"""
Parser for koii studio pattern notation. The format is specified in NOTATION.md.

parse_pattern() turns text into a Pattern, or raises NotationError listing
every problem found (with line and column), so a writer can fix them all in
one pass.
"""

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple, Union

from koii_studio import device

# Step values: an int is a hit velocity, HOLD extends the previous note, None is a rest.
HOLD = "hold"
Step = Union[int, str, None]

STEP_VELOCITY = {"x": 100, "X": 127, "o": 50}
STEP_VELOCITY.update({str(n): round(n * 127 / 9) for n in range(1, 10)})
REST_CHARS = {"."}
IGNORED_CHARS = {" ", "\t", "|"}

# Grid name -> (beats per step, steps per beat for display grouping)
GRIDS: Dict[str, Tuple[Fraction, int]] = {
    "1/4": (Fraction(1), 1),
    "1/8": (Fraction(1, 2), 2),
    "1/16": (Fraction(1, 4), 4),
    "1/32": (Fraction(1, 8), 8),
    "1/8t": (Fraction(1, 3), 3),
    "1/16t": (Fraction(1, 6), 6),
}

DEFAULT_BPM = 120
BPM_RANGE = (20, 300)
SWING_RANGE = (50, 75)
MAX_STEPS = 1024

_NAME = r"[A-Za-z0-9][\w.\-]*|[A-Da-d][.↵]"
_TRACK_RE = re.compile(rf"^(?P<name>{_NAME})\s*:(?P<steps>.*)$")
_NOTES_RE = re.compile(rf"^(?P<name>{_NAME})\s+notes\s*:(?P<notes>.*)$", re.IGNORECASE)
_NOTE_NAME_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d)$")
_CHANNEL_RE = re.compile(r"^ch(\d{1,2})$", re.IGNORECASE)
_PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


@dataclass
class Issue:
    line: int
    column: Optional[int]
    message: str

    def __str__(self) -> str:
        if not self.line:
            return self.message
        where = f"line {self.line}" + (f", col {self.column}" if self.column else "")
        return f"{where}: {self.message}"


class NotationError(ValueError):
    """One or more problems in a pattern or arrangement."""

    def __init__(self, issues: List[Issue]):
        self.issues = issues
        super().__init__("\n".join(str(i) for i in issues))


def tempo_override(bpm: Any) -> Optional[int]:
    """A tempo given to play or save at (None or 0: the patterns' own), checked like @bpm."""
    if bpm in (None, "", 0):
        return None
    if isinstance(bpm, bool) or not str(bpm).isdigit() or not BPM_RANGE[0] <= int(bpm) <= BPM_RANGE[1]:
        raise NotationError([Issue(0, None, f"bpm needs a whole number from {BPM_RANGE[0]} to {BPM_RANGE[1]}, not {bpm!r}")])
    return int(bpm)


@dataclass(frozen=True)
class Target:
    """What a track plays: a pad, a raw MIDI note, or pitched notes on a channel."""
    kind: str                      # "pad" | "note" | "channel"
    note: Optional[int] = None     # pad / note targets
    channel: Optional[int] = None  # channel targets (1-16)
    label: str = ""

    @property
    def pitched(self) -> bool:
        return self.kind == "channel"


@dataclass
class Track:
    name: str
    target: Target
    steps: List[Step] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)  # step characters as written, for display
    notes: List[Tuple[int, ...]] = field(default_factory=list)
    line: int = 0


@dataclass
class Pattern:
    tracks: List[Track]
    length: int
    bpm: int = DEFAULT_BPM
    swing: int = 50
    grid: str = "1/16"
    source: str = ""
    warnings: List[str] = field(default_factory=list)
    maps: Dict[str, str] = field(default_factory=dict)  # @map name -> target label

    @property
    def step_beats(self) -> Fraction:
        return GRIDS[self.grid][0]

    @property
    def length_beats(self) -> Fraction:
        return self.length * self.step_beats


# ---------------------------------------------------------------------------
# Small parsers shared with the rest of the package
# ---------------------------------------------------------------------------

