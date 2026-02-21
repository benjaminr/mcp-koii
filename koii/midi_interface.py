"""
MIDI Interface for EP-133 K.O. II

This module provides a Python interface for communicating with the
Teenage Engineering EP-133 K.O. II via MIDI.

EP-133 K.O. II MIDI Specification (OS 2.0+):
- MIDI channels: 1-16 (default channel 1, receives on all channels)
- Note ranges: Group A (36-47), Group B (48-59), Group C (60-71), Group D (72-83)
- Keys mode: notes 0-127
- Supports: Note On/Off, Velocity, Pitch Bend (receive), CC#0/32/1, Program Change, Clock
- Does not support: Aftertouch, SysEx, Song Position/Select, Active Sensing
- Internal clock resolution: 96 PPQN
- MIDI I/O via USB and TRS-A (3.3V, MMA compliant)
- OS 2.0+ features: MIDI thru, per-pad MIDI channel assignment,
  MIDI note map, pitch bend/mod wheel affect playback
"""

import time
import logging
import re
import copy
from typing import Dict, List, Optional, Tuple, Union, Set, Any

import mido
from mido.ports import BaseOutput

# Configure logging
logger = logging.getLogger(__name__)

# Constants based on EP-133 K.O. II MIDI specification
PAD_GROUPS = {
    "A": range(36, 48),  # C2-B2 (Drums/Percussion)
    "B": range(48, 60),  # C3-B3 (Bass)
    "C": range(60, 72),  # C4-B4 (Melodic/Synth)
    "D": range(72, 84),  # C5-B5 (User samples)
}

# Default velocity values for pattern notation
VELOCITY_HIGH = 100  # for 'x' or 'X' in patterns
VELOCITY_LOW = 60    # for 'o' or 'O' in patterns
VELOCITY_DEFAULT = 80  # default value when not specified

# Common instrument names mapped directly to MIDI notes.
# These correspond to the default EP-133 K.O. II pad assignments on Channel A.
# This avoids the fragile chain of sound library search → pad config → pad-to-note.
COMMON_INSTRUMENTS = {
    # Channel A - Drums & Percussion
    "kick": 36,           # A. - MICRO KICK
    "kick2": 37,          # A0 - NT ALT KICK
    "bass drum": 36,      # A. alias
    "bd": 36,             # A. alias
    "snare": 40,          # A2 - NT SNARE ALT
    "snare2": 41,         # A3 - NT SNARE ALT B (shared with rimshot position)
    "sd": 40,             # A2 alias
    "rimshot": 42,        # A4 - NT RIMSHOT (via DEFAULT_PAD_CONFIG)
    "rim": 42,            # A4 alias
    "clap": 41,           # A3 - NT CLAP (via DEFAULT_PAD_CONFIG)
    "cp": 41,             # A3 alias
    "hi-hat": 43,         # A5 - NT HH CLOSED
    "hihat": 43,          # A5 alias
    "hh": 43,             # A5 alias
    "closed hat": 43,     # A5 alias
    "closed hi-hat": 43,  # A5 alias
    "open hat": 46,       # A8 - NT HH OPEN
    "open hi-hat": 46,    # A8 alias
    "oh": 46,             # A8 alias
    "ride": 44,           # A6 - NT RIDE
    "ride cymbal": 44,    # A6 alias
    "crash": 47,          # A9 - NT RIDE C / crash position
    "cymbal": 47,         # A9 alias
    "tom": 42,            # A4 - general tom
    "low tom": 42,        # A4
    "mid tom": 44,        # A6
    "high tom": 45,       # A7
    "tambourine": 43,     # A5 area (default has NT TAMBO on A4)
    "tambo": 43,          # alias
    "perc": 45,           # A7 - NT PERC
    "percussion": 45,     # A7 alias
    "shaker": 45,         # A7 area
    "cowbell": 45,        # A7 area
    "clave": 45,          # A7 area
    "conga": 45,          # A7 area
    "bongo": 45,          # A7 area

    # Channel B - Bass
    "bass": 48,           # B. - NT BASS
    "sub": 48,            # B. alias
    "bass2": 49,          # B0

    # Channel C - Melodic & Synth
    "melodic": 60,        # C. - BLUE
    "synth": 60,          # C. alias
    "piano": 61,          # C0 area
    "keys": 60,           # C. alias
    "chord": 60,          # C. alias
    "strings": 60,        # C. alias
    "organ": 60,          # C. alias
}

# Sound library categories from sounds.md
SOUND_CATEGORIES = [
    "Kicks",
    "Snares",
    "Cymbals and Hats",
    "Percussion",
    "Bass",
    "Melodic & Synth",
]

