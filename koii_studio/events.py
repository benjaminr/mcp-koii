"""
A small thread-safe publish/subscribe bus.

The player, the studio and the MCP tools publish events (notes, playback
passes, library changes, activity); the visualiser streams them to browsers.
"""

import queue
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Set

# Event types kept for clients that connect later. Notes are too frequent and too
# short-lived to be worth replaying.
_REMEMBERED_TYPES = {"activity", "connection"}
_MAX_ARGUMENT_CHARS = 5000


class EventBus:
    def __init__(self, history: int = 100, queue_size: int = 2000):
        self._lock = threading.Lock()
        self._subscribers: Set[queue.Queue] = set()
        self._history: Deque[Dict[str, Any]] = deque(maxlen=history)
        self._queue_size = queue_size
        self._current_pass: Optional[Dict[str, Any]] = None

    def publish(self, event_type: str, **data: Any) -> Dict[str, Any]:
        event = {"type": event_type, "time": time.time(), **data}
        with self._lock:
            if event_type in _REMEMBERED_TYPES:
                self._history.append(event)
            if event_type == "pass":
                self._current_pass = event
            elif event_type == "stopped":
                self._current_pass = None
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                pass  # a stalled client loses events rather than blocking playback
        return event

    def activity(self, source: str, action: str, arguments: Optional[Dict[str, Any]] = None,
                 result: Optional[str] = None, error: Optional[str] = None) -> Dict[str, Any]:
        """Record something a person or Claude did, e.g. source='claude', action='play'."""
        return self.publish(
            "activity",
            source=source,
            action=action,
            arguments=_trim_arguments(arguments or {}),
            result=result,
            error=error,
        )

    def subscribe(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue(maxsize=self._queue_size)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def recent(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._history)

    def current_pass(self) -> Optional[Dict[str, Any]]:
        """The pass playing now, so a page opened mid-loop can show it straight away."""
        with self._lock:
            return self._current_pass


def _trim_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    trimmed = {}
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > _MAX_ARGUMENT_CHARS:
            value = value[:_MAX_ARGUMENT_CHARS] + "…"
        trimmed[key] = value
    return trimmed