def parse_target(text: str) -> Optional[Target]:
    """Parse a pad label, MIDI note number or chN. Returns None if it's none of those."""
    text = text.strip()
    pad = device.parse_pad(text)
    if pad:
        group, key = pad
        return Target("pad", note=device.pad_note(group, key), label=device.pad_label(group, key))
    m = _CHANNEL_RE.match(text)
    if m and 1 <= int(m.group(1)) <= 16:
        return Target("channel", channel=int(m.group(1)), label=f"ch{int(m.group(1))}")
    if text.isdigit() and 0 <= int(text) <= 127:
        note = int(text)
        return Target("note", note=note, label=device.note_pad(note) or str(note))
    return None


def parse_note(token: str) -> Optional[int]:
    """'C4' -> 60, 'F#2' -> 42, 'Bb1' -> 34, '48' -> 48. None if invalid or out of range."""
    if token.isdigit():
        value = int(token)
        return value if value <= 127 else None
    m = _NOTE_NAME_RE.match(token)
    if not m:
        return None
    letter, accidental, octave = m.groups()
    value = (int(octave) + 1) * 12 + _PITCH_CLASS[letter.upper()]
    value += {"#": 1, "b": -1, "": 0}[accidental]
    return value if 0 <= value <= 127 else None


def note_name(note: int) -> str:
    return f"{_NOTE_NAMES[note % 12]}{note // 12 - 1}"


def strip_comment(line: str) -> str:
    """Remove a '#' comment that starts the line or follows whitespace (C#2 is kept)."""
    for i, ch in enumerate(line):
        if ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


def resolve_name(name: str, maps: Dict[str, Target], aliases: Dict[str, str]) -> Optional[Target]:
    """Resolve a track name: pattern @map, then kit alias, then pad label / MIDI note / chN."""
    key = name.lower()
    if key in maps:
        return maps[key]
    if key in aliases:
        return parse_target(aliases[key])
    return parse_target(name)


# ---------------------------------------------------------------------------
# Pattern parser
# ---------------------------------------------------------------------------

def _parse_steps(text: str, line_no: int, col0: int, issues: List[Issue],
                 previous: Step = None) -> Tuple[List[Step], List[str]]:
    """
    Parse one line of steps. Returns the step values and the characters they came from.
    `previous` is the track's last step from earlier lines, so a hold can carry on across lines.
    """
    steps: List[Step] = []
    symbols: List[str] = []
    for i, ch in enumerate(text):
        col = col0 + i
        if ch in IGNORED_CHARS:
            continue
        symbols.append(ch)
        if ch in STEP_VELOCITY:
            steps.append(STEP_VELOCITY[ch])
        elif ch in REST_CHARS:
            steps.append(None)
        elif ch == "-":
            before = steps[-1] if steps else previous
            if before is None:
                issues.append(Issue(line_no, col, "'-' (hold) must follow a hit or another '-'"))
            steps.append(HOLD)
        elif ch == "0":
            issues.append(Issue(line_no, col, "'0' is not a step; use '.' for a rest or 1-9 for a level"))
            steps.append(None)
        else:
            issues.append(Issue(
                line_no, col,
                f"unknown step '{ch}'. Steps are x X o 1-9 (hits), . (rest), - (hold); "
                "spaces and | are ignored",
            ))
            steps.append(None)
    return steps, symbols


def _parse_directive(body: str, line_no: int, settings: Dict, maps: Dict[str, Target],
                     issues: List[Issue]) -> None:
    parts = body.split(None, 1)
    key = parts[0].lower() if parts else ""
    value = parts[1].strip() if len(parts) > 1 else ""

    if key == "bpm":
        if not value.isdigit() or not BPM_RANGE[0] <= int(value) <= BPM_RANGE[1]:
            issues.append(Issue(line_no, None, f"@bpm needs a whole number from {BPM_RANGE[0]} to {BPM_RANGE[1]}"))
        else:
            settings["bpm"] = int(value)
    elif key == "swing":
        if not value.isdigit() or not SWING_RANGE[0] <= int(value) <= SWING_RANGE[1]:
            issues.append(Issue(line_no, None, "@swing needs a percent from 50 (straight) to 75"))
        else:
            settings["swing"] = int(value)
    elif key == "grid":
        grid = value.lower()
        if grid not in GRIDS:
            issues.append(Issue(line_no, None, f"@grid must be one of {', '.join(GRIDS)}"))
        else:
            settings["grid"] = grid
    elif key == "map":
        name, eq, target_text = value.partition("=")
        name = name.strip()
        target = parse_target(target_text) if eq else None
        if not eq or not re.fullmatch(_NAME, name):
            issues.append(Issue(line_no, None, "write @map as: @map name = target  (e.g. @map bass = ch2)"))
        elif target is None:
            issues.append(Issue(
                line_no, None,
                f"@map target '{target_text.strip()}' isn't a pad (A1, B., CEnter), MIDI note (0-127) or channel (ch1-ch16)",
            ))
        else:
            maps[name.lower()] = target
    else:
        issues.append(Issue(line_no, None, f"unknown directive '@{key}'. Use @bpm, @swing, @grid or @map"))