# Complete sound library
SOUND_LIBRARY = {
    "Kicks": {
        1: "MICRO KICK", 2: "NT KICK", 3: "NT KICK B", 4: "NT KICK C", 5: "NT KICK D",
        6: "LOCK KIK", 7: "KICK GRIT", 8: "KICK VERB", 9: "KICK MID", 10: "KICK BUMP",
        11: "KICK 9X9 DIRT", 12: "KICK 9X9 DIRT B", 13: "KICK 9X9 DIRT C", 14: "KICK 9X9 DIRT D",
        15: "KICK 9X9 DIRT E", 16: "KICK HARD", 17: "KICK AIR", 18: "KICK THUD", 19: "CARDIO KICK I",
        20: "AFTERPARTY KICK", 21: "NT ALT KICK", 22: "NT ALT KICK B", 23: "NT ALT KICK C",
        24: "KICK DIRT", 25: "KICK SUB", 26: "KICK SP", 27: "KICK FLUX", 28: "KICK FLUX B",
        29: "KICK SUB B", 30: "KICK OPEN", 31: "BOOMER KICK"
    },
    "Snares": {
        100: "NT SNARE", 101: "NT SNARE B", 102: "NT SNARE C", 103: "SNARE LO", 104: "SNARE MID",
        105: "SNARE HI", 106: "SNARE 6X6 1", 107: "SNARE 6X6 2", 108: "SNARE 6X6 3",
        109: "SNARE CLASSIC", 110: "SNARE FAT", 111: "SNARE SMACK", 112: "SNARE BURST",
        113: "BRUSHY SNARE 1", 114: "NT SNARE ALT", 115: "NT SNARE ALT B", 116: "NT SNARE ALT C",
        117: "SNARE RIM", 118: "SNARE PUNCH", 119: "SNARE POP", 120: "SNARE SNAP",
        121: "SNARE VINYL", 122: "SNARE MP3K", 123: "SNARE MINI BM", 124: "SNARE VINYL B",
        125: "SNARE RES", 126: "SNARE OPEN", 127: "SNARE WOOD", 128: "QUIK ROLL 3",
        129: "LONDON SNARE 2", 130: "NT RIMSHOT", 131: "NT RIMSHOT B", 132: "NT RIMSHOT C",
        133: "RIM LO", 134: "RIM MID", 135: "RIM HI", 136: "RIMSHOT DDDI", 137: "RIMSHOT VINYL",
        138: "RIMSHOT 7X7 SP", 139: "RIMSHOT DMX", 140: "RIM DARK", 141: "RIM SMACK",
        142: "RIM SNAP", 143: "KNOW RIMSHOT 1", 144: "SIDEQUEST SNARE", 145: "AKKOUNTANT RIM 2"
    },
    "Cymbals and Hats": {
        200: "NT HH CLOSED", 201: "NT HH CLOSED B", 202: "NT HH CLOSED C", 203: "CLOSED HAT LO",
        204: "CLOSED HAT MID", 205: "CLOSED HAT HI", 206: "CLOSED HAT PEDAL",
        207: "CLOSED HAT FOOT", 208: "HAT CLOSED 9X9", 209: "HAT CLOSED 5X5",
        210: "HAT CLOSED 6X6", 211: "HAT CLOSED 8X8", 212: "CLOSED HAT LO B",
        213: "CLOSED HAT HI B", 214: "CLOSED HAT AIR", 215: "GOLDEN HAT 1",
        216: "CRUNCH HAT 2", 217: "SHINE HAT 4", 218: "NT HH OPEN", 219: "NT HH OPEN B",
        220: "NT HH OPEN C", 221: "OPEN HAT REAL", 222: "OPEN HAT DRIVE",
        223: "OPEN HAT METAL", 224: "HAT OPEN 9X9", 225: "HAT OPEN 5X5",
        226: "HAT OPEN 6X6", 227: "HAT OPEN 8X8", 228: "OPEN HAT LO", 229: "OPEN HAT HI",
        230: "OPEN HAT AIR", 231: "GIRTH OPEN HAT 3", 232: "GOLDEN HAT 1 B",
        233: "LUCKY DBL HAT 2", 234: "BRUSH HAT 4", 235: "NT RIDE", 236: "NT RIDE B",
        237: "RIDE DARK", 238: "RIDE BRITE", 239: "RIDE SAKATA", 240: "CYMBAL MPI",
        241: "RIDE 7X7", 242: "RIDE DARK B", 243: "RIDE LITE", 244: "RIDE BELL",
        245: "RIDE HI", 246: "TOASTER BELL", 247: "NT RIDE C", 248: "CRASH",
        249: "CRASH 9X9", 250: "CHINA 626", 251: "SPLASH", 252: "CRASH CYM",
        253: "80 GREAT CRASH"
    },
    "Percussion": {
        300: "NT CLAP", 301: "NT CLAP B", 302: "NT CLAP C", 303: "CLAP REAL",
        304: "CLAP HARD", 305: "CLAP SNAP", 306: "CLAP VINYL", 307: "CLAP TRUMULATOR",
        308: "CLAP SP DISCO", 309: "CLAP SP DISCO B", 310: "CLAP DARK", 311: "CLAP LITE",
        312: "CLAP AIR", 313: "CLAP NOISE", 314: "GOSPEL CLAP 3", 315: "HOMECOMING CLAP",
        316: "DETROIT CLAP 2", 317: "NT TAMBO", 318: "NT TAMBO B", 319: "NT TAMBO C",
        320: "HAND DRUM HI", 321: "TAMB", 322: "HAND DRUM LO", 323: "BONGO MID 4",
        324: "CONGA MID II", 325: "AGOGO", 326: "BONGO HI", 327: "MARACA", 328: "BONGO LO",
        329: "GUIRO", 330: "CLAVE", 331: "CONGA LO", 332: "CONGA HI", 333: "CABASE LMI",
        334: "CABASA MP3K", 335: "CABASA LNNDRUM", 336: "SHAKER DMX", 337: "TAMB B",
        338: "CLAVE B", 339: "COWBELL", 340: "SHAKER", 341: "HERMES HIHAT 2",
        342: "LOWW CLAVE I", 343: "NT PERC", 344: "NT PERC B", 345: "NT PERC C"
    },
    "Bass": {
        400: "NT BASS", 401: "S95X ROUND", 402: "TUBRO BASS", 403: "E BASS ROUND",
        404: "BASIC", 405: "MP3K SUB", 406: "SYN A RE", 407: "UPRIGHT SUB", 408: "E BASS PICK",
        409: "THMP", 410: "CAT ENVELOPE", 411: "TB3X3 PUNCH", 412: "UGGBASS",
        413: "E BASS PICK B", 414: "PERFECT BASS", 415: "PRODIGY SUB", 416: "S95X SUB",
        417: "BASS THUB", 418: "ROCKELBASS MID", 419: "E BASS DIST", 420: "OB SUB",
        421: "CX TONE", 422: "BUZZ BASS", 423: "ROCKELBASS SHORT", 424: "MNO EVO FILTER",
        425: "SYNTH 4TH HIT", 426: "THIRTY SEVEN SUB", 427: "ORGA", 428: "MUD",
        429: "REESE", 430: "P.SIX SIMPLE", 431: "S612 ELECTRIC", 432: "AKUBASS MIDLONG",
        458: "PUFF", 459: "RUDE TWANG"
    },
    "Melodic & Synth": {
        500: "BLUE", 501: "PIANO S95X", 502: "WURLI CLEAN", 503: "MUTE STRATO",
        504: "CUTE EMU FLUTE", 505: "ULTRA", 506: "SQUICK", 507: "CLAV 360 PHASER",
        508: "BABY CHORD", 509: "BG VOCAL", 510: "SKYLINE STRING", 511: "OCTAVE STAB",
        512: "TRUMPET BREEZY", 513: "SCARY VIBES", 514: "SLY SYNTH CHORD",
        515: "EPIANO 360", 516: "ORGAN DX VERB", 517: "PLUCK HI BASS", 518: "PLUCK HYBRID",
        519: "PROPHET PIANO", 520: "EPIANO 360 BASS", 521: "HOUSEORGAN DE-EX",
        522: "SOOTHE STRING", 523: "CELLO PLUCKZ", 524: "HIGH PAN", 525: "SYNTH MICRO FUNK",
        526: "DR ORGAN CHORD", 527: "LEADAFT", 528: "SOOTHE STRONG", 529: "SIMPLE TROMBONE",
        530: "CELLO 360", 531: "FLUTE 360 FILTER", 532: "ORGAN DX200 STAB",
        533: "WATERCHORD AM7", 534: "SAD GUITAR", 535: "HORN 360 ENGLISH", 536: "STRINGS 360",
        537: "HOUSE CHORD EM7", 538: "UPRIGHT CHORD", 539: "EXOTIC PLUCK", 540: "SKY LEAD",
        541: "STRINGS DR", 542: "LIQUID CHORD EM7", 543: "CHORDY F9SUS4", 544: "BROKEN BELL PERC",
        545: "PLING CHORD", 546: "S612 VERB HIT", 547: "DR", 548: "VOX S612 DARK",
        549: "SITAR ONE SHOT", 550: "LOOK ORGAN", 551: "THIRTY 7 STAB", 552: "BUZZ DELAY",
        553: "VOX S612 EH", 554: "GUZHENG", 555: "NT CHORDY", 556: "FX BIRDS TAPE",
        557: "VOX S612 GATED", 558: "O3D", 559: "SEARCH CHORD"
    }
}

