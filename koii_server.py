#!/usr/bin/env python3
"""
KOII MCP Server - Teenage Engineering EP-133 K.O. II MIDI Interface

This MCP server provides an interface for controlling the Teenage Engineering
EP-133 K.O. II sampler via MIDI.
"""

import logging
import io
import re
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator, Dict, List, Optional, Union

from mcp.server.fastmcp import FastMCP

from koii.midi_interface import MIDIInterface, SOUND_LIBRARY, SOUND_CATEGORIES, DEFAULT_PAD_CONFIG, PAD_GROUPS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("koii-mcp")

# Create the MIDIInterface instance
midi = MIDIInterface()

@contextmanager
def capture_logs(logger_instance: logging.Logger, level: int = logging.INFO) -> io.StringIO:
    """
    Capture log messages from a logger instance.
    
    Args:
        logger_instance: The logger instance to capture from
        level: The logging level to set during capture
    
    Returns:
        StringIO object containing the captured logs
    """
    # Setup log capture
    log_capture = io.StringIO()
    log_handler = logging.StreamHandler(log_capture)
    logger_instance.addHandler(log_handler)
    
    # Store original level
    original_level = logger_instance.level
    logger_instance.setLevel(level)
    
    try:
        yield log_capture
    finally:
        # Restore original settings
        logger_instance.setLevel(original_level)
        logger_instance.removeHandler(log_handler)

# Define the lifespan context manager
@asynccontextmanager
async def lifespan(app: FastMCP) -> AsyncIterator[Dict]:
    """
    Manage the lifecycle of the MCP server.
    
    This context manager initializes resources when the server starts
    and cleans them up when it stops.
    """
    # Initialize any resources here
    logger.info("Starting KOII MCP Server")
    
    try:
        # Yield control back to the server with our context
        yield {"midi": midi}
    finally:
        # Clean up resources when the server stops
        if midi.connected:
            midi.disconnect()
        logger.info("Stopping KOII MCP Server")

# Create the MCP server
server = FastMCP(
    "KOII MCP Server",
    description="Teenage Engineering EP-133 K.O. II MIDI Interface",
    lifespan=lifespan,
    dependencies=["mido"],
)

@server.tool()
def list_midi_ports() -> List[str]:
    """
    List all available MIDI output ports.
    
    Returns:
        A list of available MIDI port names.
    """
    ports = midi.list_ports()
    return ports

@server.tool()
def connect_to_device(port_name: Optional[str] = None, port_index: Optional[int] = None) -> str:
    """
    Connect to a MIDI device.
    
    Args:
        port_name: The name of the MIDI port to connect to.
            If not provided, will try to auto-detect the EP-133 K.O. II.
        port_index: The index of the MIDI port to connect to.
    
    Returns:
        A status message indicating success or failure.
    """
    # If already connected, disconnect first
    if midi.connected:
        midi.disconnect()
    
    # Connect to the device
    success = midi.connect(port_name, port_index)
    
    if success:
        return f"Successfully connected to MIDI device: {midi.port.name}"
    else:
        return "Failed to connect to MIDI device"

@server.tool()
def disconnect() -> str:
    """
    Disconnect from the current MIDI device.
    
    Returns:
        A status message indicating success or failure.
    """
    if not midi.connected:
        return "No MIDI device connected"
    
    port_name = midi.port.name
    success = midi.disconnect()
    
    if success:
        return f"Successfully disconnected from MIDI device: {port_name}"
    else:
        return "Failed to disconnect from MIDI device"