def parse_pattern(text: str, aliases: Optional[Dict[str, str]] = None) -> Pattern:
    """Parse pattern text. Raises NotationError listing every problem found."""
    aliases = {k.lower(): v for k, v in (aliases if aliases is not None else device.DEFAULT_ALIASES).items()}
    issues: List[Issue] = []
    settings: Dict = {}
    maps: Dict[str, Target] = {}
    step_lines: List[Tuple[int, str, str, int]] = []   # (line, name, steps text, col)
    note_lines: List[Tuple[int, str, str, int]] = []

    # Pass 1: directives first, so @map applies regardless of where it appears.
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = strip_comment(raw).rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("@"):
            _parse_directive(stripped[1:], line_no, settings, maps, issues)
            continue
        m = _NOTES_RE.match(stripped)
        if m:
            note_lines.append((line_no, m.group("name"), m.group("notes"), indent + m.start("notes") + 1))
            continue
        m = _TRACK_RE.match(stripped)
        if m:
            step_lines.append((line_no, m.group("name"), m.group("steps"), indent + m.start("steps") + 1))
            continue
        if re.fullmatch(r"[xXo1-9.\-| ]+", stripped):
            # Old style was 'x...x...  # kick'; suggest the new form with that name.
            old_name = raw[len(line):].lstrip("# \t").split()
            name = old_name[0] if old_name else "kick"
            issues.append(Issue(line_no, None, f"missing track name. Put the sound first: '{name}: {stripped}'"))
        else:
            issues.append(Issue(line_no, None, f"can't read '{stripped}'. Expected 'name: steps', 'name notes: ...' or '@directive'"))

    # Pass 2: tracks. Repeating a name continues the track.
    tracks: Dict[str, Track] = {}
    for line_no, name, steps_text, col in step_lines:
        key = name.lower()
        if key not in tracks:
            target = resolve_name(name, maps, aliases)
            if target is None:
                issues.append(Issue(
                    line_no, None,
                    f"unknown sound '{name}'. Use a kit alias (kick, snare, hat, ...), a pad (A1, B., CEnter), "
                    "a MIDI note (36), or add '@map " + name + " = <target>'",
                ))
                target = Target("note", note=0, label="?")
            tracks[key] = Track(name=name, target=target, line=line_no)
        previous = tracks[key].steps[-1] if tracks[key].steps else None
        steps, symbols = _parse_steps(steps_text, line_no, col, issues, previous)
        if not steps:
            issues.append(Issue(line_no, None, f"track '{name}' has no steps"))
        tracks[key].steps.extend(steps)
        tracks[key].symbols.extend(symbols)

    for line_no, name, notes_text, col in note_lines:
        track = tracks.get(name.lower())
        if track is None:
            issues.append(Issue(line_no, None, f"'{name} notes' has no '{name}:' rhythm line"))
            continue
        for match in re.finditer(r"\S+", notes_text):
            token = match.group(0)
            chord = []
            for part in token.split("+"):
                value = parse_note(part)
                if value is None:
                    issues.append(Issue(
                        line_no, col + match.start(),
                        f"'{part}' isn't a note. Use names like C2, F#3, Bb1 (C4 = middle C) or numbers 0-127; "
                        "join chord notes with +",
                    ))
                else:
                    chord.append(value)
            if chord:
                track.notes.append(tuple(chord))

    # Pass 3: whole-pattern checks.
    for track in tracks.values():
        if track.target.pitched and not track.notes:
            issues.append(Issue(track.line, None, f"'{track.name}' plays on {track.target.label} and needs a '{track.name} notes: ...' line"))
        if not track.target.pitched and track.notes:
            issues.append(Issue(
                track.line, None,
                f"'{track.name}' plays pad/note {track.target.label}, which has a fixed pitch. To play notes, "
                f"map it to a MIDI channel ('@map {track.name} = ch2') and set that pad's channel on the device",
            ))

    if not tracks and not issues:
        issues.append(Issue(1, None, "no tracks. Write at least one line like 'kick: x...x...x...x...'"))

    length = max((len(t.steps) for t in tracks.values()), default=0)
    if length > MAX_STEPS:
        issues.append(Issue(1, None, f"pattern is {length} steps; the limit is {MAX_STEPS}"))
    misfits = [t for t in tracks.values() if t.steps and length % len(t.steps)]
    if misfits:
        longest = next(t for t in tracks.values() if len(t.steps) == length)
        steps_per_beat = GRIDS[settings.get("grid", "1/16")][1]
        for track in misfits:
            issues.append(Issue(
                track.line, None,
                f"'{track.name}' has {len(track.steps)} steps, which doesn't divide the longest track "
                f"'{longest.name}' ({length} steps). Every track must be as long as the longest or divide it evenly",
            ))
        for track in [longest] + misfits:
            if len(track.steps) % steps_per_beat:
                issues.append(Issue(
                    track.line, None,
                    f"'{track.name}' is {len(track.steps)} steps, not a whole number of beats "
                    f"({steps_per_beat} steps per beat) — is a step missing or extra?",
                ))

    if issues:
        raise NotationError(sorted(issues, key=lambda i: (i.line, i.column or 0)))

    return Pattern(
        tracks=list(tracks.values()),
        length=length,
        bpm=settings.get("bpm", DEFAULT_BPM),
        swing=settings.get("swing", 50),
        grid=settings.get("grid", "1/16"),
        source=text,
        warnings=_pad_collision_warnings(tracks.values()) + _polyphony_warnings(tracks.values(), length),
        maps={name: _target_text(target) for name, target in maps.items()},
    )