# Default pad configuration mapping.
# Layout per channel is a 4x3 grid, ordered bottom-to-top:
#   Row 0: [pad_dot, pad_0, pad_FX]  (bottom special row)
#   Row 1: [pad_1,   pad_2, pad_3]   (bottom numbered row)
#   Row 2: [pad_4,   pad_5, pad_6]   (middle numbered row)
#   Row 3: [pad_7,   pad_8, pad_9]   (top numbered row)
# Values are sound IDs from SOUND_LIBRARY.
DEFAULT_PAD_CONFIG = {
    "A": {  # Channel A - Drums & Percussion
        "pads": [
            [1, 21, 300],       # A., A0, AFX: MICRO KICK, NT ALT KICK, NT CLAP
            [100, 114, 130],    # A1, A2, A3: NT SNARE, NT SNARE ALT, NT RIMSHOT
            [317, 200, 218],    # A4, A5, A6: NT TAMBO, NT HH CLOSED, NT HH OPEN
            [343, 235, 247],    # A7, A8, A9: NT PERC, NT RIDE, NT RIDE C
        ]
    },
    "B": {  # Channel B - Bass
        "pads": [
            [400, 405, 410],    # B., B0, BFX: NT BASS, MP3K SUB, CAT ENVELOPE
            [415, 420, 425],    # B1, B2, B3: PRODIGY SUB, OB SUB, SYNTH 4TH HIT
            [430, 402, 404],    # B4, B5, B6: P.SIX SIMPLE, TUBRO BASS, BASIC
            [407, 408, 401],    # B7, B8, B9: UPRIGHT SUB, E BASS PICK, S95X ROUND
        ]
    },
    "C": {  # Channel C - Melodic & Synth
        "pads": [
            [500, 505, 510],    # C., C0, CFX: BLUE, ULTRA, SKYLINE STRING
            [515, 520, 525],    # C1, C2, C3: EPIANO 360, EPIANO 360 BASS, SYNTH MICRO FUNK
            [530, 343, 540],    # C4, C5, C6: CELLO 360, NT PERC, SKY LEAD
            [545, 550, 555],    # C7, C8, C9: PLING CHORD, LOOK ORGAN, NT CHORDY
        ]
    }
}

# MIDI note name to number mapping
NOTE_TO_NUMBER = {
    'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
    'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8,
    'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11
}

# Musical scale step patterns (intervals in semitones)
SCALE_PATTERNS = {
    "major": [0, 2, 4, 5, 7, 9, 11],  # W-W-H-W-W-W-H
    "minor": [0, 2, 3, 5, 7, 8, 10],  # W-H-W-W-H-W-W
    "dorian": [0, 2, 3, 5, 7, 9, 10],  # W-H-W-W-W-H-W
    "phrygian": [0, 1, 3, 5, 7, 8, 10],  # H-W-W-W-H-W-W
    "lydian": [0, 2, 4, 6, 7, 9, 11],  # W-W-W-H-W-W-H
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],  # W-W-H-W-W-H-W
    "locrian": [0, 1, 3, 5, 6, 8, 10],  # H-W-W-H-W-W-W
    "major_pentatonic": [0, 2, 4, 7, 9],  # Major without 4th and 7th
    "minor_pentatonic": [0, 3, 5, 7, 10],  # Minor without 2nd and 6th
    "blues": [0, 3, 5, 6, 7, 10],  # Minor pentatonic + blue note
    "chromatic": list(range(12))  # All 12 semitones
}


