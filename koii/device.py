"""
EP-133 K.O. II device facts: pad layout, MIDI note map, kit aliases and the
factory sound list.

Sources and confidence are documented in DEVICE.md. In short:

- Note map (A 36-47, B 48-59, C 60-71, D 72-83), receive on all channels / send
  on channel 1 by default, keys mode 0-127, per-pad MIDI channel (Sound Edit,
  knob X) and root note (knob Y): official TE guide.
- The pad order within a group (., 0, ENTER, 1-9 ascending): official note
  table; pads double as a calculator-style numpad.
- PROJECT_1_KIT and FACTORY_SOUNDS: community-transcribed from the device
  display, not published by TE. Treat as a starting point; users can and do
  change sounds, so kit aliases are user-overridable.
"""

from typing import Dict, List, Optional, Tuple

GROUPS = ("A", "B", "C", "D")
GROUP_BASE_NOTE = {"A": 36, "B": 48, "C": 60, "D": 72}

# Pad keys in MIDI note order (offset 0..11 from the group's base note).
PAD_KEYS = (".", "0", "Enter", "1", "2", "3", "4", "5", "6", "7", "8", "9")

# Physical layout, top row first, as seen on the device.
PAD_GRID = (
    ("7", "8", "9"),
    ("4", "5", "6"),
    ("1", "2", "3"),
    (".", "0", "Enter"),
)

_ENTER_SPELLINGS = {"ENTER", "E", "FX", "↵"}

# Default MIDI behaviour (official): receives on all channels, sends on channel 1.
DEFAULT_CHANNEL = 1


def pad_label(group: str, key: str) -> str:
    """Canonical pad label, e.g. ('A', '.') -> 'A.', ('B', 'Enter') -> 'BEnter'."""
    return f"{group}{key}"


def parse_pad(label: str) -> Optional[Tuple[str, str]]:
    """
    Parse a pad label into (group, key), or return None if it isn't one.

    Accepts 'A.', 'a0', 'A1'..'A9', and 'AEnter' / 'AE' / 'AFX' / 'A↵'.
    """
    if len(label) < 2:
        return None
    group = label[0].upper()
    if group not in GROUPS:
        return None
    rest = label[1:]
    if rest in (".", "0") or (len(rest) == 1 and rest in "123456789"):
        return group, rest
    if rest.upper() in _ENTER_SPELLINGS:
        return group, "Enter"
    return None


def pad_note(group: str, key: str) -> int:
    """MIDI note for a pad, e.g. ('A', '.') -> 36, ('A', 'Enter') -> 38."""
    return GROUP_BASE_NOTE[group] + PAD_KEYS.index(key)


def note_pad(note: int) -> Optional[str]:
    """Pad label for a MIDI note in 36-83, else None."""
    for group, base in GROUP_BASE_NOTE.items():
        if base <= note < base + 12:
            return pad_label(group, PAD_KEYS[note - base])
    return None


# ---------------------------------------------------------------------------
# Factory sounds (community-transcribed; see module docstring)
# ---------------------------------------------------------------------------

FACTORY_SOUNDS: Dict[str, Dict[int, str]] = {
    "Kicks": {
        1: "MICRO KICK", 2: "NT KICK", 3: "NT KICK B", 4: "NT KICK C", 5: "NT KICK D",
        6: "LOCK KIK", 7: "KICK GRIT", 8: "KICK VERB", 9: "KICK MID", 10: "KICK BUMP",
        11: "KICK 9X9 DIRT", 12: "KICK 9X9 DIRT B", 13: "KICK 9X9 DIRT C", 14: "KICK 9X9 DIRT D",
        15: "KICK 9X9 DIRT E", 16: "KICK HARD", 17: "KICK AIR", 18: "KICK THUD", 19: "CARDIO KICK I",
        20: "AFTERPARTY KICK", 21: "NT ALT KICK", 22: "NT ALT KICK B", 23: "NT ALT KICK C",
        24: "KICK DIRT", 25: "KICK SUB", 26: "KICK SP", 27: "KICK FLUX", 28: "KICK FLUX B",
        29: "KICK SUB B", 30: "KICK OPEN", 31: "BOOMER KICK",
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
        142: "RIM SNAP", 143: "KNOW RIMSHOT 1", 144: "SIDEQUEST SNARE", 145: "AKKOUNTANT RIM 2",
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
        253: "80 GREAT CRASH",
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
        342: "LOWW CLAVE I", 343: "NT PERC", 344: "NT PERC B", 345: "NT PERC C",
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
        458: "PUFF", 459: "RUDE TWANG",
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
        557: "VOX S612 GATED", 558: "O3D", 559: "SEARCH CHORD",
    },
}


def sound_name(sound_id: int) -> Optional[str]:
    for sounds in FACTORY_SOUNDS.values():
        if sound_id in sounds:
            return sounds[sound_id]
    return None


# Factory Project 1 pad -> sound ID (community-transcribed). Group D ships empty.
PROJECT_1_KIT: Dict[str, int] = {
    "A.": 1, "A0": 21, "AEnter": 300,
    "A1": 100, "A2": 114, "A3": 130,
    "A4": 317, "A5": 200, "A6": 218,
    "A7": 343, "A8": 235, "A9": 247,
    "B.": 400, "B0": 405, "BEnter": 410,
    "B1": 415, "B2": 420, "B3": 425,
    "B4": 430, "B5": 402, "B6": 404,
    "B7": 407, "B8": 408, "B9": 401,
    "C.": 500, "C0": 505, "CEnter": 510,
    "C1": 515, "C2": 520, "C3": 525,
    "C4": 530, "C5": 343, "C6": 540,
    "C7": 545, "C8": 550, "C9": 555,
}

# Built-in kit aliases, derived from PROJECT_1_KIT. Users override these with
# set_alias when their project differs.
DEFAULT_ALIASES: Dict[str, str] = {
    "kick": "A.", "bd": "A.",
    "kick2": "A0",
    "clap": "AEnter", "cp": "AEnter",
    "snare": "A1", "sd": "A1",
    "snare2": "A2",
    "rim": "A3", "rimshot": "A3",
    "tambo": "A4", "tambourine": "A4",
    "hat": "A5", "hh": "A5", "hihat": "A5",
    "openhat": "A6", "oh": "A6",
    "perc": "A7",
    "ride": "A8",
    "ride2": "A9",
    "bass": "B.",
    "keys": "C.",
}


def kit_rows(aliases: Dict[str, str]) -> List[Dict[str, object]]:
    """Every pad with its MIDI note, Project 1 sound and the aliases pointing at it."""
    by_pad: Dict[str, List[str]] = {}
    for name, target in aliases.items():
        by_pad.setdefault(target, []).append(name)
    rows = []
    for group in GROUPS:
        for key in PAD_KEYS:
            label = pad_label(group, key)
            sound_id = PROJECT_1_KIT.get(label)
            rows.append({
                "pad": label,
                "note": pad_note(group, key),
                "project_1_sound": sound_name(sound_id) if sound_id else None,
                "aliases": sorted(by_pad.get(label, [])),
            })
    return rows
