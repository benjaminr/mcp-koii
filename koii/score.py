"""
Sheet music for a pattern: rhythm spelling (notes, rests, ties, dots, triplets)
worked out once here, then drawn by the browser and exported as MusicXML.

Conventions:
- Drums are one percussion staff. A drum hit lasts until the next hit on that
  staff or the end of its beat, whichever comes first (drum notes don't sustain,
  so they're never tied).
- Each pitched track gets its own staff. A note lasts for its hit plus holds
  ('-'), is cut short by the next hit, and is tied across beat lines.
- The gaps are rests. An empty bar is a whole rest; an empty half bar is a half rest.
- Triplet grids (1/8t, 1/16t) write each beat that's divided as a triplet.
"""

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

from koii.notation import HOLD, Pattern, Track, note_name, GRIDS

BEATS_PER_BAR = 4
TRIPLET = (3, 2)  # 3 in the time of 2

# Written note values, longest first, in beats.
VALUES: List[Tuple[str, Fraction]] = [
    ("whole", Fraction(4)), ("half", Fraction(2)), ("quarter", Fraction(1)), ("eighth", Fraction(1, 2)),
    ("16th", Fraction(1, 4)), ("32nd", Fraction(1, 8)), ("64th", Fraction(1, 16)),
]

# Percussion staff positions: 0 is the bottom line (E4), each step half a space up.
DRUM_POSITIONS: Dict[str, Tuple[int, str]] = {
    "kick": (1, "normal"), "tom": (6, "normal"), "perc": (3, "normal"), "snare": (5, "normal"),
    "rim": (5, "x"), "clap": (7, "normal"), "hat": (9, "x"), "openhat": (9, "x"), "ride": (8, "x"),
    "crash": (10, "x"), "bass": (2, "normal"), "keys": (4, "normal"), "other": (4, "normal"),
}
_DIATONIC = "CDEFGAB"
_ROLE_WORDS = [
    (("kick", "bassdrum"), ("bd",), "kick"),
    (("snare",), ("sd",), "snare"),
    (("rim",), (), "rim"),
    (("clap",), ("cp",), "clap"),
    (("openhat", "open"), ("oh",), "openhat"),
    (("hat", "hihat", "closedhat"), ("hh", "ch"), "hat"),
    (("ride",), (), "ride"),
    (("crash", "cymbal", "splash", "china"), (), "crash"),
    (("tom",), (), "tom"),
    (("tambo", "tambourine", "perc", "bongo", "conga", "handdrum", "shaker", "cowbell", "clave", "cabasa",
      "guiro", "agogo"), (), "perc"),
    (("bass", "sub"), (), "bass"),
    (("keys", "piano", "chord", "lead", "synth", "organ", "pad", "strings", "melody"), (), "keys"),
]
# Pad roles in the factory layout, which the built-in kit names follow.
_PAD_ROLES = {"A.": "kick", "A0": "kick", "AEnter": "clap", "A1": "snare", "A2": "snare", "A3": "rim",
              "A4": "perc", "A5": "hat", "A6": "openhat", "A7": "perc", "A8": "ride", "A9": "crash"}


def role_for(track: Track) -> str:
    """What instrument a track is, from its name, else its pad in the factory layout."""
    name = track.name.lower()
    for prefixes, exact, role in _ROLE_WORDS:
        if name.startswith(prefixes) or name.rstrip("0123456789") in exact:
            return role
    label = track.target.label
    if label in _PAD_ROLES:
        return _PAD_ROLES[label]
    return {"B": "bass", "C": "keys"}.get(label[:1], "other")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Head:
    """One notehead: a drum (position on the percussion staff) or a pitch."""
    track: str
    velocity: int
    position: int                   # staff position (0 = bottom line)
    notehead: str = "normal"        # "normal" or "x"
    midi: Optional[int] = None      # pitched only
    accidental: Optional[str] = None
    open: bool = False              # open hi-hat


@dataclass
class Item:
    """A written note, chord or rest."""
    start: Fraction                 # beats from the start of the pattern
    length: Fraction                # sounding length in beats
    value: str                      # whole, half, quarter, eighth, 16th, ...
    dots: int = 0
    heads: List[Head] = field(default_factory=list)  # empty for a rest
    tuplet: bool = False            # written as part of a triplet
    tie_start: bool = False
    tie_stop: bool = False

    @property
    def is_rest(self) -> bool:
        return not self.heads