@server.tool()
def play_note(
    note: Union[int, str],
    velocity: int = 100,
    duration: float = 0.1,
    channel: Optional[int] = None
) -> str:
    """
    Play a single note on the EP-133 K.O. II.
    
    Args:
        note: MIDI note number (0-127) or note name (e.g., 'C3', 'F#4')
        velocity: Note velocity (0-127)
        duration: Note duration in seconds
        channel: MIDI channel (1-16). If not provided, uses the current channel.
    
    Returns:
        A status message indicating success or failure.
    """
    if not midi.connected:
        return "No MIDI device connected"
    
    # Set channel if provided
    original_channel = midi.channel
    if channel is not None:
        midi.set_channel(channel)
    
    try:
        # Play the note
        note_desc = note if isinstance(note, int) else note
        success = midi.play_note(note, velocity, duration)
        
        # Restore original channel if needed
        if channel is not None:
            midi.set_channel(original_channel + 1)  # +1 to convert from 0-indexed
        
        if success:
            return f"Successfully played note {note_desc} with velocity {velocity} for {duration} seconds"
        else:
            return f"Failed to play note {note_desc}"
    except ValueError as e:
        # Restore original channel if needed
        if channel is not None:
            midi.set_channel(original_channel + 1)  # +1 to convert from 0-indexed
        return f"Error: {str(e)}"

@server.tool()
def play_pattern(
    notes: List[Dict[str, Union[int, str, float]]],
    channel: Optional[int] = None
) -> str:
    """
    Play a pattern of notes on the EP-133 K.O. II.
    
    Args:
        notes: List of note dictionaries, each containing:
            - note: MIDI note number (0-127) or note name (e.g., 'C3')
            - velocity: Note velocity (0-127)
            - duration: Note duration in seconds
        channel: MIDI channel (1-16). If not provided, uses the current channel.
    
    Returns:
        A status message indicating success or failure.
    """
    if not midi.connected:
        return "No MIDI device connected"
    
    # Set channel if provided
    original_channel = midi.channel
    if channel is not None:
        midi.set_channel(channel)
    
    try:
        # Convert dictionaries to tuples
        note_tuples = []
        for note_dict in notes:
            note = note_dict.get("note", 60)
            velocity = note_dict.get("velocity", 100)
            duration = note_dict.get("duration", 0.1)
            note_tuples.append((note, velocity, duration))
        
        # Play the pattern
        success = midi.play_pattern(note_tuples)
        
        # Restore original channel if needed
        if channel is not None:
            midi.set_channel(original_channel + 1)  # +1 to convert from 0-indexed
        
        if success:
            return f"Successfully played pattern with {len(notes)} notes"
        else:
            return "Failed to play pattern"
    except Exception as e:
        # Restore original channel if needed
        if channel is not None:
            midi.set_channel(original_channel + 1)  # +1 to convert from 0-indexed
        return f"Error: {str(e)}"

@server.tool()
def play_drum_pattern(pattern: str, bpm: int = 120) -> str:
    """
    Play a text-based drum pattern on the EP-133 K.O. II.
    
    Format:
    x...x...x...x...  # kick      (bottom left pad, A.)
    ....x.......x...  # snare     (pad A2)
    x.x.x.x.x.x.x.x.  # hi-hat    (pad A5)
    
    The pattern supports four reference types:
    1. Pad references: A., A0, A1-A9, B., B1, etc.
    2. MIDI note numbers: 36, 40, 43, etc.
    3. Instrument names: kick, snare, hi-hat, etc.
    4. Sound names from library: "MICRO KICK", "NT SNARE", etc.
    
    Default drum mappings:
    - kick → A. (MIDI note 36)
    - snare → A2 (MIDI note 40)
    - clap → A3 (MIDI note 41)
    - hi-hat → A5 (MIDI note 43)
    - open hi-hat → A8 (MIDI note 46)
    
    Args:
        pattern: Text-based drum pattern
        bpm: Tempo in beats per minute
    
    Returns:
        A status message indicating success or failure.
    """
    if not midi.connected:
        return "No MIDI device connected"
    
    # Capture logs from the MIDIInterface to extract information about
    # recognized and unrecognized instruments
    from koii.midi_interface import logger as midi_logger
    
    with capture_logs(midi_logger) as log_capture:
        try:
            success = midi.parse_drum_pattern(pattern, bpm)
            
            # Extract information from logs
            log_output = log_capture.getvalue()
            
            # Find recognized instruments
            recognized_instruments = []
            unrecognized_instruments = []
            
            for line in log_output.split('\n'):
                # Look for mapped instruments
                mapped_match = re.search(r"Mapped '([^']+)' to MIDI note (\d+)", line)
                if mapped_match:
                    reference = mapped_match.group(1)
                    note = mapped_match.group(2)
                    recognized_instruments.append(f"{reference} → MIDI note {note}")
                
                # Look for unrecognized instruments
                unrecognized_match = re.search(r"Ignored unrecognized instruments: (.+)", line)
                if unrecognized_match:
                    unrecognized = unrecognized_match.group(1).split(', ')
                    unrecognized_instruments.extend(unrecognized)
            
            # Build response message
            if success:
                response = f"Successfully played drum pattern at {bpm} BPM\n"
                
                if recognized_instruments:
                    response += "\nRecognized instruments:\n"
                    for instr in recognized_instruments:
                        response += f"- {instr}\n"
                
                if unrecognized_instruments:
                    response += "\nUnrecognized instruments (ignored):\n"
                    for instr in unrecognized_instruments:
                        response += f"- {instr}\n"
                
                return response.strip()
            else:
                return "Failed to play drum pattern"
        
        except Exception as e:
            return f"Error: {str(e)}"