# The EP-133 plays up to 16 mono or 12 stereo voices at once (official spec, OS 2.0+).
MAX_VOICES_STEREO = 12
MAX_VOICES_MONO = 16


def _polyphony_warnings(tracks, length: int) -> List[str]:
    """Warn when one step starts more notes than the device can play together."""
    starts = [0] * length
    for track in tracks:
        note_index = 0
        for step in range(length):
            value = track.steps[step % len(track.steps)]
            if not isinstance(value, int):
                continue
            if track.target.pitched and track.notes:
                starts[step] += len(track.notes[note_index % len(track.notes)])
                note_index += 1
            else:
                starts[step] += 1
    busiest = max(starts, default=0)
    if busiest <= MAX_VOICES_STEREO:
        return []
    step = starts.index(busiest) + 1
    return [f"step {step} starts {busiest} notes at once; the EP-133 plays at most {MAX_VOICES_MONO} mono or "
            f"{MAX_VOICES_STEREO} stereo voices, so some will be cut short"]


def _target_text(target: Target) -> str:
    """How a target is written in a pattern: a pad label, a MIDI note number or chN."""
    return str(target.note) if target.kind == "note" and target.label == str(target.note) else target.label


def _pad_collision_warnings(tracks) -> List[str]:
    """
    Pitched notes in 36-83 share note numbers with pads. Pads that listen on all
    channels (the EP-133 default) play along with them, as seen on hardware.
    """
    warnings = []
    for track in tracks:
        if not track.target.pitched:
            continue
        clashes = sorted({n for chord in track.notes for n in chord if device.note_pad(n)})
        if clashes:
            names = ", ".join(f"{note_name(n)} ({device.note_pad(n)})" for n in clashes)
            warnings.append(
                f"'{track.name}' notes {names} share note numbers with pads. If the EP-133 receives on all "
                "channels (the default), those pads will play too. Keep pitched notes below C2, or set the "
                "system MIDI channel to 1 (see DEVICE.md)."
            )
    return warnings