@dataclass
class Staff:
    kind: str                       # "drums" or "pitched"
    name: str
    clef: str                       # "percussion", "bass" or "treble"
    octave_shift: int = 0           # pitched notes are drawn this many octaves higher (8vb/15mb)
    bars: List[List[Item]] = field(default_factory=list)


@dataclass
class Score:
    bpm: int
    grid: str
    steps_per_beat: int
    beats: Fraction
    staves: List[Staff]


# ---------------------------------------------------------------------------
# Rhythm spelling
# ---------------------------------------------------------------------------

def spell(length: Fraction, triplet: bool) -> List[Tuple[str, int]]:
    """
    Write a duration (in beats) as note values, tied together if one isn't enough.
    In a triplet, written values are 3/2 of the sounding length.
    """
    written = length * Fraction(3, 2) if triplet else length
    pieces: List[Tuple[str, int]] = []
    while written > 0:
        for name, value in VALUES:
            for dots, factor in ((0, Fraction(1)), (1, Fraction(3, 2)), (2, Fraction(7, 4))):
                if value * factor == written:
                    pieces.append((name, dots))
                    return pieces
        name, value = next((n, v) for n, v in VALUES if v <= written)
        pieces.append((name, 0))
        written -= value
    return pieces


def _expand(track: Track, length: int) -> list:
    return [track.steps[i % len(track.steps)] for i in range(length)]


def _drum_onsets(pattern: Pattern, tracks: List[Track]) -> Dict[int, List[Head]]:
    onsets: Dict[int, List[Head]] = {}
    for track in tracks:
        role = role_for(track)
        position, notehead = DRUM_POSITIONS[role]
        for step, value in enumerate(_expand(track, pattern.length)):
            if isinstance(value, int):
                onsets.setdefault(step, []).append(Head(track=track.name, velocity=value, position=position,
                                                        notehead=notehead, open=role == "openhat"))
    for heads in onsets.values():
        heads.sort(key=lambda head: head.position)
    return onsets


def _pitch_position(midi: int, clef: str, octave_shift: int) -> Tuple[int, Optional[str]]:
    name = note_name(midi)                      # e.g. "Eb1", "F#2"
    letter, accidental = name[0], name[1] if len(name) > 2 and name[1] in "#b" else None
    octave = int(name[2:] if accidental else name[1:])
    degree = (octave + octave_shift) * 7 + _DIATONIC.index(letter)
    bottom = (2 * 7 + _DIATONIC.index("G")) if clef == "bass" else (4 * 7 + _DIATONIC.index("E"))
    return degree - bottom, accidental


def _pitched_notes(pattern: Pattern, track: Track) -> List[Tuple[int, int, Tuple[int, ...], int]]:
    """(start step, end step, chord, velocity) for each hit, with holds and the next hit deciding the end."""
    steps = _expand(track, pattern.length)
    hits = [i for i, value in enumerate(steps) if isinstance(value, int)]
    notes = []
    for index, start in enumerate(hits):
        end = start + 1
        while end < pattern.length and steps[end] == HOLD:
            end += 1
        if index + 1 < len(hits):
            end = min(end, hits[index + 1])
        chord = track.notes[index % len(track.notes)]
        notes.append((start, end, chord, steps[start]))
    return notes