@server.tool()
def list_sound_categories() -> List[str]:
    """
    List all available sound categories in the EP-133 K.O. II.
    
    Returns:
        A list of sound categories.
    """
    return SOUND_CATEGORIES

@server.tool()
def list_sounds_in_category(category: str) -> Dict[int, str]:
    """
    List all sounds in a specific category.
    
    Args:
        category: The sound category name (e.g., "Kicks", "Snares", etc.)
    
    Returns:
        A dictionary mapping sound numbers to sound names.
    """
    if category not in SOUND_LIBRARY:
        categories = list(SOUND_LIBRARY.keys())
        return {"error": f"Invalid category: {category}. Available categories: {', '.join(categories)}"}
    
    return SOUND_LIBRARY[category]

@server.tool()
def get_default_pad_configuration() -> Dict[str, Dict]:
    """
    Get the default pad configuration for the EP-133 K.O. II.
    
    This shows which sounds are mapped to which pads by default.
    Each channel (A, B, C) has a matrix of pads, with physical pad labels,
    MIDI note numbers, and sound IDs/names.
    
    Returns:
        A dictionary containing the detailed pad configuration.
    """
    # Create a more detailed and structured configuration
    detailed_config = {}
    
    # Define the physical layout of pads
    pad_layout = [
        ["7", "8", "9"],   # Top row
        ["4", "5", "6"],   # Middle row
        ["1", "2", "3"],   # Bottom row
        [".", "0", "FX"]   # Special bottom row
    ]
    
    for channel, config in DEFAULT_PAD_CONFIG.items():
        detailed_config[channel] = {"rows": []}
        
        # Get the base MIDI note for this channel
        base_midi_note = min(PAD_GROUPS[channel])
        
        # Process each row from bottom to top, as they appear in DEFAULT_PAD_CONFIG
        for row_idx, sound_row in enumerate(config["pads"]):
            # Convert to physical layout row (reversed order from DEFAULT_PAD_CONFIG)
            physical_row_idx = 3 - row_idx
            physical_row = pad_layout[physical_row_idx]
            
            row_data = []
            
            for col_idx, sound_number in enumerate(sound_row):
                # Skip FX pad as it's not directly addressable via MIDI
                if physical_row_idx == 3 and col_idx == 2:  # FX pad
                    pad_label = f"{channel}FX"
                    midi_note = None  # Not directly addressable
                else:
                    pad_label = f"{channel}{physical_row[col_idx]}"
                    
                    # Calculate MIDI note number based on position
                    if physical_row_idx == 3:  # Special bottom row
                        if col_idx == 0:  # '.' pad
                            midi_note = base_midi_note + 0  # A. = 36, B. = 48, etc.
                        elif col_idx == 1:  # '0' pad
                            midi_note = base_midi_note + 1  # A0 = 37, B0 = 49, etc.
                        elif col_idx == 2:  # 'FX' pad
                            midi_note = base_midi_note + 2  # AFX = 38, BFX = 50, etc.
                    else:
                        # For regular numbered pads (1-9)
                        # The MIDI layout follows bottom-to-top, left-to-right
                        # A1 = 39, A2 = 40, A3 = 41, A4 = 42, etc.
                        pad_num = int(physical_row[col_idx])
                        row = (pad_num - 1) // 3  # 0 = bottom, 1 = middle, 2 = top
                        col = (pad_num - 1) % 3   # 0 = left, 1 = middle, 2 = right
                        midi_note = base_midi_note + 3 + (row * 3) + col
                
                # Find the sound name
                sound_name = None
                sound_category = None
                for category, sounds in SOUND_LIBRARY.items():
                    if sound_number in sounds:
                        sound_name = sounds[sound_number]
                        sound_category = category
                        break
                
                # Add this pad's data
                row_data.append({
                    "pad": pad_label,
                    "midi_note": midi_note,
                    "sound_id": sound_number,
                    "sound_name": sound_name if sound_name else f"Unknown ({sound_number})",
                    "category": sound_category
                })
            
            # Add this row to the channel's configuration
            detailed_config[channel]["rows"].append(row_data)
    
    return detailed_config

