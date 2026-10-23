"""
The studio: MIDI connection + pattern library + player.

Every method returns a human-readable string (or raises a ValueError subclass
with a helpful message), which keeps the MCP tool layer thin and lets the same
behaviour be tested without MCP or hardware.
"""

import logging
import re
import threading
from pathlib import Path
from typing import Callable, List, Optional

import mido

from koii import device
from koii.library import Library, LibraryError
from koii.notation import NotationError, looks_like_pattern, note_name, parse_target, render_pattern
from koii.player import Player
from koii.sequence import Section, expand, layer, to_midi_file, total_seconds

logger = logging.getLogger(__name__)

_DEVICE_PORT_HINTS = ("ep-133", "ep133", "k.o", "ko ii", "ko-ii", "koii", "teenage")


class NotConnected(ValueError):
    pass


class Studio:
    def __init__(self, library: Optional[Library] = None,
                 open_output: Callable[[str], object] = mido.open_output,
                 list_outputs: Callable[[], List[str]] = mido.get_output_names):
        self.library = library or Library()
        self._open_output = open_output
        self._list_outputs = list_outputs
        self.port = None
        self.channel = device.DEFAULT_CHANNEL
        self._send_lock = threading.Lock()
        self.player = Player(self._send)

    # -- connection ---------------------------------------------------------

    def _send(self, msg: mido.Message) -> None:
        with self._send_lock:
            if self.port is not None:
                self.port.send(msg)

    def list_ports(self) -> List[str]:
        try:
            return list(self._list_outputs())
        except Exception as e:  # rtmidi raises SystemError when the OS MIDI service is unavailable
            raise NotConnected(f"couldn't query MIDI ports ({e}). Is python-rtmidi installed and the "
                               "system MIDI service available?") from e

    def connect(self, port: Optional[str] = None, channel: int = device.DEFAULT_CHANNEL) -> str:
        if not 1 <= channel <= 16:
            raise ValueError("channel must be 1-16")
        ports = self.list_ports()
        if not ports:
            raise NotConnected("no MIDI outputs found. Is the EP-133 plugged in over USB and switched on?")
        if port:
            matches = [p for p in ports if p == port] or [p for p in ports if port.lower() in p.lower()]
            if not matches:
                raise NotConnected(f"no MIDI output matching '{port}'. Available: {', '.join(ports)}")
            name = matches[0]
        else:
            likely = [p for p in ports if any(h in p.lower() for h in _DEVICE_PORT_HINTS)]
            if not likely:
                raise NotConnected(f"couldn't spot the EP-133. Pick one with connect(port=...): {', '.join(ports)}")
            name = likely[0]
        self.disconnect()
        self.port = self._open_output(name)
        self.channel = channel
        return f"connected to '{name}', sending pad hits on MIDI channel {channel}"

    def disconnect(self) -> str:
        self.player.stop()
        with self._send_lock:
            if self.port is None:
                return "not connected"
            name = getattr(self.port, "name", "MIDI port")
            self.port.close()
            self.port = None
        return f"disconnected from '{name}'"

    def _require_port(self) -> None:
        if self.port is None:
            raise NotConnected("not connected to a MIDI device. Call connect() first (list_midi_ports() shows what's available)")

    # -- building blocks ----------------------------------------------------

    def _sections(self, what: str, bpm: Optional[int]) -> tuple:
        """Resolve pattern text, a saved name, 'a+b', a song or an arrangement into sections."""
        if looks_like_pattern(what):
            pattern = self.library.parse(what)
            if bpm:
                pattern.bpm = bpm
            return [layer([("pattern", pattern)])], "pattern", render_pattern(pattern)
        sections = expand(what, self.library.get_pattern, self.library.get_song, bpm)
        return sections, what.strip(), _describe_sections(sections)

    # -- patterns -----------------------------------------------------------

    def check(self, text: str) -> str:
        return "OK\n" + render_pattern(self.library.parse(text))

    def play(self, what: str, repeat: int = 1, loop: bool = False, bpm: Optional[int] = None) -> str:
        if not 1 <= repeat <= 999:
            raise ValueError("repeat must be 1-999")
        sections, label, description = self._sections(what, bpm)  # validate before needing a device
        self._require_port()
        message = self.player.play(sections * repeat, self.channel, loop, label)
        return f"{message}\n{description}"

    def stop(self) -> str:
        return "stopped" if self.player.stop() else "nothing was playing"

    def save_pattern(self, name: str, text: str) -> str:
        existed = self.library.lookup(name)[0] == "pattern"
        pattern = self.library.save_pattern(name, text)
        return f"{'updated' if existed else 'saved'} pattern '{name}'\n{render_pattern(pattern)}"

    def save_song(self, name: str, arrangement: str, bpm: Optional[int] = None) -> str:
        # Validate that everything it references exists before saving.
        sections = expand(arrangement, self.library.get_pattern, self.library.get_song, bpm)
        self.library.save_song(name, arrangement, bpm)
        return f"saved song '{name}'\n{_describe_sections(sections)}"

    def show(self, name: str) -> str:
        kind, stored = self.library.lookup(name)
        if kind == "pattern":
            text = self.library.patterns[stored]["text"]
            return f"pattern '{stored}':\n{text.strip()}\n\n{render_pattern(self.library.get_pattern(stored))}"
        if kind == "song":
            arrangement, bpm = self.library.get_song(stored)
            sections = expand(arrangement, self.library.get_pattern, self.library.get_song, bpm)
            head = f"song '{stored}': {arrangement.strip()}" + (f" (at {bpm} BPM)" if bpm else "")
            return f"{head}\n{_describe_sections(sections)}"
        raise LibraryError(f"nothing saved as '{name}'. Saved: {', '.join(self.library.names()) or 'nothing yet'}")

    def list_library(self) -> str:
        lines = []
        for name in sorted(self.library.patterns, key=str.lower):
            try:
                p = self.library.get_pattern(name)
                lines.append(f"pattern  {name}: {', '.join(t.name for t in p.tracks)} · {p.length} steps · {p.bpm} BPM")
            except NotationError as e:
                lines.append(f"pattern  {name}: (doesn't parse: {e.issues[-1].message})")
        for name in sorted(self.library.songs, key=str.lower):
            song = self.library.songs[name]
            lines.append(f"song     {name}: {song['arrangement'].strip()}")
        return "\n".join(lines) if lines else "nothing saved yet. save_pattern(name, text) stores a pattern"

    def delete(self, name: str) -> str:
        return self.library.delete(name)

    def export_midi(self, what: str, filename: Optional[str] = None, bpm: Optional[int] = None) -> str:
        sections, label, _ = self._sections(what, bpm)
        if not filename:
            filename = re.sub(r"[^\w\-]+", "_", label)[:60].strip("_") or "pattern"
        if not filename.endswith(".mid"):
            filename += ".mid"
        out_dir = self.library.home / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / Path(filename).name
        to_midi_file(sections, self.channel).save(str(path))
        return f"wrote {path} ({total_seconds(sections):.1f}s)"

    # -- kit ----------------------------------------------------------------

    def show_kit(self) -> str:
        aliases = self.library.effective_aliases()
        lines = ["pad      note  factory Project 1 sound   aliases"]
        for row in device.kit_rows(aliases):
            lines.append(f"{row['pad']:<8} {row['note']:<5} {(row['project_1_sound'] or '-'):<25} {', '.join(row['aliases'])}")
        pitched = sorted(f"{n} → {t}" for n, t in aliases.items() if parse_target(t) and parse_target(t).pitched)
        if pitched:
            lines.append("pitched aliases: " + ", ".join(pitched))
        custom = sorted(self.library.aliases)
        if custom:
            lines.append("your aliases: " + ", ".join(f"{n} → {self.library.aliases[n]}" for n in custom))
        lines.append("Sounds are the factory Project 1 layout as transcribed by the community; "
                     "if your pads differ, use set_alias(name, pad).")
        return "\n".join(lines)

    def set_alias(self, name: str, target: str) -> str:
        stored = self.library.set_alias(name, target)
        return f"'{name.lower()}' now plays {stored}"

    def remove_alias(self, name: str) -> str:
        return self.library.remove_alias(name)

    def audition(self, sound: str, velocity: int = 100, note: Optional[str] = None) -> str:
        """Play one hit so you can hear what a name/pad is. For channel targets, `note` picks the pitch."""
        self._require_port()
        if not 1 <= velocity <= 127:
            raise ValueError("velocity must be 1-127")
        pitch_line = f"{sound} notes: {note or 'C3'}\n" if note or _is_pitched(self, sound) else ""
        text = f"@bpm 120\n{sound}: x---\n{pitch_line}"
        pattern = self.library.parse(text)
        pattern.tracks[0].steps[0] = velocity
        self.player.play([layer([(sound, pattern)])], self.channel, False, sound)
        target = pattern.tracks[0].target
        where = target.label if target.pitched else f"{target.label} (note {target.note})"
        return f"played {sound} → {where}" + (f" at {note_name(pattern.tracks[0].notes[0][0])}" if target.pitched else "")


def _is_pitched(studio: "Studio", sound: str) -> bool:
    target = parse_target(studio.library.effective_aliases().get(sound.lower(), sound))
    return bool(target and target.pitched)


def _describe_sections(sections: List[Section]) -> str:
    """Collapse consecutive identical sections: 'verse ×4 (16 beats @ 96 BPM)'."""
    lines = []
    i = 0
    while i < len(sections):
        j = i
        while j + 1 < len(sections) and sections[j + 1] is sections[i]:
            j += 1
        s = sections[i]
        count = j - i + 1
        lines.append(f"  {s.label}" + (f" ×{count}" if count > 1 else "") +
                     f"  ({s.length_beats} beats @ {s.bpm} BPM)")
        i = j + 1
    lines.append(f"total {total_seconds(sections):.1f}s")
    return "\n".join(lines)
