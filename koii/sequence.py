"""
Turn parsed patterns and arrangements into timed MIDI events.

Times are kept in beats (exact Fractions) so the same compiled sections drive
both live playback (converted to seconds) and MIDI file export (ticks).
"""

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, List, Optional, Tuple

import mido

from koii.notation import HOLD, Issue, NotationError, Pattern, parse_arrangement

# A channel of None means "the connection's default channel".
NOTE_OFF, NOTE_ON = 0, 1


@dataclass(frozen=True)
class Event:
    beat: Fraction
    kind: int              # NOTE_OFF sorts before NOTE_ON at the same time
    note: int
    velocity: int
    channel: Optional[int]


@dataclass
class Section:
    label: str
    bpm: int
    length_beats: Fraction
    events: List[Event] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return float(self.length_beats) * 60.0 / self.bpm


def _step_time(index: int, pattern: Pattern) -> Fraction:
    """Start of a step in beats, with swing pushing every second step late."""
    t = index * pattern.step_beats
    if index % 2 == 1 and pattern.swing != 50:
        t += pattern.step_beats * Fraction(pattern.swing - 50, 50)
    return t


def compile_pattern(pattern: Pattern, cycles: int = 1) -> List[Event]:
    """Events for `cycles` back-to-back passes of a pattern, starting at beat 0."""
    events: List[Event] = []
    length = pattern.length
    for track in pattern.tracks:
        steps = track.steps * (length // len(track.steps))
        note_index = 0
        for cycle in range(cycles):
            offset = cycle * pattern.length_beats
            for i, step in enumerate(steps):
                if step is None or step == HOLD:
                    continue
                end = i + 1
                while end < length and steps[end] == HOLD:
                    end += 1
                start_beat = offset + _step_time(i, pattern)
                end_beat = offset + (_step_time(end, pattern) if end < length else pattern.length_beats)
                if track.target.pitched:
                    chord = track.notes[note_index % len(track.notes)]
                    note_index += 1
                    channel = track.target.channel
                else:
                    chord = (track.target.note,)
                    channel = None
                for note in chord:
                    events.append(Event(start_beat, NOTE_ON, note, step, channel))
                    events.append(Event(end_beat, NOTE_OFF, note, 0, channel))
    events.sort(key=lambda e: (e.beat, e.kind, e.note))
    return events


def layer(patterns: List[Tuple[str, Pattern]], bpm: Optional[int] = None) -> Section:
    """Play several patterns together. Shorter ones must divide the longest and repeat."""
    longest = max(p.length_beats for _, p in patterns)
    issues = []
    for name, p in patterns:
        if longest % p.length_beats:
            issues.append(Issue(0, None, f"'{name}' is {p.length_beats} beats, which doesn't divide {longest} beats; "
                                         "layered patterns must fit evenly into the longest one"))
    if issues:
        raise NotationError(issues)
    events: List[Event] = []
    for _, p in patterns:
        events.extend(compile_pattern(p, cycles=int(longest / p.length_beats)))
    events.sort(key=lambda e: (e.beat, e.kind, e.note))
    label = "+".join(name for name, _ in patterns)
    return Section(label=label, bpm=bpm or patterns[0][1].bpm, length_beats=longest, events=events)


def expand(
    arrangement: str,
    get_pattern: Callable[[str], Optional[Pattern]],
    get_song: Callable[[str], Optional[Tuple[str, Optional[int]]]],
    bpm: Optional[int] = None,
    _depth: int = 0,
) -> List[Section]:
    """
    Expand an arrangement ("intro x2, verse+bass x4") into sections, one per pass.

    get_pattern(name) returns a parsed Pattern or None; get_song(name) returns
    (arrangement, bpm) or None. A song name inside an arrangement expands in place.
    """
    if _depth > 8:
        raise NotationError([Issue(0, None, "songs nest too deeply (does a song include itself?)")])
    sections: List[Section] = []
    issues = []
    for part in parse_arrangement(arrangement):
        if len(part.names) == 1 and get_song(part.names[0]) is not None:
            song_text, song_bpm = get_song(part.names[0])
            inner = expand(song_text, get_pattern, get_song, bpm or song_bpm, _depth + 1)
            sections.extend(inner * part.repeat)
            continue
        found = []
        for name in part.names:
            pattern = get_pattern(name)
            if pattern is None:
                hint = "; it's a song (songs can't be layered with +)" if get_song(name) else ""
                issues.append(Issue(0, None, f"no pattern named '{name}'{hint}"))
            else:
                found.append((name, pattern))
        if found and len(found) == len(part.names):
            section = layer(found, bpm)
            sections.extend([section] * part.repeat)
    if issues:
        raise NotationError(issues)
    return sections


def total_seconds(sections: List[Section]) -> float:
    return sum(s.seconds for s in sections)


def timeline(sections: List[Section], default_channel: int) -> Tuple[List[Tuple[float, mido.Message]], float]:
    """Flatten sections into (seconds, message) pairs plus the total duration."""
    out: List[Tuple[float, mido.Message]] = []
    start = 0.0
    for section in sections:
        seconds_per_beat = 60.0 / section.bpm
        for e in section.events:
            channel = (e.channel or default_channel) - 1
            kind = "note_on" if e.kind == NOTE_ON else "note_off"
            out.append((start + float(e.beat) * seconds_per_beat,
                        mido.Message(kind, note=e.note, velocity=e.velocity, channel=channel)))
        start += section.seconds
    return out, start


def to_midi_file(sections: List[Section], default_channel: int, ticks_per_beat: int = 480) -> mido.MidiFile:
    """A single-track Standard MIDI File with a tempo change at each section that needs one."""
    mid = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("track_name", name="koii", time=0))

    absolute: List[Tuple[int, int, mido.Message]] = []  # (tick, order, msg)
    start = Fraction(0)
    current_bpm = None
    for section in sections:
        if section.bpm != current_bpm:
            tick = round(start * ticks_per_beat)
            absolute.append((tick, -1, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(section.bpm))))
            current_bpm = section.bpm
        for e in section.events:
            tick = round((start + e.beat) * ticks_per_beat)
            kind = "note_on" if e.kind == NOTE_ON else "note_off"
            absolute.append((tick, e.kind, mido.Message(kind, note=e.note, velocity=e.velocity,
                                                        channel=(e.channel or default_channel) - 1)))
        start += section.length_beats

    absolute.sort(key=lambda x: (x[0], x[1]))
    last = 0
    for tick, _, msg in absolute:
        track.append(msg.copy(time=tick - last))
        last = tick
    end_tick = round(start * ticks_per_beat)
    track.append(mido.MetaMessage("end_of_track", time=max(0, end_tick - last)))
    return mid
