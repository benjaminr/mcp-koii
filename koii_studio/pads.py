"""
The EP-133's pads, set over USB: which sound a pad plays, its MIDI channel, play mode,
level, envelope and pan. Changes take effect straight away (tested on OS 2.5).

Each pad is a node in the device's file tree, and its settings are a small JSON object
that can be read and merged into, like a sample's. Every change here is read back and
checked, and recorded in ~/.koii-studio/pad-changes.json so the last one can be undone.

Pads belong to a project: these act on the project that's open on the device. Setting a
pad's channel is what lets a melodic part play it (see DEVICE.md): give the chords pad
channel 3, and a pattern track on ch3 plays it at any pitch.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from koii_studio.events import EventBus
from koii_studio.files import PROJECTS_NODE, DeviceFiles, Rejected

GROUPS = "ABCD"
# The pad keys in note order, lowest first: "." plays the group's first note.
PAD_KEYS = (".", "0", "Enter", "1", "2", "3", "4", "5", "6", "7", "8", "9")
# The file tree numbers a group's pads from the top row of the keypad down.
NODE_NUMBER = {"7": 1, "8": 2, "9": 3, "4": 4, "5": 5, "6": 6, "1": 7, "2": 8, "3": 9, ".": 10, "0": 11, "Enter": 12}
FIRST_PROJECT_NODE = 3000
NODES_PER_PROJECT = 1000
FIRST_PAD_NODE = 200          # within a project: group A's pads start at +200, B at +300 …
NODES_PER_GROUP = 100

PLAY_MODES = ("oneshot", "key", "legato")
# The device wants a release with every play-mode change. When none is given, a new mode
# gets these: 255 plays a one-shot through; key and legato fade out after note-off.
DEFAULT_RELEASE = {"oneshot": 255, "key": 128, "legato": 128}

# Friendly setting -> (device key, lowest, highest)
RANGES = {
    "channel": ("midi.channel", 0, 16),
    "level": ("sound.amplitude", 0, 100),
    "attack": ("envelope.attack", 0, 255),
    "release": ("envelope.release", 0, 255),
    "pan": ("sound.pan", -16, 16),
}
SETTINGS = ("sound", "channel", "mode", *[name for name in RANGES if name != "channel"])
HISTORY_LIMIT = 200
SETTLE_SECONDS = 0.3   # let the device apply a change before reading it back
PROJECT_SETTLE_SECONDS = 6.0   # the protocol notes warn that playing straight after a switch can misbehave
PROJECT_COUNT = 9
GROUPS_NODE_OFFSET = 100       # within a project: the groups folder, whose 'active' is the selected group


class PadError(ValueError):
    """A pad name or setting that can't be used, or a change the device didn't keep."""


@dataclass(frozen=True)
class Pad:
    group: str   # "A" … "D"
    key: str     # one of PAD_KEYS

    @property
    def label(self) -> str:
        return f"{self.group}{self.key}"

    def node(self, project: int) -> int:
        return group_node(project, self.group) + NODE_NUMBER[self.key]


def project_node(project: int) -> int:
    """The project's folder in the device's file tree: 3000 for project 1, 4000 for 2 …"""
    return FIRST_PROJECT_NODE + (project - 1) * NODES_PER_PROJECT


def group_node(project: int, group: str) -> int:
    """A group's folder: its pads are this plus 1–12."""
    return project_node(project) + FIRST_PAD_NODE + GROUPS.index(group) * NODES_PER_GROUP


def parse_pad(text: str) -> Pad:
    """'D1', 'a.', 'BEnter' or 'BE' -> Pad. Groups A–D; keys . 0 Enter 1–9."""
    cleaned = str(text).strip()
    if len(cleaned) >= 2 and cleaned[0].upper() in GROUPS:
        key = cleaned[1:]
        if key.lower() in ("enter", "e", "ent"):
            key = "Enter"
        if key in PAD_KEYS:
            return Pad(cleaned[0].upper(), key)
    raise PadError(f"'{text}' isn't a pad. Pads are a group A–D and a key: A. A0 AEnter A1 … A9 (e.g. D1)")


def all_pads(group: Optional[str] = None) -> List[Pad]:
    groups = [group.upper()] if group else list(GROUPS)
    for name in groups:
        if name not in GROUPS:
            raise PadError(f"groups are A–D, not '{group}'")
    return [Pad(name, key) for name in groups for key in PAD_KEYS]