# ---------------------------------------------------------------------------
# Rendering (normalised view returned to the user / Claude)
# ---------------------------------------------------------------------------

def format_steps(symbols: List[str], steps_per_beat: int) -> str:
    """Step characters as written, with a '|' between beats."""
    beats = [symbols[i:i + steps_per_beat] for i in range(0, len(symbols), steps_per_beat)]
    return "|".join("".join(beat) for beat in beats)


def render_pattern(pattern: Pattern) -> str:
    """A compact, normalised description of a parsed pattern."""
    steps_per_beat = GRIDS[pattern.grid][1]
    beats = pattern.length_beats
    bars = beats / 4
    bar_text = f"{bars} bar{'s' if bars != 1 else ''}" if bars.denominator == 1 else f"{float(beats):g} beats"
    header = f"{pattern.length} steps of {pattern.grid} ({bar_text}) · {pattern.bpm} BPM"
    if pattern.swing != 50:
        header += f" · swing {pattern.swing}%"
    lines = [header]
    width = max(len(t.name) for t in pattern.tracks)
    for track in pattern.tracks:
        target = track.target.label
        if track.target.kind != "channel":
            target = f"{target} ({track.target.note})" if track.target.label != str(track.target.note) else target
        row = f"  {track.name.ljust(width)}  {target.ljust(10)} {format_steps(track.symbols, steps_per_beat)}"
        if len(track.steps) < pattern.length:
            row += f"  ×{pattern.length // len(track.steps)}"
        if track.notes:
            row += "   " + " ".join("+".join(note_name(n) for n in chord) for chord in track.notes)
        lines.append(row)
    lines.extend(f"warning: {w}" for w in pattern.warnings)
    return "\n".join(lines)


def pattern_to_dict(pattern: Pattern) -> Dict:
    """A JSON-friendly description of a parsed pattern, for the visualiser."""
    return {
        "bpm": pattern.bpm,
        "swing": pattern.swing,
        "grid": pattern.grid,
        "steps_per_beat": GRIDS[pattern.grid][1],
        "step_beats": float(pattern.step_beats),
        "length": pattern.length,
        "beats": float(pattern.length_beats),
        "maps": dict(pattern.maps),
        "warnings": list(pattern.warnings),
        "source": pattern.source,
        "tracks": [
            {
                "name": track.name,
                "target": {
                    "kind": track.target.kind,
                    "label": track.target.label,
                    "note": track.target.note,
                    "channel": track.target.channel,
                },
                "symbols": list(track.symbols),
                "notes": ["+".join(note_name(n) for n in chord) for chord in track.notes],
                "midi_notes": [list(chord) for chord in track.notes],
                "line": track.line,
            }
            for track in pattern.tracks
        ],
    }


# ---------------------------------------------------------------------------
# Arrangements: "intro x2, verse+bass x4, chorus"
# ---------------------------------------------------------------------------

@dataclass
class Section:
    names: List[str]
    repeat: int = 1


_SECTION_RE = re.compile(r"^(?P<names>[\w.\-]+(?:\s*\+\s*[\w.\-]+)*)(?:\s+[x×]\s*(?P<n>\d+))?$")


def parse_arrangement(text: str) -> List[Section]:
    issues: List[Issue] = []
    sections: List[Section] = []
    for line_no, raw in enumerate(text.splitlines() or [text], start=1):
        for item in strip_comment(raw).split(","):
            item = item.strip()
            if not item:
                continue
            m = _SECTION_RE.match(item)
            if not m:
                issues.append(Issue(line_no, None, f"can't read section '{item}'. Write 'name', 'name x4' or 'a+b x2'"))
                continue
            repeat = int(m.group("n") or 1)
            if not 1 <= repeat <= 999:
                issues.append(Issue(line_no, None, f"repeat count in '{item}' must be 1-999"))
                continue
            names = [n.strip() for n in m.group("names").split("+")]
            sections.append(Section(names=names, repeat=repeat))
    if not sections and not issues:
        issues.append(Issue(1, None, "empty arrangement"))
    if issues:
        raise NotationError(issues)
    return sections


def looks_like_pattern(text: str) -> bool:
    """Pattern text has 'name:' track lines or @directives; arrangements never contain ':'."""
    return ":" in text or text.strip().startswith("@")
