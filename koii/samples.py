"""
The EP-133's sample library as koii sees it: a cached listing, downloads,
auditions, and backups running in the background with progress events.

All device file traffic goes through koii.files, one locked session at a time.
"""

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from koii.backup import BackupResult, Progress, backup_device, latest_backup
from koii.events import EventBus
from koii.files import DeviceFileError, DeviceFiles, Sound, pcm_to_wav
from koii.notation import note_name

logger = logging.getLogger(__name__)

SLOT_COUNT = 999


def describe_sound(sound: Sound) -> Dict[str, Any]:
    meta = sound.metadata
    root = meta.get("sound.rootnote")
    return {
        "slot": sound.slot, "name": sound.name, "bytes": sound.bytes, "seconds": round(sound.seconds, 3),
        "channels": sound.channels, "samplerate": sound.sample_rate,
        "root": note_name(int(root)) if isinstance(root, (int, float)) and 0 <= root <= 127 else None,
        "playmode": meta.get("sound.playmode"), "crc": sound.crc,
    }


class DeviceLibrary:
    def __init__(self, events: EventBus, home: Path, client: Optional[DeviceFiles] = None):
        self.events = events
        self.backups = home / "backups"
        self.client = client or DeviceFiles()
        self._sounds: Optional[List[Sound]] = None
        self._job: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._progress: Optional[Progress] = None
        self._last_result: Optional[BackupResult] = None

    # -- reading ----------------------------------------------------------------------

    def sounds(self, refresh: bool = False) -> List[Sound]:
        if self._sounds is None or refresh:
            self._sounds = self.client.list_sounds(with_metadata=True)
            self.events.publish("samples", stage="listed", count=len(self._sounds))
        return self._sounds

    def listing(self, refresh: bool = False) -> Dict[str, Any]:
        sounds = self.sounds(refresh)
        return {
            "sounds": [describe_sound(s) for s in sounds],
            "occupied": len(sounds), "empty": SLOT_COUNT - len(sounds),
            "bytes": sum(s.bytes for s in sounds),
        }

    def wav(self, slot: int) -> tuple:
        """(WAV bytes, name) for a slot, read from the device and checked against its CRC."""
        pcm, sound = self.client.read_sound(slot)
        return pcm_to_wav(pcm, sound.sample_rate, sound.channels), sound.name

    def audition(self, slot: int) -> str:
        self.client.audition(slot)
        return f"playing slot {slot} on the EP-133"

    def summary(self, query: Optional[str] = None, limit: int = 60) -> str:
        """A text listing for Claude: occupied slots, optionally filtered by name."""
        listing = self.listing()
        sounds = listing["sounds"]
        if query:
            sounds = [s for s in sounds if query.lower() in s["name"].lower()]
        lines = [f"{listing['occupied']} sounds, {listing['empty']} empty slots, "
                 f"{listing['bytes'] / 1e6:.1f} MB of audio" + (f"; {len(sounds)} match '{query}'" if query else "")]
        for s in sounds[:limit]:
            extras = " · ".join(x for x in (f"root {s['root']}" if s["root"] else "", s["playmode"] or "",
                                            "stereo" if s["channels"] == 2 else "") if x)
            lines.append(f"  {s['slot']:>3}  {s['name']:<20} {s['seconds']:.2f}s" + (f"  {extras}" if extras else ""))
        if len(sounds) > limit:
            lines.append(f"  … and {len(sounds) - limit} more (narrow it with a search)")
        return "\n".join(lines)

    # -- backups --------------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._job is not None and self._job.is_alive()

    def start_backup(self) -> str:
        if self.busy:
            return "a backup is already running"
        self._cancel.clear()
        self._progress = Progress("starting")
        self._job = threading.Thread(target=self._run_backup, name="koii-backup", daemon=True)
        self._job.start()
        previous = latest_backup(self.backups)
        note = f"; unchanged samples are copied from {previous.name}" if previous else \
            " (the first one reads everything, roughly 20 minutes for 30 MB)"
        return f"backup started in the background{note}. Progress shows in the visualiser and in status()"

    def cancel_backup(self) -> str:
        if not self.busy:
            return "no backup is running"
        self._cancel.set()
        return "cancelling the backup after the current sample"

    def _run_backup(self) -> None:
        def report(progress: Progress) -> None:
            self._progress = progress
            self.events.publish("backup", stage=progress.stage, done=progress.done, total=progress.total,
                                message=progress.message, bytes_read=progress.bytes_read, reused=progress.reused)
        try:
            self._last_result = backup_device(self.client, self.backups, report, self._cancel)
        except DeviceFileError as error:
            report(Progress("failed", message=str(error)))
        except Exception as error:  # keep the server alive; say what broke
            logger.exception("backup failed")
            report(Progress("failed", message=f"{type(error).__name__}: {error}"))

    def backup_status(self) -> Dict[str, Any]:
        progress = self._progress
        latest = latest_backup(self.backups)
        return {
            "running": self.busy,
            "stage": progress.stage if progress else None,
            "done": progress.done if progress else 0,
            "total": progress.total if progress else 0,
            "message": progress.message if progress else "",
            "latest": str(latest) if latest else None,
        }

    def backup_status_text(self) -> str:
        status = self.backup_status()
        if status["running"]:
            return f"backup running: {status['stage']} {status['done']}/{status['total']} {status['message']}"
        latest = f"latest complete backup: {status['latest']}" if status["latest"] else "no complete backup yet"
        last = f"last run: {status['stage']}, {status['message']}" if status["stage"] else ""
        return "; ".join(x for x in (latest, last) if x)