def describe(pad: Pad, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """A pad's settings in koii studio's words: sound slot (None if empty), channel (None if it has none) …"""
    sound = metadata.get("sym") or None
    channel = metadata.get("midi.channel") or None
    return {
        "pad": pad.label,
        "sound": sound,
        "channel": channel,
        "mode": metadata.get("sound.playmode") if sound else None,
        "level": metadata.get("sound.amplitude") if sound else None,
        "attack": metadata.get("envelope.attack") if sound else None,
        "release": metadata.get("envelope.release") if sound else None,
        "pan": metadata.get("sound.pan") if sound else None,
    }


def changes_for(settings: Dict[str, Any], current: Dict[str, Any], sound_frames: Optional[int] = None) -> Dict[str, Any]:
    """
    Turn friendly settings into the device keys to write.

    sound: a slot 1–999 (its playback region is reset to the whole sample, as the device
    needs when a pad changes sample), or 0 to empty the pad. channel: 1–16, or None / 0 / "none" for no channel of
    its own. mode: oneshot / key / legato (written with a release, as the device requires).
    level 0–100, attack and release 0–255, pan −16 (left) … 16 (right).
    """
    unknown = sorted(set(settings) - set(SETTINGS))
    if unknown:
        raise PadError(f"unknown pad setting {', '.join(unknown)}; use {', '.join(SETTINGS)}")
    changes: Dict[str, Any] = {}
    if settings.get("sound") == 0:
        changes["sym"] = 0
    elif "sound" in settings:
        slot = settings["sound"]
        if not isinstance(slot, int) or not 1 <= slot <= 999:
            raise PadError(f"sound must be a sample slot 1–999, not {slot!r}")
        if not sound_frames:
            raise PadError(f"slot {slot} is empty, so a pad can't play it")
        changes.update({"sym": slot, "sample.start": 0, "sample.end": sound_frames})
    for name, (key, low, high) in RANGES.items():
        if name not in settings:
            continue
        value = settings[name]
        if name == "channel" and value in (None, "none", "off"):
            value = 0
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            shown = "1–16, or none" if name == "channel" else f"{low}–{high}"
            raise PadError(f"{name} must be {shown}, not {value!r}")
        changes[key] = value
    if "mode" in settings:
        mode = settings["mode"]
        if mode not in PLAY_MODES:
            raise PadError(f"mode must be {', '.join(PLAY_MODES)}, not {mode!r}")
        changes["sound.playmode"] = mode
        if "envelope.release" not in changes:
            keep = current.get("envelope.release")
            changes["envelope.release"] = keep if current.get("sound.playmode") == mode and keep is not None \
                else DEFAULT_RELEASE[mode]
    elif "envelope.release" in changes and current.get("sound.playmode"):
        # The device takes a release with its play mode, so send the current one alongside.
        changes["sound.playmode"] = current["sound.playmode"]
    if not changes:
        raise PadError("nothing to change: give sound, channel, mode, level, attack, release or pan")
    return changes


class PadEditor:
    def __init__(self, events: EventBus, home: Path, client: Optional[DeviceFiles] = None,
                 names: Optional[Callable[[], Dict[int, str]]] = None):
        """names() gives the sample names by slot, so pads can say what they play."""
        self.events = events
        self.history_path = home / "pad-changes.json"
        self.client = client or DeviceFiles()
        self.names = names or (lambda: {})

    # -- reading ----------------------------------------------------------------------

    def active_project(self) -> int:
        with self.client.session("pads: active project") as session:
            return _active_project(session)

    def open_project(self, project: int) -> Dict[str, Any]:
        """
        Open another project on the EP-133 (1–9), as TE's Sample Tool does: set it as the
        active project, check the device took it, then select its group A and first pad.
        """
        if not isinstance(project, int) or not 1 <= project <= PROJECT_COUNT:
            raise PadError(f"projects are 1–{PROJECT_COUNT}, not {project!r}")
        group_a = group_node(project, "A")
        with self.client.session("pads: open project") as session:
            previous = _active_project(session)
            if previous != project:
                session.preflight()
                session.set_metadata(PROJECTS_NODE, {"active": project_node(project)})
                time.sleep(SETTLE_SECONDS)
                if _active_project(session) != project:
                    raise PadError(f"the EP-133 stayed on project {previous}")
                session.set_metadata(project_node(project) + GROUPS_NODE_OFFSET, {"active": group_a})   # group A
                session.set_metadata(group_a, {"active": group_a + 1})                                  # its first pad
        if previous != project:
            time.sleep(PROJECT_SETTLE_SECONDS)
        self.events.publish("project", project=project, previous=previous)
        message = f"project {project} is open" + (f" (was {previous})" if previous != project else " already")
        return {"project": project, "previous": previous, "message": message}

    def get(self, group: Optional[str] = None, pad: Optional[str] = None) -> Dict[str, Any]:
        """The settings of one pad, one group, or all 48, in the open project."""
        pads = [parse_pad(pad)] if pad else all_pads(group)
        with self.client.session("pads: read") as session:
            project = _active_project(session)
            settings = [describe(each, session.metadata(each.node(project))) for each in pads]
        names = self.names()
        for each in settings:
            each["name"] = names.get(each["sound"]) if each["sound"] else None
        return {"project": project, "pads": settings}

    # -- changing -----------------------------------------------------------------------

    def set(self, pad: str, **settings: Any) -> Dict[str, Any]:
        """Change one pad in the open project, check the device kept it, and record it for undo."""
        target = parse_pad(pad)
        settings = {key: value for key, value in settings.items() if value is not None}   # None: leave as it is
        with self.client.session("pads: change") as session:
            project = _active_project(session)
            node = target.node(project)
            before = session.metadata(node)
            frames = _sound_frames(session, settings["sound"]) if settings.get("sound") else None
            changes = changes_for(settings, before, frames)
            session.preflight()
            session.set_metadata(node, changes)
            time.sleep(SETTLE_SECONDS)
            after = session.metadata(node)
        missed = {key: (value, after.get(key)) for key, value in changes.items() if after.get(key) != value}
        self._record(project, target, before, after, changes)
        self.events.publish("pad", pad=target.label, project=project, settings=describe(target, after))
        if missed:
            raise PadError(f"the device didn't keep {target.label}'s " +
                           ", ".join(f"{key} (asked {asked}, got {got})" for key, (asked, got) in missed.items()))
        return {"project": project, "pad": target.label, "before": describe(target, before),
                "after": describe(target, after), "message": _summary(target, before, after)}

    def undo(self) -> Dict[str, Any]:
        """Put back the pad changed most recently, as it was before that change."""
        history = self._history()
        if not history:
            raise PadError("no pad changes to undo")
        last = history[-1]
        target = parse_pad(last["pad"])
        restore = {key: last["before"].get(key) for key in last["changes"] if key in last["before"]}
        if "sound.playmode" in restore and restore.get("envelope.release") is None:
            restore["envelope.release"] = last["before"].get("envelope.release", DEFAULT_RELEASE["oneshot"])
        with self.client.session("pads: undo") as session:
            if _active_project(session) != last["project"]:
                raise PadError(f"the last change was to project {last['project']}; open it on the device to undo it")
            node = target.node(last["project"])
            session.preflight()
            session.set_metadata(node, restore)
            time.sleep(SETTLE_SECONDS)
            after = session.metadata(node)
        self._save_history(history[:-1])
        self.events.publish("pad", pad=target.label, project=last["project"], settings=describe(target, after))
        return {"pad": target.label, "after": describe(target, after),
                "message": f"put {target.label} back: " + _settings_text(describe(target, after))}

    # -- history --------------------------------------------------------------------------

    def _history(self) -> List[Dict[str, Any]]:
        try:
            return json.loads(self.history_path.read_text())
        except (OSError, json.JSONDecodeError):
            return []

    def _save_history(self, history: List[Dict[str, Any]]) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(json.dumps(history[-HISTORY_LIMIT:], indent=1))

    def _record(self, project: int, pad: Pad, before: Dict, after: Dict, changes: Dict) -> None:
        history = self._history()
        history.append({"when": datetime.now(timezone.utc).isoformat(timespec="seconds"), "project": project,
                        "pad": pad.label, "changes": changes, "before": before, "after": after})
        self._save_history(history)


def _active_project(session) -> int:
    active = session.metadata(PROJECTS_NODE).get("active")
    if not isinstance(active, int) or active < FIRST_PROJECT_NODE:
        raise PadError("couldn't tell which project is open on the EP-133")
    return (active - FIRST_PROJECT_NODE) // NODES_PER_PROJECT + 1


def _sound_frames(session, slot: Any) -> Optional[int]:
    """How many frames a slot's sample has, or None if the slot is empty."""
    if not isinstance(slot, int) or not 1 <= slot <= 999:
        return None
    try:
        size = session.stat(slot)["size"]
        channels = session.metadata(slot).get("channels") or 1
    except Rejected:
        return None
    return size // (2 * channels) or None


def _settings_text(settings: Dict[str, Any]) -> str:
    if not settings["sound"]:
        return "empty" + (f", channel {settings['channel']}" if settings["channel"] else "")
    parts = [f"sound {settings['sound']}", f"channel {settings['channel'] or 'none'}", settings["mode"],
             f"level {settings['level']}", f"release {settings['release']}"]
    return ", ".join(str(part) for part in parts)


def _summary(pad: Pad, before: Dict, after: Dict) -> str:
    old, new = describe(pad, before), describe(pad, after)
    changed = [f"{name} {old[name]} → {new[name]}" for name in ("sound", "channel", "mode", "level", "attack", "release", "pan")
               if old[name] != new[name]]
    return f"{pad.label}: " + (", ".join(changed) if changed else "already set like that") + \
           f"\n  now: {_settings_text(new)}"