@server.tool()
def list_available_scales() -> Dict[str, str]:
    """
    List all available musical scales with their interval patterns.
    
    Returns:
        A dictionary mapping scale names to their descriptions.
    """
    from koii.midi_interface import SCALE_PATTERNS
    
    # Create a dictionary with scale descriptions
    scale_descriptions = {
        "major": "Major scale (W-W-H-W-W-W-H)",
        "minor": "Natural minor scale (W-H-W-W-H-W-W)",
        "dorian": "Dorian mode (W-H-W-W-W-H-W)",
        "phrygian": "Phrygian mode (H-W-W-W-H-W-W)",
        "lydian": "Lydian mode (W-W-W-H-W-W-H)",
        "mixolydian": "Mixolydian mode (W-W-H-W-W-H-W)",
        "locrian": "Locrian mode (H-W-W-H-W-W-W)",
        "major_pentatonic": "Major pentatonic scale (major without 4th and 7th)",
        "minor_pentatonic": "Minor pentatonic scale (minor without 2nd and 6th)",
        "blues": "Blues scale (minor pentatonic + flat 5th)",
        "chromatic": "Chromatic scale (all 12 semitones)"
    }
    
    return scale_descriptions

@server.tool()
def get_scale_mapping(
    channel: str,
    scale_name: str,
    root_note: str,
    octave: int = 3
) -> Dict[str, Dict]:
    """
    Get a mapping of pads to notes in a musical scale.
    
    This tool is useful in Keys Mode, when you've configured your EP-133 K.O. II
    to use a specific scale. It shows which pads correspond to which notes in the scale.
    
    Args:
        channel: Pad channel to map ('A', 'B', 'C', or 'D')
        scale_name: Name of the scale (e.g., 'major', 'minor', 'dorian')
        root_note: Root note of the scale (e.g., 'C', 'F#', 'Eb')
        octave: Starting octave for the scale (0-10)
    
    Returns:
        A dictionary mapping pad labels to scale note information.
    """
    if not midi.connected:
        return {"error": "No MIDI device connected"}
    
    try:
        # Get the mapping
        pad_to_note = midi.map_pads_to_scale(channel, scale_name, root_note, octave)
        
        # Format the result with note names
        result = {
            "scale_info": {
                "name": scale_name,
                "root": root_note,
                "octave": octave
            },
            "pad_mapping": {}
        }
        
        # Helper to get note name from MIDI note number
        def get_note_name(midi_note):
            octave = (midi_note // 12) - 1
            note_idx = midi_note % 12
            note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
            return f"{note_names[note_idx]}{octave}"
        
        # Add detailed note information for each pad
        for pad, note in pad_to_note.items():
            result["pad_mapping"][pad] = {
                "midi_note": note,
                "note_name": get_note_name(note)
            }
        
        return result
        
    except ValueError as e:
        return {"error": str(e)}

@server.tool()
def play_scale_sequence(
    channel: str,
    scale_name: str,
    root_note: str,
    sequence: List[int],
    velocity: int = 100,
    duration: float = 0.2,
    interval: float = 0.1,
    octave: int = 3
) -> str:
    """
    Play a sequence of notes from a musical scale.
    
    The sequence is specified as a list of scale degrees (1-based):
    - 1 = root note
    - 2 = second note in the scale
    - 3 = third note in the scale
    - etc.
    - Negative numbers play notes from the scale in lower octaves
    - 0 = rest (no note)
    
    Args:
        channel: Pad channel ('A', 'B', 'C', or 'D')
        scale_name: Name of the scale (e.g., 'major', 'minor', 'dorian')
        root_note: Root note of the scale (e.g., 'C', 'F#', 'Eb')
        sequence: List of scale degrees (1-based, 0 for rest)
        velocity: Note velocity (0-127)
        duration: Note duration in seconds
        interval: Time between notes in seconds
        octave: Starting octave for the scale (0-10)
    
    Returns:
        A status message indicating success or failure.
    """
    if not midi.connected:
        return "No MIDI device connected"
    
    try:
        success = midi.play_scale_sequence(
            channel, scale_name, root_note, sequence, 
            velocity, duration, interval, octave
        )
        
        if success:
            # Format the sequence for display
            sequence_display = []
            for note in sequence:
                if note == 0:
                    sequence_display.append("rest")
                else:
                    sequence_display.append(str(note))
            
            sequence_str = ", ".join(sequence_display)
            
            return (f"Successfully played scale sequence using {scale_name} scale "
                   f"in {root_note} (channel {channel}, octave {octave}):\n"
                   f"Sequence: {sequence_str}")
        else:
            return "Failed to play scale sequence"
    
    except ValueError as e:
        return f"Error: {str(e)}"

@server.prompt()
def midi_info() -> str:
    """Provide information about the EP-133 K.O. II MIDI implementation."""
    return """
    # EP-133 K.O. II MIDI Controller

    This is the KOII MCP server for controlling the Teenage Engineering EP-133 K.O. II sampler via MIDI.
    
    ## Pad Mapping
    
    Pads are mapped to MIDI note numbers by default:
    
    | Group | MIDI Notes    | Pads          |
    |-------|---------------|---------------|
    | A     | 36–47 (C2–B2) | Pads A. to A9 |
    | B     | 48–59 (C3–B3) | Pads B. to B9 |
    | C     | 60–71 (C4–B4) | Pads C. to C9 |
    | D     | 72–83 (C5–B5) | Pads D. to D9 |
    
    ## Available Functions
    
    ### Basic MIDI Operations
    - `list_midi_ports()`: List all available MIDI ports
    - `connect_to_device(port_name, port_index)`: Connect to a MIDI device
    - `disconnect()`: Disconnect from the current MIDI device
    - `play_note(note, velocity, duration, channel)`: Play a single note
    - `play_pattern(notes, channel)`: Play a pattern of notes
    
    ### Drum Patterns
    - `play_drum_pattern(pattern, bpm)`: Play a text-based drum pattern
    
    ### Sound Library
    - `list_sound_categories()`: List all available sound categories
    - `list_sounds_in_category(category)`: List all sounds in a specific category
    - `get_default_pad_configuration()`: Get the default sounds mapped to each pad
    
    ### Scale Mode
    - `list_available_scales()`: List all available musical scales with descriptions
    - `get_scale_mapping(channel, scale_name, root_note, octave)`: Map pads to notes in a scale
    - `play_scale_sequence(channel, scale_name, root_note, sequence)`: Play a melodic sequence
    """

@server.prompt()
def pad_configuration_help() -> str:
    """Provide help on understanding the default pad configuration."""
    return """
    # EP-133 K.O. II Pad Configuration
    
    The EP-133 K.O. II has pads organized in channels (A, B, C, D), with each channel containing
    a matrix of pads in a 4×3 grid. Understanding the relationship between pad labels, MIDI notes,
    and sound IDs is crucial for creating effective patterns.
    
    ## Physical Pad Layout
    
    ```
    +-----+-----+-----+  
    | A7  | A8  | A9  |  ← Top row
    +-----+-----+-----+  
    | A4  | A5  | A6  |  ← Middle row
    +-----+-----+-----+  
    | A1  | A2  | A3  |  ← Bottom row
    +-----+-----+-----+  
    | A.  | A0  | FX  |  ← Special bottom row
    +-----+-----+-----+  
    ```
    
    The same layout applies to channels B, C, and D.
    
    ## Three Important Number Systems
    
    1. **Pad Labels**: The physical labels on the pads (A., A0, A1-A9)
    2. **MIDI Note Numbers**: The actual MIDI notes sent to trigger sounds (36-83)
    3. **Sound IDs**: The internal sound numbers used in the sound library (1, 100, 500, etc.)
    
    ### Pad Labels to MIDI Note Mapping
    
    - **Channel A**: 
      - A. → 36 (C2)
      - A0 → 37 (C#2)
      - FX → 38 (D2)
      - A1 → 39 (D#2)
      - A2 → 40 (E2)
      - A3 → 41 (F2)
      - A4 → 42 (F#2)
      - A5 → 43 (G2)
      - A6 → 44 (G#2)
      - A7 → 45 (A2)
      - A8 → 46 (A#2)
      - A9 → 47 (B2)
    
    - **Channel B**: 
      - B. → 48 (C3)
      - B0 → 49 (C#3)
      - ...etc. (following the same pattern)
    
    - **Channel C**: 
      - C. → 60 (C4)
      - C0 → 61 (C#4)
      - ...etc. (following the same pattern)
    
    - **Channel D**: 
      - D. → 72 (C5)
      - D0 → 73 (C#5)
      - ...etc. (following the same pattern)
    
    ## Understanding the Default Configuration
    
    To see a detailed mapping of pads to sounds, use:
    
    ```
    get_default_pad_configuration()
    ```
    
    This returns comprehensive information about each pad:
    - Pad label (A1, B2, etc.)
    - MIDI note number
    - Sound ID
    - Sound name
    - Category
    
    ## Default Sound Organization by Channel
    
    - **Channel A**: Drums and percussion sounds
      - Top row (A7-A9): Percussion (tambourine, ride cymbals)
      - Middle rows: Snares and cymbals
      - Bottom row (A., A0-A3): Kicks and claps
    
    - **Channel B**: Bass sounds
      - Various bass types from lower to higher frequencies
    
    - **Channel C**: Melodic and synth sounds
      - Chords, pianos, strings, and other melodic instruments
    
    ## Creating Patterns with Pad References
    
    When creating drum patterns, you can reference pads directly by their label:
    
    ```
    x...x...x...x...  # A.  (Bottom left pad, MIDI note 36)
    ....x.......x...  # A2  (Bottom row, MIDI note 38)
    x.x.x.x.x.x.x.x.  # A5  (Middle pad, MIDI note 41)
    ```
    
    This allows your patterns to work correctly even if the sound mapping changes.
    
    ## Finding Available Sounds
    
    Browse all available sounds using:
    - `list_sound_categories()`: View sound categories (Kicks, Snares, etc.)
    - `list_sounds_in_category(category)`: Browse sounds within a specific category
    """

@server.prompt()
def drum_pattern_help() -> str:
    """Provide help on creating drum patterns."""
    return """
    # Creating Drum Patterns
    
    You can create and play drum patterns using the `play_drum_pattern()` function.
    
    ## Pattern Format
    
    The pattern is specified as a multi-line string, where:
    - Each line represents a different instrument or pad
    - 'x' or 'X' indicates a hit (high velocity, 100)
    - 'o' or 'O' indicates a softer hit (lower velocity, 60)
    - Digits '1'-'9' for velocity values from gentle (1) to hard (9)
    - 'v' followed by digits (e.g., 'v64', 'v127') for exact velocity values 
    - '.' indicates no hit
    - Each position represents a 16th note
    - Comments after '#' specify what sound to trigger
    
    ## Flexible Reference System
    
    The drum pattern parser supports **four different ways** to reference sounds:
    
    1. **Pad Labels**: Direct references to physical pads (A0, B3, C7)
    2. **MIDI Notes**: Direct MIDI note numbers (36, 42, 51)
    3. **Instrument Names**: Common drum instruments (kick, snare, hi-hat)
    4. **Sound Names**: Actual sound names from the library ("MICRO KICK", "NT SNARE")
    
    You can even mix these reference types within the same pattern!
    
    ## Example Patterns
    
    Using traditional instrument names:
    ```
    x...x...x...x...  # kick
    ....x.......x...  # snare
    x.x.x.x.x.x.x.x.  # hi-hat
    ```
    
    Using pad references:
    ```
    x...x...x...x...  # A.
    ....x.......x...  # A2
    x.x.x.x.x.x.x.x.  # A5
    ```
    
    Using MIDI note numbers:
    ```
    x...x...x...x...  # 36
    ....x.......x...  # 38
    x.x.x.x.x.x.x.x.  # 42
    ```
    
    Using sound library names:
    ```
    x...x...x...x...  # "MICRO KICK"
    ....x.......x...  # "NT SNARE"
    x.x.x.x.x.x.x.x.  # "NT HH CLOSED"
    ```
    
    Using mixed references:
    ```
    x...x...x...x...  # A.       (pad reference)
    ....x.......x...  # 38       (MIDI note)
    x.x.x.x.x.x.x.x.  # hi-hat   (instrument name)
    ......x.........  # "NT RIDE" (sound name)
    ```
    
    ## Dynamic Velocity Examples
    
    Using numeric velocity values (1-9):
    ```
    9...5...3...1...  # kick     (velocity decreasing)
    ....6.......8...  # snare    (medium then hard)
    5.3.5.7.5.9.5.1.  # hi-hat   (changing accents)
    ```
    
    Using exact velocity values:
    ```
    v120....v80....v40....v10....  # kick    (precise velocities)
    ....v64.......v96...          # snare   (medium then harder)
    v30.v30.v100...v30.v30.v127.  # hi-hat  (ghost notes with accents)
    ```
    
    Combining different velocity notations:
    ```
    x...5...o...1...       # kick     (mix of notation styles)
    ....v100...v64...v32.  # snare    (decaying echo effect)
    x.o.3.5.7.9.v127.v10.  # hi-hat   (complex pattern)
    ```
    
    ## Sound Name References
    
    When using sound names:
    - Enclose them in quotes if they contain spaces: `# "MICRO KICK"`
    - They are automatically case-insensitive
    - Partial matches work as well, finding the closest match
    
    ## MIDI Note References
    
    You can directly specify MIDI notes:
    - Use the numerical value: `# 36`
    - Valid range is 0-127
    
    ## Pad References
    
    You can specify which pad to trigger using its label:
    
    - **Channel A**: A. (bottom left), A0, A1-A9
    - **Channel B**: B. (bottom left), B0, B1-B9
    - **Channel C**: C. (bottom left), C0, C1-C9
    - **Channel D**: D. (bottom left), D0, D1-D9
    
    This works regardless of what sounds are mapped to those pads.
    
    ## Instrument Name References
    
    Drum instrument names are mapped to specific pads in the default configuration:
    
    | Instrument      | Pad | MIDI Note | Default Sound     |
    |-----------------|-----|-----------|-------------------|
    | kick            | A.  | 36 (C2)   | MICRO KICK        |
    | snare           | A2  | 40 (E2)   | NT SNARE ALT      |
    | clap            | A3  | 41 (F2)   | NT CLAP           |
    | low tom         | A4  | 42 (F#2)  | NT TAMBO          |
    | closed hi-hat   | A5  | 43 (G2)   | NT HH CLOSED      |
    | mid tom         | A6  | 44 (G#2)  | NT RIDE           |
    | high tom/perc   | A7  | 45 (A2)   | NT PERC           |
    | open hi-hat/ride| A8  | 46 (A#2)  | NT HH OPEN        |
    | crash/cymbal    | A9  | 47 (B2)   | NT RIDE C         |
    
    ## Finding Available Sounds
    
    To see what sounds are available and how they're mapped to pads:
    - `list_sound_categories()`: View available categories
    - `list_sounds_in_category(category)`: View sounds in a category
    - `get_default_pad_configuration()`: See the full pad mapping
    """

# If this script is executed directly, run the server
if __name__ == "__main__":
    server.run()

@server.prompt()
def scale_mode_help() -> str:
    """Provide help on using scale mode."""
    return """
    # Using Scale Mode with the EP-133 K.O. II

    The EP-133 K.O. II can be configured to use musical scales when in Keys Mode. This allows you to play melodies and chords using the devices pads.
    
    ## Setting Up Scale Mode on the Device
    
    1. **Enable Keys Mode** on your EP-133 K.O. II using the devices interface
    2. **Configure your desired scale** on the device
    3. **Tell Claude** which channel, scale, and root note youve configured
    
    ## Available Tools for Scale Mode
    
    ### 1. List Available Scales
    
    ```python
    list_available_scales()
    ```
    
    This function returns a dictionary of all available scales with descriptions of their intervals. Supported scales include:
    - major
    - minor
    - dorian, phrygian, lydian, mixolydian, locrian (modal scales)
    - major_pentatonic, minor_pentatonic
    - blues
    - chromatic
    
    ### 2. Get Scale Mapping
    
    ```python
    get_scale_mapping(channel="A", scale_name="major", root_note="C", octave=3)
    ```
    
    This function shows you which pads correspond to which notes in your chosen scale. Arguments:
    - `channel`: Which pad group to use (A, B, C, or D)
    - `scale_name`: Type of scale (major, minor, etc.)
    - `root_note`: Tonic/root note (C, C#, Eb, etc.)
    - `octave`: Starting octave (0-10, default 3)
    
    ### 3. Play Scale Sequence
    
    ```python
    play_scale_sequence(
        channel="A", 
        scale_name="major", 
        root_note="C", 
        sequence=[1, 2, 3, 4, 5], 
        velocity=100,
        duration=0.2,
        interval=0.1,
        octave=3
    )
    ```
    
    This function plays a sequence of notes from your chosen scale. Arguments:
    - `channel`: Which pad group to use (A, B, C, or D)
    - `scale_name`: Type of scale (major, minor, etc.)
    - `root_note`: Tonic/root note (C, C#, Eb, etc.)
    - `sequence`: List of scale degrees to play (1-based):
      - 1 = Root note
      - 2 = Second note in scale
      - 3 = Third note in scale
      - 0 = Rest (no note)
      - Negative numbers = Notes in lower octaves
    - `velocity`: Note velocity (0-127)
    - `duration`: Note duration in seconds
    - `interval`: Time between notes in seconds
    - `octave`: Starting octave (0-10, default 3)
    
    ## Example Usage
    
    ### Finding Available Scales
    
    ```
    list_available_scales()
    ```
    
    ### Getting Note Mapping for a C Minor Scale on Channel A
    
    ```
    get_scale_mapping(channel="A", scale_name="minor", root_note="C")
    ```
    
    ### Playing a Simple Melody in G Major
    
    ```
    play_scale_sequence(
        channel="A",
        scale_name="major",
        root_note="G",
        sequence=[1, 2, 3, 4, 5, 4, 3, 2, 1],
        duration=0.2,
        interval=0.1
    )
    ```
    
    ### Playing a Minor Pentatonic Blues Riff
    
    ```
    play_scale_sequence(
        channel="A",
        scale_name="blues",
        root_note="E",
        sequence=[1, 3, 4, 3, 1, 0, 5, 4, 3, 5, 1],
        velocity=90,
        duration=0.15,
        interval=0.05
    )
    ```
    
    ## Tips for Scale Mode
    
    - The root note is always mapped to the lowest pad in the layout (e.g., A. for channel A)
    - The scale notes ascend in order from the bottom left to the top right of the pad layout
    - Pad FX is not used in scale mappings
    - For more complex melodic sequences, use multiple `play_scale_sequence` calls with different durations
    - If the device display shows different notes than expected, double check your scale configuration on the device
    """