class MIDIInterface:
    """Interface for communicating with the EP-133 K.O. II via MIDI."""

    def __init__(self):
        """Initialize the MIDI interface."""
        self.port: Optional[BaseOutput] = None
        self.channel: int = 0  # MIDI channels are 0-indexed in mido
        self.connected: bool = False
        # Pattern storage: name → {pattern_text, bpm, instruments, events}
        self._patterns: Dict[str, Dict[str, Any]] = {}
        # Song storage: name → {patterns: [(pattern_name, repeats)], bpm}
        self._songs: Dict[str, Dict[str, Any]] = {}
    
    def list_ports(self) -> List[str]:
        """List all available MIDI output ports."""
        return mido.get_output_names()
    
    def connect(self, port_name: Optional[str] = None, port_index: Optional[int] = None) -> bool:
        """
        Connect to a MIDI output port by name or index.
        
        Args:
            port_name: The name of the MIDI port to connect to
            port_index: The index of the MIDI port to connect to
            
        Returns:
            bool: True if connected successfully, False otherwise
        """
        try:
            available_ports = mido.get_output_names()
            
            if not available_ports:
                logger.error("No MIDI ports found")
                return False
            
            if port_name:
                # Try to find exact match
                if port_name in available_ports:
                    self.port = mido.open_output(port_name)
                    self.connected = True
                    logger.info(f"Connected to MIDI port: {port_name}")
                    return True
                
                # Try to find partial match
                matching_ports = [p for p in available_ports if port_name.lower() in p.lower()]
                if matching_ports:
                    self.port = mido.open_output(matching_ports[0])
                    self.connected = True
                    logger.info(f"Connected to MIDI port: {matching_ports[0]}")
                    return True
                
                logger.error(f"MIDI port '{port_name}' not found")
                return False
            
            elif port_index is not None:
                if 0 <= port_index < len(available_ports):
                    self.port = mido.open_output(available_ports[port_index])
                    self.connected = True
                    logger.info(f"Connected to MIDI port: {available_ports[port_index]}")
                    return True
                
                logger.error(f"Invalid port index: {port_index}. Available ports: 0-{len(available_ports)-1}")
                return False
            
            # Try to connect to a KO-II port if neither port_name nor port_index provided
            ko_ports = [p for p in available_ports if any(
                name in p.lower() for name in ["ko", "ko-ii", "ep-133", "teenage"]
            )]
            if ko_ports:
                self.port = mido.open_output(ko_ports[0])
                self.connected = True
                logger.info(f"Connected to MIDI port: {ko_ports[0]}")
                return True
            
            # As a last resort, connect to the first available port
            self.port = mido.open_output(available_ports[0])
            self.connected = True
            logger.info(f"Connected to MIDI port: {available_ports[0]}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to MIDI port: {e}")
            self.connected = False
            return False
    
    def disconnect(self) -> bool:
        """
        Disconnect from the current MIDI port.
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.port:
            return True  # Already disconnected
            
        try:
            self.port.close()
            self.port = None
            self.connected = False
            logger.info("Disconnected from MIDI port")
            return True
        except Exception as e:
            logger.error(f"Error disconnecting from MIDI port: {e}")
            return False
    
    def set_channel(self, channel: int) -> bool:
        """
        Set the MIDI channel (1-16, converted to 0-15 internally).
        
        Args:
            channel: MIDI channel number (1-16)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if 1 <= channel <= 16:
            self.channel = channel - 1  # Convert to 0-indexed
            logger.info(f"MIDI channel set to {channel}")
            return True
        
        logger.error(f"Invalid MIDI channel: {channel}. Must be between 1 and 16.")
        return False
    
    def _ensure_connected(self) -> bool:
        """
        Ensure that the MIDI interface is connected.
        
        Returns:
            bool: True if connected, False otherwise
        """
        if not self.connected or not self.port:
            logger.error("MIDI interface not connected")
            return False
        return True
    
    def parse_note_name(self, note_name: str) -> int:
        """
        Parse a note name (e.g., 'C3', 'F#4') into a MIDI note number.
        
        Args:
            note_name: Note name like 'C3', 'F#4', etc.
            
        Returns:
            int: MIDI note number
        
        Raises:
            ValueError: If the note name is invalid
        """
        if not note_name:
            raise ValueError("Note name cannot be empty")
        
        # Handle numeric note values
        if note_name.isdigit():
            note_num = int(note_name)
            if 0 <= note_num <= 127:
                return note_num
            raise ValueError(f"Note number {note_num} is out of range (0-127)")
        
        # Parse note name format (e.g., 'C3', 'F#4')
        if len(note_name) < 2:
            raise ValueError(f"Invalid note name: {note_name}")
        
        # Extract note and octave
        if note_name[1] in ['#', 'b']:
            if len(note_name) < 3:
                raise ValueError(f"Invalid note name: {note_name}")
            note = note_name[:2]
            octave = note_name[2:]
        else:
            note = note_name[0]
            octave = note_name[1:]
        
        # Validate note
        if note[0].upper() not in NOTE_TO_NUMBER:
            raise ValueError(f"Invalid note name: {note_name}")
        
        # Validate octave
        try:
            octave_num = int(octave)
        except ValueError:
            raise ValueError(f"Invalid octave in note name: {note_name}")
        
        # Calculate MIDI note number
        note_num = NOTE_TO_NUMBER[note[0].upper()]
        if len(note) > 1:
            if note[1] == '#':
                note_num += 1
            elif note[1] == 'b':
                note_num -= 1
        
        midi_note = (octave_num + 1) * 12 + note_num
        
        if not 0 <= midi_note <= 127:
            raise ValueError(f"Note {note_name} is out of MIDI range (0-127)")
        
        return midi_note
    
    def play_note(self, note: Union[int, str], velocity: int = 100, duration: float = 0.1) -> bool:
        """
        Play a MIDI note on the EP-133 K.O. II.
        
        Args:
            note: MIDI note number (0-127) or note name (e.g., 'C3')
            velocity: Note velocity (0-127)
            duration: Note duration in seconds
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._ensure_connected():
            return False
        
        try:
            # Convert note name to MIDI note number if necessary
            if isinstance(note, str):
                note_num = self.parse_note_name(note)
            else:
                note_num = note
            
            # Validate note number
            if not 0 <= note_num <= 127:
                logger.error(f"Invalid note number: {note_num}. Must be between 0 and 127.")
                return False
            
            # Validate velocity
            velocity = max(0, min(127, velocity))
            
            # Send note on message
            self.port.send(mido.Message('note_on', note=note_num, velocity=velocity, channel=self.channel))
            
            # Wait for specified duration
            time.sleep(duration)
            
            # Send note off message
            self.port.send(mido.Message('note_off', note=note_num, velocity=0, channel=self.channel))
            
            logger.info(f"Played note {note_num} with velocity {velocity} for {duration} seconds")
            return True
            
        except Exception as e:
            logger.error(f"Error playing note: {e}")
            return False
    
    def play_pattern(self, notes: List[Tuple[Union[int, str], int, float]]) -> bool:
        """
        Play a pattern of notes on the EP-133 K.O. II.
        
        Args:
            notes: List of tuples containing (note, velocity, duration)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._ensure_connected():
            return False
        
        try:
            for note, velocity, duration in notes:
                # Play each note
                self.play_note(note, velocity, duration)
            
            logger.info(f"Played pattern with {len(notes)} notes")
            return True
            
        except Exception as e:
            logger.error(f"Error playing pattern: {e}")
            return False
    
    def send_program_change(self, program: int) -> bool:
        """
        Send a program change message to switch samples.
        
        Args:
            program: Program number (0-127)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._ensure_connected():
            return False
        
        try:
            # Validate program number
            if not 0 <= program <= 127:
                logger.error(f"Invalid program number: {program}. Must be between 0 and 127.")
                return False
            
            # Send program change message
            self.port.send(mido.Message('program_change', program=program, channel=self.channel))
            
            logger.info(f"Sent program change {program}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending program change: {e}")
            return False
    
    def send_midi_clock(self, bpm: int, duration: float) -> bool:
        """
        Send MIDI clock messages at the specified BPM for the specified duration.
        
        Args:
            bpm: Tempo in beats per minute
            duration: Duration to send clock messages in seconds
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._ensure_connected():
            return False
        
        try:
            # Validate BPM
            if bpm <= 0:
                logger.error(f"Invalid BPM: {bpm}. Must be positive.")
                return False
            
            # Calculate interval between clock messages (24 per quarter note)
            interval = 60.0 / (bpm * 24)
            
            # Calculate number of clock messages to send
            num_clocks = int(duration / interval)
            
            # Send start message
            self.port.send(mido.Message('start'))
            
            # Send clock messages
            for _ in range(num_clocks):
                self.port.send(mido.Message('clock'))
                time.sleep(interval)
            
            # Send stop message
            self.port.send(mido.Message('stop'))
            
            logger.info(f"Sent MIDI clock at {bpm} BPM for {duration} seconds")
            return True
            
        except Exception as e:
            logger.error(f"Error sending MIDI clock: {e}")
            return False
    
    def pad_to_note(self, pad_reference: str) -> int:
        """
        Convert a pad reference (e.g., 'A0', 'B3', 'C7') to a MIDI note number.
        
        The physical layout of the EP-133 K.O. II pads is mapped to MIDI notes as follows:
        
        For Channel A:
        +----+----+----+
        | A7 | A8 | A9 |  = [45, 46, 47]  (Top row)
        +----+----+----+
        | A4 | A5 | A6 |  = [42, 43, 44]  (Middle row)
        +----+----+----+
        | A1 | A2 | A3 |  = [39, 40, 41]  (Bottom row)
        +----+----+----+
        | A. | A0 | FX |  = [36, 37, 38]  (Bottom special row)
        +----+----+----+
        
        The same pattern applies to channels B (starting at 48), C (starting at 60), and D (starting at 72).
        
        Args:
            pad_reference: Pad reference string (e.g., 'A0', 'B3', 'C7')
            
        Returns:
            int: MIDI note number
            
        Raises:
            ValueError: If the pad reference is invalid
        """
        if not pad_reference or len(pad_reference) < 2:
            raise ValueError(f"Invalid pad reference: {pad_reference}")
        
        # Parse the pad reference
        channel = pad_reference[0].upper()
        if channel not in PAD_GROUPS:
            raise ValueError(f"Invalid pad channel: {channel}. Must be A, B, C, or D.")
        
        # Map the pad label to the correct position in the MIDI note range
        base_note = min(PAD_GROUPS[channel])  # Start of the channel's MIDI range (e.g., 36 for A)
        
        # Special cases for the bottom row
        if pad_reference[1:] == '.':
            # A. = 36, B. = 48, etc. (bottom left)
            offset = 0
        elif pad_reference[1:] == '0':
            # A0 = 37, B0 = 49, etc. (bottom middle)
            offset = 1
        elif pad_reference[1:].upper() == 'FX':
            # AFX = 38, BFX = 50, etc. (bottom right)
            offset = 2
        else:
            try:
                pad_num = int(pad_reference[1:])
                
                if pad_num < 1 or pad_num > 9:
                    raise ValueError(f"Invalid pad number: {pad_num}. Must be between 1-9, '.' or '0'.")
                
                # Convert the pad number (1-9) to MIDI note offset
                # The layout is bottom-to-top, left-to-right
                # For Channel A: A1=39, A2=40, A3=41, A4=42, A5=43, A6=44, A7=45, A8=46, A9=47
                
                row = (pad_num - 1) // 3  # 0 = bottom row, 1 = middle row, 2 = top row
                col = (pad_num - 1) % 3   # 0 = left, 1 = middle, 2 = right
                
                # Start at MIDI note 39 (which is base_note + 3) for the first pad (A1)
                offset = 3 + (row * 3) + col
                
            except ValueError:
                raise ValueError(f"Invalid pad reference: {pad_reference[1:]}. Must be a number (1-9), '.' or '0'.")
        
        # Final MIDI note number
        note = base_note + offset
        
        # Sanity check to ensure the note is within the valid range for the channel
        if note not in PAD_GROUPS[channel]:
            raise ValueError(f"Calculated note {note} is outside valid range for channel {channel}.")
        
        return note

    def find_sound_by_name(self, name: str) -> Optional[int]:
        """
        Find a sound ID by its name (full or partial match).
        
        Args:
            name: The sound name or part of the name to search for
            
        Returns:
            int: The sound ID if found, None otherwise
        """
        name_upper = name.upper()
        best_match = None
        
        # Try exact match first
        for category, sounds in SOUND_LIBRARY.items():
            for sound_id, sound_name in sounds.items():
                if sound_name == name_upper:
                    return sound_id
        
        # Then try contains match
        for category, sounds in SOUND_LIBRARY.items():
            for sound_id, sound_name in sounds.items():
                if name_upper in sound_name:
                    # If we already found a match, prefer the shorter name
                    # as it's likely more specific
                    if best_match is None or len(sound_name) < len(SOUND_LIBRARY[best_match[0]][best_match[1]]):
                        best_match = (category, sound_id)
        
        # Return the best match if found
        if best_match:
            return best_match[1]
        
        return None
    
    def interpret_trigger_reference(self, reference: str) -> int:
        """
        Interpret a reference that could be a common instrument name, pad label,
        MIDI note, or sound name.

        Resolution order:
        1. Common instrument names (kick, snare, hi-hat, etc.) → direct MIDI note
        2. Direct MIDI note number (0-127)
        3. Pad reference (A., A0, A1-A9, B., etc.)
        4. Sound library name search → default pad config lookup

        Args:
            reference: The reference string (e.g., "kick", "A0", "36", "MICRO KICK")

        Returns:
            int: MIDI note number

        Raises:
            ValueError: If the reference can't be interpreted
        """
        logger.info(f"Interpreting trigger reference: '{reference}'")
        ref_stripped = reference.strip().strip('"').strip("'")

        # Case 1: Common instrument name (most frequent use case)
        ref_lower = ref_stripped.lower()
        if ref_lower in COMMON_INSTRUMENTS:
            note = COMMON_INSTRUMENTS[ref_lower]
            logger.info(f"Interpreted as common instrument: {ref_stripped} → MIDI note {note}")
            return note

        # Case 2: Direct MIDI note number
        if ref_stripped.isdigit():
            note_num = int(ref_stripped)
            if 0 <= note_num <= 127:
                logger.info(f"Interpreted as MIDI note number: {note_num}")
                return note_num
            raise ValueError(f"MIDI note {note_num} is out of range (0-127)")

        # Case 3: Pad reference (A0, B3, C., DFX, etc.)
        if (len(ref_stripped) >= 2 and ref_stripped[0].upper() in PAD_GROUPS and
            (ref_stripped[1:].isdigit() or ref_stripped[1:] == '.' or ref_stripped[1:].upper() == 'FX')):
            try:
                note = self.pad_to_note(ref_stripped)
                logger.info(f"Interpreted as pad reference: {ref_stripped} → MIDI note {note}")
                return note
            except ValueError:
                pass

        # Case 4: Sound library name search → pad config lookup
        sound_id = self.find_sound_by_name(ref_stripped)
        if sound_id is not None:
            logger.info(f"Found matching sound in library: {ref_stripped} → Sound ID {sound_id}")
            for channel, config in DEFAULT_PAD_CONFIG.items():
                for row_idx, row in enumerate(config["pads"]):
                    if sound_id in row:
                        col_idx = row.index(sound_id)
                        if row_idx == 0:  # Bottom special row
                            if col_idx == 0:
                                pad_ref = f"{channel}."
                            elif col_idx == 1:
                                pad_ref = f"{channel}0"
                            else:
                                pad_ref = f"{channel}FX"
                        else:
                            pad_num = ((row_idx - 1) * 3) + col_idx + 1
                            pad_ref = f"{channel}{pad_num}"
                        note = self.pad_to_note(pad_ref)
                        logger.info(f"Sound mapped to pad {pad_ref} → MIDI note {note}")
                        return note

        # Last resort - default to kick drum
        logger.warning(f"Could not interpret reference: {reference} - defaulting to A. (kick drum)")
        return self.pad_to_note("A.")
    
    def _extract_instrument_reference(self, comment: str) -> str:
        """
        Extract the instrument reference from a comment.
        
        Args:
            comment: The comment string from a pattern line
            
        Returns:
            str: The extracted instrument reference
        """
        # Try to extract a quoted string first
        quoted_match = re.search(r'"([^"]+)"', comment) or re.search(r"'([^']+)'", comment)
        if quoted_match:
            return quoted_match.group(1)
        
        # Otherwise, take the first word
        return comment.split()[0]
    
    def _parse_pattern_line(self, line: str) -> List[Optional[int]]:
        """
        Pre-parse a single pattern line into a list of velocity values.

        Each element in the returned list represents one 16th note step.
        None means a rest (no hit), an int is the velocity (1-127).

        Supported notation:
        - 'x' or 'X': High velocity hit (100)
        - 'o' or 'O': Low velocity hit (60)
        - '.': Rest (no hit)
        - '-': Rest (alternative notation)
        - '1'-'9': Velocity level (1=14, 2=28, ..., 9=126)
        - 'v' + 1-3 digits: Exact velocity (e.g., v64, v127, v30)
        - ' ': Ignored (allows visual grouping like 'x... x... x... x...')

        The key fix: 'v64' is treated as a single step (one hit at velocity 64),
        not three separate steps. The digits after 'v' are consumed as part of
        the velocity value, not as separate step characters.

        Args:
            line: A pattern line string (without the # comment part)

        Returns:
            List of velocity values (int) or None for rests.
        """
        events: List[Optional[int]] = []
        i = 0
        while i < len(line):
            char = line[i]
            if char == '.' or char == '-':
                events.append(None)
                i += 1
            elif char in ('x', 'X'):
                events.append(VELOCITY_HIGH)
                i += 1
            elif char in ('o', 'O'):
                events.append(VELOCITY_LOW)
                i += 1
            elif char.isdigit() and '1' <= char <= '9':
                events.append(int(char) * 14)
                i += 1
            elif char == 'v':
                # Parse velocity value: consume 'v' + up to 3 digits as ONE step
                i += 1
                vel_str = ''
                while i < len(line) and line[i].isdigit() and len(vel_str) < 3:
                    vel_str += line[i]
                    i += 1
                if vel_str:
                    events.append(min(127, max(1, int(vel_str))))
                else:
                    events.append(VELOCITY_DEFAULT)
            elif char == ' ':
                # Skip spaces - allow visual grouping in patterns
                i += 1
            elif char == '0':
                # '0' = rest (mnemonic: zero velocity = silence)
                events.append(None)
                i += 1
            else:
                # Unknown character = rest
                events.append(None)
                i += 1
        return events

    def parse_drum_pattern(self, pattern: str, bpm: int = 120, repeat: int = 1) -> bool:
        """
        Parse and play a text-based drum pattern.

        Format:
        x...x...x...x...  # kick
        ....x.......x...  # snare
        x.x.x.x.x.x.x.x  # hi-hat

        The pattern can reference sounds in four ways (checked in order):
        1. Common instrument names (kick, snare, hi-hat, bass, etc.)
        2. MIDI note numbers (36, 40, 43, etc.)
        3. Pad labels (A., A0, A1-A9, B., etc.)
        4. Sound library names ("MICRO KICK", "NT SNARE", etc.)

        Notation per step:
        - 'x'/'X': Hit at velocity 100
        - 'o'/'O': Soft hit at velocity 60
        - '1'-'9': Hit at scaled velocity (1=14 to 9=126)
        - 'v' + digits: Hit at exact velocity (e.g., v64, v127)
        - '.'/'-'/'0': Rest (no hit)
        - ' ': Ignored (visual grouping)

        Args:
            pattern: Text-based drum pattern
            bpm: Tempo in beats per minute (default 120)
            repeat: Number of times to repeat the pattern (default 1)

        Returns:
            bool: True if successful, False otherwise
        """
        if not self._ensure_connected():
            return False

        try:
            lines = [line.strip() for line in pattern.split('\n') if line.strip()]

            # Parse each line into events and instrument mapping
            parsed_tracks: List[Tuple[List[Optional[int]], int, str]] = []
            unrecognized_instruments: List[str] = []

            for line in lines:
                if '#' in line:
                    pattern_part, comment = line.split('#', 1)
                    pattern_part = pattern_part.strip()
                    comment = comment.strip()

                    reference = self._extract_instrument_reference(comment)
                    try:
                        note = self.interpret_trigger_reference(reference)
                        logger.info(f"Mapped '{reference}' to MIDI note {note}")
                        events = self._parse_pattern_line(pattern_part)
                        parsed_tracks.append((events, note, comment))
                    except ValueError as e:
                        logger.warning(f"Could not interpret reference '{reference}': {e}")
                        unrecognized_instruments.append(comment)
                elif any(c in 'xXoO123456789' for c in line):
                    events = self._parse_pattern_line(line)
                    parsed_tracks.append((events, self.pad_to_note("A."), "kick (default)"))

            if not parsed_tracks:
                if unrecognized_instruments:
                    logger.error(f"No valid pattern lines found. Unrecognized: {', '.join(unrecognized_instruments)}")
                else:
                    logger.error("No valid pattern lines found")
                return False

            # Determine step count from the longest track
            step_count = max(len(events) for events, _, _ in parsed_tracks)
            step_duration = 60.0 / bpm / 4  # 16th note duration

            logger.info(f"Playing pattern at {bpm} BPM, {step_count} steps, {len(parsed_tracks)} instruments, {repeat}x repeat")
            for events, note, name in parsed_tracks:
                logger.info(f"  Track: {name} (MIDI note: {note}, {len(events)} steps)")

            if unrecognized_instruments:
                logger.warning(f"Ignored unrecognized instruments: {', '.join(unrecognized_instruments)}")

            # Play the pattern (with repeats)
            for rep in range(repeat):
                for step in range(step_count):
                    notes_to_play: List[Tuple[int, int]] = []

                    for events, note, _ in parsed_tracks:
                        if step < len(events) and events[step] is not None:
                            notes_to_play.append((note, events[step]))

                    # Send all note-on messages for this step
                    for note, velocity in notes_to_play:
                        self.port.send(mido.Message(
                            'note_on', note=note, velocity=velocity, channel=self.channel
                        ))

                    time.sleep(step_duration)

                    # Send all note-off messages
                    for note, _ in notes_to_play:
                        self.port.send(mido.Message(
                            'note_off', note=note, velocity=0, channel=self.channel
                        ))

            played = len(parsed_tracks)
            ignored = len(unrecognized_instruments)
            status = f"Played drum pattern at {bpm} BPM with {played} instruments"
            if repeat > 1:
                status += f" ({repeat} repeats)"
            if ignored > 0:
                status += f" (ignored {ignored} unrecognized instruments)"
            logger.info(status)
            return True

        except Exception as e:
            logger.error(f"Error playing drum pattern: {e}")
            return False
    
    def get_default_sound_for_pad(self, pad_reference: str) -> Optional[int]:
        """
        Get the default sound ID mapped to a specific pad.
        
        Args:
            pad_reference: Pad reference string (e.g., 'A0', 'B3', 'C7')
            
        Returns:
            int: Sound ID if found, None otherwise
        """
        if len(pad_reference) < 2:
            return None
            
        channel = pad_reference[0].upper()
        if channel not in DEFAULT_PAD_CONFIG:
            return None
        
        # Parse the pad label to determine row and column
        suffix = pad_reference[1:]
        
        if suffix == '.':
            row, col = 0, 0
        elif suffix == '0':
            row, col = 0, 1
        elif suffix.upper() == 'FX':
            row, col = 0, 2
        else:
            try:
                pad_num = int(suffix)
                if 1 <= pad_num <= 9:
                    # Calculate row and column based on pad number
                    # Convert to DEFAULT_PAD_CONFIG indices
                    row_idx = (pad_num - 1) // 3 + 1  # 1 = bottom, 2 = middle, 3 = top
                    col_idx = (pad_num - 1) % 3       # 0 = left, 1 = middle, 2 = right
                    row, col = row_idx, col_idx
                else:
                    return None
            except ValueError:
                return None
        
        # Check if the pad exists in the configuration
        config = DEFAULT_PAD_CONFIG[channel]
        if row >= len(config["pads"]):
            return None
            
        pad_row = config["pads"][row]
        if col >= len(pad_row):
            return None
            
        return pad_row[col]
        
    def get_scale_notes(self, scale_name: str, root_note: str, octave: int = 3) -> List[int]:
        """
        Get the MIDI note numbers for a musical scale.
        
        Args:
            scale_name: Name of the scale (e.g., 'major', 'minor', 'dorian')
            root_note: Root note of the scale (e.g., 'C', 'F#', 'Eb')
            octave: Starting octave for the scale (0-10)
            
        Returns:
            List[int]: MIDI note numbers for the scale
            
        Raises:
            ValueError: If the scale name or root note is invalid
        """
        # Validate scale name
        scale_name = scale_name.lower()
        if scale_name not in SCALE_PATTERNS:
            valid_scales = ", ".join(SCALE_PATTERNS.keys())
            raise ValueError(f"Invalid scale name: {scale_name}. Valid options: {valid_scales}")
        
        # Validate root note
        root_upper = root_note.upper()
        if root_upper not in NOTE_TO_NUMBER and not any(root_upper.startswith(n) for n in NOTE_TO_NUMBER):
            valid_notes = ", ".join(sorted(set(n for n in NOTE_TO_NUMBER if len(n) == 1)))
            valid_notes += " (with optional # or b)"
            raise ValueError(f"Invalid root note: {root_note}. Valid options: {valid_notes}")
        
        # Parse the root note
        if len(root_upper) > 1 and root_upper[1] in ['#', 'b']:
            note_name = root_upper[:2]
        else:
            note_name = root_upper[0]
        
        # Get the root note number
        root_number = NOTE_TO_NUMBER.get(note_name)
        if root_number is None:
            raise ValueError(f"Could not parse root note: {root_note}")
        
        # Get the scale pattern
        scale_pattern = SCALE_PATTERNS[scale_name]
        
        # Generate the scale notes
        midi_notes = []
        base_note = (octave + 1) * 12 + root_number
        
        # Generate two octaves of the scale for more flexibility
        for octave_offset in range(2):
            for step in scale_pattern:
                midi_note = base_note + step + (octave_offset * 12)
                if 0 <= midi_note <= 127:  # Valid MIDI note range
                    midi_notes.append(midi_note)
        
        return midi_notes
    
    def map_pads_to_scale(self, channel: str, scale_name: str, root_note: str, octave: int = 3) -> Dict[str, int]:
        """
        Map pads in a channel to notes in a musical scale.
        
        Args:
            channel: Pad channel ('A', 'B', 'C', or 'D')
            scale_name: Name of the scale (e.g., 'major', 'minor', 'dorian')
            root_note: Root note of the scale (e.g., 'C', 'F#', 'Eb')
            octave: Starting octave for the scale (0-10)
            
        Returns:
            Dict[str, int]: Mapping of pad labels to MIDI notes in the scale
            
        Raises:
            ValueError: If the channel, scale name, or root note is invalid
        """
        # Validate channel
        channel = channel.upper()
        if channel not in PAD_GROUPS:
            raise ValueError(f"Invalid channel: {channel}. Must be A, B, C, or D.")
        
        # Get the scale notes
        scale_notes = self.get_scale_notes(scale_name, root_note, octave)
        
        # Define the pad layout in logical order for playing scales
        # From bottom left to top right, row by row
        pad_layout = [
            f"{channel}.",  # Bottom row left
            f"{channel}0",  # Bottom row middle
            f"{channel}1",  # Bottom row right
            f"{channel}2",  # Second row left
            f"{channel}3",  # Second row middle
            f"{channel}4",  # Second row right
            f"{channel}5",  # Third row left
            f"{channel}6",  # Third row middle
            f"{channel}7",  # Third row right
            f"{channel}8",  # Top row left
            f"{channel}9",  # Top row middle
        ]
        
        # Map pads to scale notes
        pad_to_note = {}
        for i, pad in enumerate(pad_layout):
            if i < len(scale_notes):
                pad_to_note[pad] = scale_notes[i]

        return pad_to_note

    def play_scale_sequence(
        self,
        channel: str,
        scale_name: str,
        root_note: str,
        sequence: List[int],
        velocity: int = 100,
        duration: float = 0.2,
        interval: float = 0.1,
        octave: int = 3
    ) -> bool:
        """
        Play a sequence of notes from a musical scale.

        Args:
            channel: Pad channel ('A', 'B', 'C', or 'D')
            scale_name: Name of the scale (e.g., 'major', 'minor', 'blues')
            root_note: Root note of the scale (e.g., 'C', 'F#', 'Eb')
            sequence: List of scale degrees (1-based). 0 = rest. Negative = lower octave.
            velocity: Note velocity (0-127)
            duration: Note duration in seconds
            interval: Time between notes in seconds
            octave: Starting octave for the scale (0-10)

        Returns:
            bool: True if successful, False otherwise
        """
        if not self._ensure_connected():
            return False

        try:
            scale_notes = self.get_scale_notes(scale_name, root_note, octave)
            if not scale_notes:
                logger.error("No scale notes generated")
                return False

            velocity = max(0, min(127, velocity))

            for i, degree in enumerate(sequence):
                if degree == 0:
                    # Rest
                    time.sleep(duration + interval)
                    continue

                # Handle negative degrees (lower octave)
                if degree < 0:
                    idx = abs(degree) - 1
                    if idx < len(scale_notes):
                        note = scale_notes[idx] - 12
                    else:
                        note = scale_notes[0] - 12
                else:
                    idx = degree - 1
                    if idx < len(scale_notes):
                        note = scale_notes[idx]
                    else:
                        # Wrap around within available notes
                        note = scale_notes[idx % len(scale_notes)]

                # Clamp to valid MIDI range
                note = max(0, min(127, note))

                # Play the note
                self.port.send(mido.Message(
                    'note_on', note=note, velocity=velocity, channel=self.channel
                ))
                time.sleep(duration)
                self.port.send(mido.Message(
                    'note_off', note=note, velocity=0, channel=self.channel
                ))

                # Wait between notes (except after the last note)
                if i < len(sequence) - 1:
                    time.sleep(interval)

            logger.info(
                f"Played scale sequence: {scale_name} in {root_note} "
                f"(channel {channel}, octave {octave}, {len(sequence)} notes)"
            )
            return True

        except Exception as e:
            logger.error(f"Error playing scale sequence: {e}")
            return False

    # ----------------------------------------------------------------
    # Pattern Storage & Management
    # ----------------------------------------------------------------

    def store_pattern(self, name: str, pattern: str, bpm: int = 120) -> Dict[str, Any]:
        """
        Store a named pattern for later recall and use in songs.

        Args:
            name: Unique name for the pattern (e.g., "verse_drums", "chorus_bass")
            pattern: Text-based drum pattern string
            bpm: Default BPM for this pattern

        Returns:
            Dict with pattern info including name, instrument count, step count.
        """
        lines = [line.strip() for line in pattern.split('\n') if line.strip()]
        tracks = []
        for line in lines:
            if '#' in line:
                pattern_part, comment = line.split('#', 1)
                pattern_part = pattern_part.strip()
                comment = comment.strip()
                reference = self._extract_instrument_reference(comment)
                try:
                    note = self.interpret_trigger_reference(reference)
                    events = self._parse_pattern_line(pattern_part)
                    tracks.append({
                        "events": events,
                        "note": note,
                        "name": comment,
                        "pattern_text": pattern_part,
                    })
                except ValueError:
                    logger.warning(f"Skipping unrecognized instrument in stored pattern: {comment}")

        step_count = max((len(t["events"]) for t in tracks), default=0)

        self._patterns[name] = {
            "pattern_text": pattern,
            "bpm": bpm,
            "tracks": tracks,
            "step_count": step_count,
        }

        logger.info(f"Stored pattern '{name}': {len(tracks)} tracks, {step_count} steps, {bpm} BPM")
        return {
            "name": name,
            "instruments": len(tracks),
            "steps": step_count,
            "bpm": bpm,
            "track_names": [t["name"] for t in tracks],
        }

    def get_pattern(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get a stored pattern by name.

        Args:
            name: Pattern name

        Returns:
            Pattern dict if found, None otherwise.
        """
        return self._patterns.get(name)

    def list_patterns(self) -> List[Dict[str, Any]]:
        """
        List all stored patterns.

        Returns:
            List of pattern summaries.
        """
        result = []
        for name, pat in self._patterns.items():
            result.append({
                "name": name,
                "instruments": len(pat["tracks"]),
                "steps": pat["step_count"],
                "bpm": pat["bpm"],
                "track_names": [t["name"] for t in pat["tracks"]],
            })
        return result

    def delete_pattern(self, name: str) -> bool:
        """
        Delete a stored pattern.

        Args:
            name: Pattern name to delete

        Returns:
            True if deleted, False if not found.
        """
        if name in self._patterns:
            del self._patterns[name]
            logger.info(f"Deleted pattern '{name}'")
            return True
        return False

    def play_stored_pattern(self, name: str, bpm: Optional[int] = None, repeat: int = 1) -> bool:
        """
        Play a previously stored pattern.

        Args:
            name: Pattern name
            bpm: Override BPM (uses stored BPM if None)
            repeat: Number of times to repeat

        Returns:
            bool: True if successful, False otherwise
        """
        pattern_data = self._patterns.get(name)
        if not pattern_data:
            logger.error(f"Pattern '{name}' not found")
            return False

        actual_bpm = bpm if bpm is not None else pattern_data["bpm"]
        return self.parse_drum_pattern(pattern_data["pattern_text"], actual_bpm, repeat)

    # ----------------------------------------------------------------
    # Song Arrangement
    # ----------------------------------------------------------------

    def create_song(self, name: str, arrangement: List[Dict[str, Any]], bpm: Optional[int] = None) -> Dict[str, Any]:
        """
        Create a song by arranging stored patterns in sequence.

        Args:
            name: Song name
            arrangement: List of dicts, each with:
                - "pattern": name of a stored pattern (required)
                - "repeat": number of times to play this pattern (default 1)
                - "bpm": override BPM for this section (optional)
            bpm: Default BPM for the whole song (overrides individual pattern BPMs)

        Returns:
            Dict with song info.
        """
        # Validate all referenced patterns exist
        for i, section in enumerate(arrangement):
            pat_name = section.get("pattern")
            if not pat_name or pat_name not in self._patterns:
                raise ValueError(
                    f"Section {i}: pattern '{pat_name}' not found. "
                    f"Available: {list(self._patterns.keys())}"
                )

        self._songs[name] = {
            "arrangement": arrangement,
            "bpm": bpm,
        }

        total_sections = len(arrangement)
        total_repeats = sum(s.get("repeat", 1) for s in arrangement)

        logger.info(f"Created song '{name}': {total_sections} sections, {total_repeats} total plays")
        return {
            "name": name,
            "sections": total_sections,
            "total_pattern_plays": total_repeats,
            "arrangement": [
                {
                    "pattern": s["pattern"],
                    "repeat": s.get("repeat", 1),
                    "bpm": s.get("bpm"),
                }
                for s in arrangement
            ],
        }

    def list_songs(self) -> List[Dict[str, Any]]:
        """
        List all stored songs.

        Returns:
            List of song summaries.
        """
        result = []
        for name, song in self._songs.items():
            result.append({
                "name": name,
                "sections": len(song["arrangement"]),
                "total_pattern_plays": sum(
                    s.get("repeat", 1) for s in song["arrangement"]
                ),
            })
        return result

    def get_song(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get a stored song by name.

        Args:
            name: Song name

        Returns:
            Song dict if found, None otherwise.
        """
        return self._songs.get(name)

    def delete_song(self, name: str) -> bool:
        """
        Delete a stored song.

        Args:
            name: Song name to delete

        Returns:
            True if deleted, False if not found.
        """
        if name in self._songs:
            del self._songs[name]
            logger.info(f"Deleted song '{name}'")
            return True
        return False

    def play_song(self, name: str, bpm_override: Optional[int] = None) -> bool:
        """
        Play a stored song (sequence of patterns).

        Args:
            name: Song name
            bpm_override: Override BPM for all sections

        Returns:
            bool: True if successful, False otherwise
        """
        song = self._songs.get(name)
        if not song:
            logger.error(f"Song '{name}' not found")
            return False

        if not self._ensure_connected():
            return False

        logger.info(f"Playing song '{name}' ({len(song['arrangement'])} sections)")

        for i, section in enumerate(song["arrangement"]):
            pat_name = section["pattern"]
            repeat = section.get("repeat", 1)

            # BPM priority: bpm_override > section bpm > song bpm > pattern bpm
            if bpm_override is not None:
                section_bpm = bpm_override
            elif section.get("bpm") is not None:
                section_bpm = section["bpm"]
            elif song.get("bpm") is not None:
                section_bpm = song["bpm"]
            else:
                pattern_data = self._patterns.get(pat_name, {})
                section_bpm = pattern_data.get("bpm", 120)

            logger.info(f"  Section {i+1}: '{pat_name}' x{repeat} at {section_bpm} BPM")

            success = self.play_stored_pattern(pat_name, section_bpm, repeat)
            if not success:
                logger.error(f"Failed to play section {i+1} ('{pat_name}')")
                return False

        logger.info(f"Finished playing song '{name}'")
        return True
