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
from typing import Any, Callable, Dict, List, Optional

import mido

from koii import device
from koii.events import EventBus
from koii.library import Library, LibraryError
from koii.notation import (
    NotationError, looks_like_pattern, note_name, parse_target, pattern_to_dict, render_pattern,
)
from koii.player import Player
from koii.sequence import Section, expand, layer, to_midi_file, total_seconds

logger = logging.getLogger(__name__)

_DEVICE_PORT_HINTS = ("ep-133", "ep133", "k.o", "ko ii", "ko-ii", "koii", "teenage")
_AUDITION_SECONDS = 0.5


SIMULATOR_PORT = "simulator"


class NotConnected(ValueError):
    pass


class SimulatedPort:
    """An output that goes nowhere; the visualiser plays the notes in the browser instead."""
    name = "Browser simulator"

    def send(self, msg: mido.Message) -> None:
        pass

    def close(self) -> None:
        pass


class Studio:
    def __init__(self, library: Optional[Library] = None,
                 open_output: Callable[[str], object] = mido.open_output,
                 list_outputs: Callable[[], List[str]] = mido.get_output_names,
                 open_input: Optional[Callable[..., object]] = mido.open_input,
                 events: Optional[EventBus] = None):
        self.library = library or Library()
        self.events = events or EventBus()
        self._open_output = open_output
        self._list_outputs = list_outputs
        self._open_input = open_input
        self.port = None
        self._input = None
        self.channel = device.DEFAULT_CHANNEL
        self._send_lock = threading.Lock()
        self.player = Player(self._send, notify=self.events.publish)

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

    @property
    def simulated(self) -> bool:
        return isinstance(self.port, SimulatedPort)

    def connection_state(self) -> Dict[str, Any]:
        return {
            "connected": self.port is not None,
            "port": getattr(self.port, "name", None),
            "channel": self.channel,
            "simulated": self.simulated,
            "listening": self._input is not None,
        }

    def connect(self, port: Optional[str] = None, channel: int = device.DEFAULT_CHANNEL) -> str:
        """Connect to the EP-133 (auto-detected), a named MIDI output, or 'simulator' for browser-only sound."""
        if not 1 <= channel <= 16:
            raise ValueError("channel must be 1-16")
        if port and port.lower() == SIMULATOR_PORT:
            self.disconnect()
            self.port = SimulatedPort()
            self.channel = channel
            self.events.publish("connection", **self.connection_state())
            return "connected to the browser simulator; open the visualiser to hear it"
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
        self._listen(name)
        self.events.publish("connection", **self.connection_state())
        return f"connected to '{name}', sending pad hits on MIDI channel {channel}"

    def _listen(self, name: str) -> None:
        """Listen to the device's own MIDI output, so pads pressed by hand show up in the visualiser."""
        if self._open_input is None:
            return
        try:
            self._input = self._open_input(name, callback=self._on_device_message)
        except Exception as e:  # listening is a nice-to-have; never fail the connection over it
            logger.info("not listening to '%s': %s", name, e)
            self._input = None

    def _on_device_message(self, msg: mido.Message) -> None:
        if msg.type in ("note_on", "note_off"):
            self.events.publish("device_note", on=msg.type == "note_on" and msg.velocity > 0,
                                note=msg.note, channel=msg.channel + 1, velocity=msg.velocity)

    def disconnect(self) -> str:
        self.player.stop()
        if self._input is not None:
            try:
                self._input.close()
            except Exception as e:
                logger.info("closing MIDI input: %s", e)
            self._input = None
        with self._send_lock:
            if self.port is None:
                return "not connected"
            name = getattr(self.port, "name", "MIDI port")
            self.port.close()
            self.port = None
        self.events.publish("connection", **self.connection_state())
        return f"disconnected from '{name}'"

    def _require_port(self) -> None:
        if self.port is None:
            raise NotConnected("not connected to a MIDI device. Call connect() first (list_midi_ports() shows what's available)")

    # -- building blocks ----------------------------------------------------

    def _sections(self, what: str, bpm: Optional[int]) -> tuple:
        """
        Resolve pattern text, a saved name, 'a+b', a song or an arrangement into sections.

        Returns (sections, label, pattern summary). The summary is only set for pattern text.
        """
        if looks_like_pattern(what):
            pattern = self.library.parse(what)
            if bpm:
                pattern.bpm = bpm
            return [layer([("pattern", pattern)])], "pattern", render_pattern(pattern)
        sections = expand(what, self.library.get_pattern, self.library.get_song, bpm)
        return sections, what.strip(), ""

    # -- patterns -----------------------------------------------------------

    def check(self, text: str) -> str:
        return "OK\n" + render_pattern(self.library.parse(text))

    def play(self, what: str, repeat: int = 1, loop: bool = False, bpm: Optional[int] = None) -> str:
        if not 1 <= repeat <= 999:
            raise ValueError("repeat must be 1-999")
        sections, label, pattern_summary = self._sections(what, bpm)  # validate before needing a device
        self._require_port()
        played = sections * repeat
        message = self.player.play(played, self.channel, loop, label, info=self.playback_info(played))
        return "\n".join(part for part in (message, pattern_summary, _describe_sections(played)) if part)

    def stop(self) -> str:
        return "stopped" if self.player.stop() else "nothing was playing"

    def save_pattern(self, name: str, text: str) -> str:
        existed = self.library.lookup(name)[0] == "pattern"
        pattern = self.library.save_pattern(name, text)
        self.events.publish("library")
        return f"{'updated' if existed else 'saved'} pattern '{name}'\n{render_pattern(pattern)}"

    def save_song(self, name: str, arrangement: str, bpm: Optional[int] = None) -> str:
        # Validate that everything it references exists before saving.
        sections = expand(arrangement, self.library.get_pattern, self.library.get_song, bpm)
        self.library.save_song(name, arrangement, bpm)
        self.events.publish("library")
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
        result = self.library.delete(name)
        self.events.publish("library")
        return result

    def midi_file(self, what: str, bpm: Optional[int] = None) -> tuple:
        """Build a MIDI file for anything playable. Returns (MidiFile, label, seconds)."""
        sections, label, _ = self._sections(what, bpm)
        return to_midi_file(sections, self.channel), label, total_seconds(sections)

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
        self.events.publish("library")
        return f"'{name.lower()}' now plays {stored}"

    def remove_alias(self, name: str) -> str:
        result = self.library.remove_alias(name)
        self.events.publish("library")
        return result

    def audition(self, sound: str, velocity: int = 100, note: Optional[str] = None) -> str:
        """
        Play one hit so you can hear what a name/pad is. For channel targets, `note` picks the pitch.

        Hits go straight to the device, so auditioning doesn't interrupt a playing loop.
        """
        self._require_port()
        if not 1 <= velocity <= 127:
            raise ValueError("velocity must be 1-127")
        pitch_line = f"{sound} notes: {note or 'C1'}\n" if note or _is_pitched(self, sound) else ""
        track = self.library.parse(f"{sound}: x\n{pitch_line}").tracks[0]
        target = track.target
        if target.pitched:
            for midi_note in track.notes[0]:
                self._hit(midi_note, target.channel, velocity)
            return f"played {sound} → {target.label} at {note_name(track.notes[0][0])}"
        self._hit(target.note, self.channel, velocity)
        return f"played {sound} → {target.label} (note {target.note})"

    def _hit(self, note: int, channel: int, velocity: int, seconds: float = _AUDITION_SECONDS) -> None:
        self._send(mido.Message("note_on", note=note, velocity=velocity, channel=channel - 1))
        self.events.publish("note", on=True, note=note, channel=channel, velocity=velocity)

        def release() -> None:
            self._send(mido.Message("note_off", note=note, velocity=0, channel=channel - 1))
            self.events.publish("note", on=False, note=note, channel=channel, velocity=0)

        timer = threading.Timer(seconds, release)
        timer.daemon = True
        timer.start()

    # -- visualiser data ----------------------------------------------------

    def playback_info(self, sections: List[Section]) -> Dict[str, Any]:
        """
        What's being played, for the visualiser: each distinct section once (with its
        patterns), plus the order they play in. Repeats share the same Section object.
        """
        unique: List[Dict[str, Any]] = []
        order: List[int] = []
        index: Dict[int, int] = {}
        for section in sections:
            if id(section) not in index:
                index[id(section)] = len(unique)
                unique.append({
                    "label": section.label,
                    "bpm": section.bpm,
                    "beats": float(section.length_beats),
                    "seconds": section.seconds,
                    "patterns": [{"name": name, **pattern_to_dict(p)} for name, p in section.patterns],
                })
            order.append(index[id(section)])
        return {"sections": unique, "order": order, "seconds": total_seconds(sections)}

    def check_pattern(self, text: str) -> Dict[str, Any]:
        """Parse pattern text for the visualiser. Raises NotationError like check()."""
        return pattern_to_dict(self.library.parse(text))

    def arrangement_info(self, arrangement: str, bpm: Optional[int] = None) -> Dict[str, Any]:
        sections = expand(arrangement, self.library.get_pattern, self.library.get_song, bpm)
        return self.playback_info(sections)

    def library_state(self) -> Dict[str, Any]:
        patterns = []
        for name in sorted(self.library.patterns, key=str.lower):
            entry: Dict[str, Any] = {"name": name, "text": self.library.patterns[name]["text"]}
            try:
                pattern = self.library.get_pattern(name)
                entry.update(bpm=pattern.bpm, length=pattern.length, beats=float(pattern.length_beats),
                             tracks=[t.name for t in pattern.tracks])
            except NotationError as e:
                entry["error"] = str(e)
            patterns.append(entry)
        songs = [{"name": name, "arrangement": song["arrangement"], "bpm": song.get("bpm")}
                 for name, song in sorted(self.library.songs.items(), key=lambda item: item[0].lower())]
        return {"patterns": patterns, "songs": songs}

    def kit_state(self) -> Dict[str, Any]:
        aliases = self.library.effective_aliases()
        return {"aliases": aliases, "custom": dict(self.library.aliases), "pads": device.kit_rows(aliases)}


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
