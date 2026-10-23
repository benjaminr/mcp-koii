"""
Back up the EP-133: every sample (as WAV, checked against the device's CRC-32)
with its metadata, plus every project archive.

A backup is a folder:

    2026-10-23-1105/
      manifest.json         device, date, every sound's metadata and checksum, projects
      sounds/001 micro kick.wav ...
      projects/01.tar ...

Backups are incremental: a sample whose checksum matches the most recent
backup is copied from there instead of being read from the device again
(reading runs at roughly 25 KB/s, so a full first backup takes a while).
A folder only counts as a backup once its manifest says it's complete.
"""

import json
import re
import shutil
import threading
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from koii.files import DeviceFiles, Sound, pcm_to_wav

MANIFEST = "manifest.json"
FORMAT_VERSION = 1


@dataclass
class Progress:
    stage: str            # "listing", "sounds", "projects", "done", "failed", "cancelled"
    done: int = 0
    total: int = 0
    message: str = ""
    bytes_read: int = 0
    reused: int = 0


@dataclass
class BackupResult:
    path: Path
    sounds: int
    projects: int
    bytes_read: int
    reused: int
    seconds: float
    errors: List[str] = field(default_factory=list)


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\- .]+", "_", name).strip(" .")[:40] or "sound"


def sound_filename(sound: Sound) -> str:
    return f"{sound.slot:03d} {_safe_name(sound.name)}.wav"


def latest_backup(root: Path) -> Optional[Path]:
    """The newest folder under `root` whose manifest says it's complete."""
    if not root.exists():
        return None
    for folder in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        try:
            if json.loads((folder / MANIFEST).read_text()).get("complete"):
                return folder
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _reusable(previous: Optional[Path]) -> Dict[int, Dict]:
    """slot -> manifest entry from the previous complete backup."""
    if previous is None:
        return {}
    manifest = json.loads((previous / MANIFEST).read_text())
    return {entry["slot"]: {**entry, "folder": previous} for entry in manifest.get("sounds", [])}


def backup_device(client: DeviceFiles, root: Path, progress: Callable[[Progress], None] = lambda p: None,
                  cancel: Optional[threading.Event] = None, clock: Callable[[], float] = time.monotonic) -> BackupResult:
    """Copy everything off the device into a new folder under `root`. Read-only on the device."""
    cancel = cancel or threading.Event()
    started = clock()
    folder = root / time.strftime("%Y-%m-%d-%H%M%S")
    (folder / "sounds").mkdir(parents=True)
    (folder / "projects").mkdir()
    previous = _reusable(latest_backup(root))
    manifest: Dict = {"format": FORMAT_VERSION, "device": "EP-133", "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                      "complete": False, "sounds": [], "projects": []}
    result = BackupResult(path=folder, sounds=0, projects=0, bytes_read=0, reused=0, seconds=0)

    def save_manifest() -> None:
        (folder / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True))

    progress(Progress("listing", message="listing the sample library"))
    sounds = client.list_sounds(with_metadata=True)
    for index, sound in enumerate(sounds, start=1):
        if cancel.is_set():
            progress(Progress("cancelled", index - 1, len(sounds), "backup cancelled; it isn't complete"))
            save_manifest()
            result.seconds = clock() - started
            return result
        filename = sound_filename(sound)
        earlier = previous.get(sound.slot)
        if earlier and sound.crc is not None and earlier.get("crc") == sound.crc:
            shutil.copy2(earlier["folder"] / "sounds" / earlier["file"], folder / "sounds" / filename)
            result.reused += 1
        else:
            pcm, sound = client.read_sound(sound.slot)
            (folder / "sounds" / filename).write_bytes(pcm_to_wav(pcm, sound.sample_rate, sound.channels))
            result.bytes_read += len(pcm)
        manifest["sounds"].append({"slot": sound.slot, "name": sound.name, "file": filename, "bytes": sound.bytes,
                                   "crc": sound.crc, "metadata": sound.metadata})
        result.sounds += 1
        progress(Progress("sounds", index, len(sounds), f"{sound.slot:03d} {sound.name}",
                          result.bytes_read, result.reused))
        if index % 25 == 0:
            save_manifest()

    projects = client.list_projects()
    for index, project in enumerate(projects, start=1):
        if cancel.is_set():
            break
        data, info = client.read_project(project["id"])
        name = f"{_safe_name(project['name'] or str(project['id']))}.tar"
        (folder / "projects" / name).write_bytes(data)
        manifest["projects"].append({"id": project["id"], "name": project["name"], "file": name,
                                     "bytes": len(data), "crc": zlib.crc32(data)})
        result.projects += 1
        result.bytes_read += len(data)
        progress(Progress("projects", index, len(projects), f"project {project['name']}", result.bytes_read, result.reused))

    manifest["complete"] = not cancel.is_set()
    save_manifest()
    result.seconds = clock() - started
    stage = "done" if manifest["complete"] else "cancelled"
    progress(Progress(stage, result.sounds, len(sounds),
                      f"{result.sounds} sounds and {result.projects} projects in {folder}", result.bytes_read, result.reused))
    return result
