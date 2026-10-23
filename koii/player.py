"""
Background MIDI playback with drift-free timing, looping and seamless switching.

Events are scheduled against absolute monotonic times (not sleep-per-step), so
timing errors don't accumulate. Playback runs on its own thread so the MCP
server stays responsive: you can keep talking, queue the next pattern, or stop.

The optional `notify(event_type, **data)` callback reports what's happening
(notes, the start of each pass, stops) for the visualiser.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import mido

from koii.sequence import Section, timeline

_SPIN_SECONDS = 0.002  # sleep until this close to an event, then spin for precision

Notify = Callable[..., Any]


def _ignore(event_type: str, **data: Any) -> None:
    pass


@dataclass
class _Program:
    label: str
    events: List[Tuple[float, mido.Message]]
    duration: float
    loop: bool
    info: Dict[str, Any] = field(default_factory=dict)


class Player:
    def __init__(self, send: Callable[[mido.Message], None], clock: Callable[[], float] = time.perf_counter,
                 notify: Optional[Notify] = None):
        self._send = send
        self._clock = clock
        self._notify = notify or _ignore
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._current: Optional[_Program] = None
        self._pending: Optional[_Program] = None
        self._active: Set[Tuple[int, int]] = set()
        self._cycle_start = 0.0
        self._cycles = 0

    # -- public API ---------------------------------------------------------

    def play(self, sections: List[Section], default_channel: int, loop: bool, label: str,
             info: Optional[Dict[str, Any]] = None) -> str:
        """
        Start playing. If something is looping, the new material replaces it at the
        end of the current pass (seamless switch) and keeps looping; otherwise it
        starts now. `info` is passed through to pass notifications.
        """
        events, duration = timeline(sections, default_channel)
        program = _Program(label=label, events=events, duration=duration, loop=loop, info=info or {})
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            queued_behind = self._current if running and self._current is not None and self._current.loop else None
            if queued_behind:
                program.loop = True
                self._pending = program
                remaining = max(0.0, self._cycle_start + queued_behind.duration - self._clock())
        if queued_behind:
            self._notify("queued", label=label, starts_in=remaining)
            return f"queued '{label}' to start when the current loop of '{queued_behind.label}' ends (in {remaining:.1f}s)"
        self.stop()
        with self._lock:
            self._current = program
            self._pending = None
            self._stop.clear()
            self._cycles = 0
            self._thread = threading.Thread(target=self._run, name="koii-player", daemon=True)
            self._thread.start()
        return f"playing '{label}'" + (" on loop" if loop else f" ({duration:.1f}s)")

    def stop(self) -> bool:
        """Stop immediately and release any sounding notes. Returns True if something was playing."""
        thread = self._thread
        if thread is None or not thread.is_alive():
            return False
        self._stop.set()
        thread.join(timeout=2.0)
        return True

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until playback finishes (for non-looping playback and tests)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    @property
    def status(self) -> Optional[str]:
        with self._lock:
            if self._current is None or self._thread is None or not self._thread.is_alive():
                return None
            text = f"'{self._current.label}'"
            if self._current.loop:
                text += f" looping (pass {self._cycles + 1})"
            else:
                remaining = self._cycle_start + self._current.duration - self._clock()
                text += f" ({max(0.0, remaining):.1f}s left)"
            if self._pending:
                text += f", then '{self._pending.label}'"
            return text

    # -- playback thread ----------------------------------------------------

    def _wait_until(self, target: float) -> bool:
        """Wait until `target` on the clock. Returns False if stop was requested."""
        while True:
            remaining = target - self._clock()
            if remaining <= 0:
                return not self._stop.is_set()
            if remaining > _SPIN_SECONDS:
                if self._stop.wait(min(remaining - _SPIN_SECONDS, 0.05)):
                    return False
            elif self._stop.is_set():
                return False

    def _emit(self, msg: mido.Message) -> None:
        key = (msg.channel, msg.note)
        is_on = msg.type == "note_on" and msg.velocity > 0
        if is_on:
            self._active.add(key)
        else:
            self._active.discard(key)
        self._send(msg)
        self._notify("note", on=is_on, note=msg.note, channel=msg.channel + 1, velocity=msg.velocity)

    def _release_all(self) -> None:
        for channel, note in sorted(self._active):
            self._send(mido.Message("note_off", note=note, velocity=0, channel=channel))
            self._notify("note", on=False, note=note, channel=channel + 1, velocity=0)
        self._active.clear()

    def _announce_pass(self, program: _Program, start: float) -> None:
        # Convert the monotonic start time to wall-clock time, which browsers share.
        started_at = time.time() - (self._clock() - start)
        self._notify("pass", label=program.label, started_at=started_at, duration=program.duration,
                     loop=program.loop, number=self._cycles + 1, info=program.info)

    def _run(self) -> None:
        start = self._clock()
        try:
            while True:
                with self._lock:
                    program = self._current
                    self._cycle_start = start
                if program is None:
                    return
                self._announce_pass(program, start)
                for at, msg in program.events:
                    if not self._wait_until(start + at):
                        return
                    self._emit(msg)
                if not self._wait_until(start + program.duration):
                    return
                start += program.duration
                with self._lock:
                    if self._pending is not None:
                        self._current, self._pending = self._pending, None
                        self._cycles = 0
                    elif program.loop:
                        self._cycles += 1
                    else:
                        self._current = None
                        return
        finally:
            self._release_all()
            with self._lock:
                self._current = None
                self._pending = None
            self._notify("stopped")