def _staff_for_pitched(pattern: Pattern, track: Track) -> Tuple[str, int]:
    midis = sorted(n for chord in track.notes for n in chord)
    median = midis[len(midis) // 2] if midis else 48
    clef = "treble" if median >= 60 else "bass"
    shift = 0
    # Very low lines are written up to three octaves higher (8vb, 15mb, 22mb) so they sit on the staff.
    while shift < 3 and _pitch_position(median, clef, shift)[0] < 2:
        shift += 1
    return clef, shift


# (start step, end step, heads, tied from the previous bar, tied into the next bar)
Event = Tuple[int, int, List[Head], bool, bool]


def _fill_bar(bar: int, events: List[Event], pattern: Pattern) -> List[Item]:
    """Write one bar from events inside it (sorted, not overlapping); the gaps become rests."""
    beat_steps = GRIDS[pattern.grid][1]
    step = pattern.step_beats
    triplet = beat_steps % 3 == 0
    bar_start = bar * BEATS_PER_BAR * beat_steps
    bar_end = bar_start + BEATS_PER_BAR * beat_steps
    bar_beats = Fraction(BEATS_PER_BAR)
    if not events:
        return [Item(start=bar_start * step, length=bar_beats, value="whole")]

    # Timeline of spans covering the bar: notes and the rests between them.
    spans: List[Event] = []
    cursor = bar_start
    for start, end, heads, tied_in, tied_out in events:
        if start > cursor:
            spans.append((cursor, start, [], False, False))
        spans.append((start, end, heads, tied_in, tied_out))
        cursor = end
    if cursor < bar_end:
        spans.append((cursor, bar_end, [], False, False))

    items: List[Item] = []
    half = 2 * beat_steps
    for start, end, heads, tied_in, tied_out in spans:
        # Split at beat lines (ties for notes), but keep empty half bars as one half rest.
        position = start
        while position < end:
            beat_end = (position // beat_steps + 1) * beat_steps
            if not heads and position % half == 0 and end - position >= half:
                items.append(Item(start=position * step, length=Fraction(2), value="half"))
                position += half
                continue
            piece_end = min(end, beat_end)
            length = (piece_end - position) * step
            whole_beat = position % beat_steps == 0 and piece_end - position == beat_steps
            in_triplet = triplet and not whole_beat
            pieces = spell(length, in_triplet)
            offset = Fraction(0)
            for index, (value, dots) in enumerate(pieces):
                written = dict(VALUES)[value] * (Fraction(1) + sum(Fraction(1, 2 ** d) for d in range(1, dots + 1)))
                sounding = written * Fraction(2, 3) if in_triplet else written
                first_piece = position == start and index == 0
                last_piece = piece_end == end and index == len(pieces) - 1
                item = Item(start=position * step + offset, length=sounding, value=value, dots=dots,
                            heads=list(heads), tuplet=in_triplet)
                if heads:
                    item.tie_stop = tied_in if first_piece else True
                    item.tie_start = tied_out if last_piece else True
                items.append(item)
                offset += sounding
            position = piece_end
    return items


def build_score(pattern: Pattern) -> Score:
    beat_steps = GRIDS[pattern.grid][1]
    bar_steps = BEATS_PER_BAR * beat_steps
    bars = -(-pattern.length // bar_steps)  # ceiling
    staves: List[Staff] = []

    drum_tracks = [t for t in pattern.tracks if not t.target.pitched]
    if drum_tracks:
        onsets = _drum_onsets(pattern, drum_tracks)
        steps = sorted(onsets)
        staff = Staff(kind="drums", name="drums", clef="percussion")
        for bar in range(bars):
            lo, hi = bar * bar_steps, (bar + 1) * bar_steps
            events = []
            in_bar = [s for s in steps if lo <= s < hi]
            for index, start in enumerate(in_bar):
                beat_end = (start // beat_steps + 1) * beat_steps
                following = in_bar[index + 1] if index + 1 < len(in_bar) else hi
                events.append((start, min(beat_end, following, hi), onsets[start], False, False))
            staff.bars.append(_fill_bar(bar, events, pattern))
        staves.append(staff)

    for track in (t for t in pattern.tracks if t.target.pitched):
        clef, shift = _staff_for_pitched(pattern, track)
        staff = Staff(kind="pitched", name=track.name, clef=clef, octave_shift=shift)
        notes = _pitched_notes(pattern, track)
        for bar in range(bars):
            lo, hi = bar * bar_steps, (bar + 1) * bar_steps
            events = []
            for start, end, chord, velocity in notes:
                if end <= lo or start >= hi:
                    continue
                heads = []
                for midi in chord:
                    position, accidental = _pitch_position(midi, clef, shift)
                    heads.append(Head(track=track.name, velocity=velocity, position=position, midi=midi,
                                      accidental=accidental))
                events.append((max(start, lo), min(end, hi), heads, start < lo, end > hi))
            staff.bars.append(_fill_bar(bar, events, pattern))
        staves.append(staff)

    return Score(bpm=pattern.bpm, grid=pattern.grid, steps_per_beat=beat_steps,
                 beats=pattern.length_beats, staves=staves)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def score_to_dict(score: Score) -> Dict:
    def item(i: Item) -> Dict:
        return {
            "start": float(i.start), "length": float(i.length), "value": i.value, "dots": i.dots,
            "rest": i.is_rest, "tuplet": i.tuplet, "tie_start": i.tie_start, "tie_stop": i.tie_stop,
            "heads": [{"track": h.track, "velocity": h.velocity, "position": h.position, "notehead": h.notehead,
                       "midi": h.midi, "accidental": h.accidental, "open": h.open} for h in i.heads],
        }
    return {
        "bpm": score.bpm, "grid": score.grid, "steps_per_beat": score.steps_per_beat, "beats": float(score.beats),
        "staves": [{"kind": s.kind, "name": s.name, "clef": s.clef, "octave_shift": s.octave_shift,
                    "bars": [[item(i) for i in bar] for bar in s.bars]} for s in score.staves],
    }


_XML_TYPES = {"whole": "whole", "half": "half", "quarter": "quarter", "eighth": "eighth",
              "16th": "16th", "32nd": "32nd", "64th": "64th"}


def score_to_musicxml(score: Score, title: str = "koii pattern") -> str:
    """A MusicXML 4.0 partwise score: one part per staff."""
    divisions = 48  # per quarter note: fits 1/32 notes and triplets of 1/16
    from xml.sax.saxutils import escape

    def duration(item: Item) -> int:
        return int(item.length * divisions)

    parts_list = []
    parts = []
    for index, staff in enumerate(score.staves, start=1):
        part_id = f"P{index}"
        parts_list.append(f'<score-part id="{part_id}"><part-name>{escape(staff.name)}</part-name></score-part>')
        measures = []
        for number, bar in enumerate(staff.bars, start=1):
            xml = [f'<measure number="{number}">']
            if number == 1:
                clef = {"percussion": "<sign>percussion</sign>", "bass": "<sign>F</sign><line>4</line>",
                        "treble": "<sign>G</sign><line>2</line>"}[staff.clef]
                octave = f"<clef-octave-change>{-staff.octave_shift}</clef-octave-change>" if staff.octave_shift else ""
                xml.append(f"<attributes><divisions>{divisions}</divisions><key><fifths>0</fifths></key>"
                           f"<time><beats>4</beats><beat-type>4</beat-type></time><clef>{clef}{octave}</clef></attributes>")
                xml.append(f'<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
                           f"<per-minute>{score.bpm}</per-minute></metronome></direction-type>"
                           f'<sound tempo="{score.bpm}"/></direction>')
            for item in bar:
                heads = item.heads or [None]
                for head_index, head in enumerate(heads):
                    note = ["<note>"]
                    if head_index > 0:
                        note.append("<chord/>")
                    if head is None:
                        note.append('<rest measure="yes"/>' if item.value == "whole" else "<rest/>")
                    elif staff.kind == "drums":
                        step, octave = _drum_display(head.position)
                        note.append(f"<unpitched><display-step>{step}</display-step>"
                                    f"<display-octave>{octave}</display-octave></unpitched>")
                    else:
                        name = note_name(head.midi)
                        alter = {"#": 1, "b": -1}.get(head.accidental or "", 0)
                        octave = int(name[2:] if head.accidental else name[1:])
                        alter_xml = f"<alter>{alter}</alter>" if alter else ""
                        note.append(f"<pitch><step>{name[0]}</step>{alter_xml}<octave>{octave}</octave></pitch>")
                    note.append(f"<duration>{duration(item)}</duration>")
                    if item.tie_stop:
                        note.append('<tie type="stop"/>')
                    if item.tie_start:
                        note.append('<tie type="start"/>')
                    note.append(f"<type>{_XML_TYPES[item.value]}</type>")
                    note.extend("<dot/>" for _ in range(item.dots))
                    if head and head.accidental:
                        note.append(f"<accidental>{'sharp' if head.accidental == '#' else 'flat'}</accidental>")
                    if item.tuplet:
                        note.append("<time-modification><actual-notes>3</actual-notes>"
                                    "<normal-notes>2</normal-notes></time-modification>")
                    if head and head.notehead == "x":
                        note.append("<notehead>x</notehead>")
                    notations = []
                    if item.tie_stop:
                        notations.append('<tied type="stop"/>')
                    if item.tie_start:
                        notations.append('<tied type="start"/>')
                    if head and head.velocity >= 120:
                        notations.append("<articulations><accent/></articulations>")
                    if notations:
                        note.append(f"<notations>{''.join(notations)}</notations>")
                    note.append("</note>")
                    xml.append("".join(note))
            xml.append("</measure>")
            measures.append("".join(xml))
        parts.append(f'<part id="{part_id}">{"".join(measures)}</part>')

    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
            '"http://www.musicxml.org/dtds/partwise.dtd">'
            f'<score-partwise version="4.0"><work><work-title>{escape(title)}</work-title></work>'
            f'<part-list>{"".join(parts_list)}</part-list>{"".join(parts)}</score-partwise>')


def _drum_display(position: int) -> Tuple[str, int]:
    """Percussion staff position -> display step/octave (treble-clef placement, bottom line E4)."""
    degree = 4 * 7 + _DIATONIC.index("E") + position
    return _DIATONIC[degree % 7], degree // 7
