"""
Background MIDI playback with drift-free timing, looping and seamless switching.

Events are scheduled against absolute monotonic times (not sleep-per-step), so
timing errors don't accumulate. Playback runs on its own thread so the MCP
server stays responsive: you can keep talking, queue the next pattern, or stop.
"""

import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Set, Tuple

import mido

from koii.sequence import Section, timeline

_SPIN_SECONDS = 0.002  # sleep until this close to an event, then spin for precision


@dataclass
class _Program:
    label: str
    events: List[Tuple[float, mido.Message]]
    duration: float
    loop: bool


class Player:
    def __init__(self, send: Callable[[mido.Message], None], clock: Callable[[], float] = time.perf_counter):
        self._send = send
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._current: Optional[_Program] = None
        self._pending: Optional[_Program] = None
        self._active: Set[Tuple[int, int]] = set()
        self._cycle_start = 0.0
        self._cycles = 0

    # -- public API ---------------------------------------------------------

    def play(self, sections: List[Section], default_channel: int, loop: bool, label: str) -> str:
        """
        Start playing. If something is looping, the new material replaces it at the
        end of the current pass (seamless switch) and keeps looping; otherwise it
        starts now.
        """
        events, duration = timeline(sections, default_channel)
        program = _Program(label=label, events=events, duration=duration, loop=loop)
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            if running and self._current is not None and self._current.loop:
                program.loop = True
                self._pending = program
                remaining = self._cycle_start + self._current.duration - self._clock()
                return f"queued '{label}' to start when the current loop of '{self._current.label}' ends (in {max(0.0, remaining):.1f}s)"
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
        if msg.type == "note_on" and msg.velocity > 0:
            self._active.add(key)
        else:
            self._active.discard(key)
        self._send(msg)

    def _release_all(self) -> None:
        for channel, note in sorted(self._active):
            self._send(mido.Message("note_off", note=note, velocity=0, channel=channel))
        self._active.clear()

    def _run(self) -> None:
        start = self._clock()
        try:
            while True:
                with self._lock:
                    program = self._current
                    self._cycle_start = start
                if program is None:
                    return
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
