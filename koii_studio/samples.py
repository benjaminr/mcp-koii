"""
The EP-133's sample library as koii studio sees it: a cached listing, downloads,
auditions, backups running in the background with progress events, and
uploads.

Upload rules (enforced here, before anything is sent):
- a complete backup must exist;
- the slot must be empty, or hold a sound koii studio uploaded that hasn't changed since
  (it never overwrites or deletes anything else);
- 16-bit audio at 46,875 Hz, mono or stereo, at most MAX_UPLOAD_SECONDS long;
- after writing, the device's CRC-32 of the stored audio must match ours.

All device file traffic goes through koii_studio.files, one locked session at a time.
"""

import json
import logging
import threading
import time
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from koii_studio.backup import BackupResult, Progress, backup_device, latest_backup
from koii_studio.events import EventBus
from koii_studio.files import DEVICE_SAMPLE_RATE, DeviceFileError, DeviceFiles, Sound, clean_sample_name, pcm_to_wav
from koii_studio.notation import note_name

logger = logging.getLogger(__name__)

SLOT_COUNT = 999
MAX_UPLOAD_SECONDS = 20.0
FIRST_SUGGESTED_SLOT = 600   # factory sounds sit below this; suggestions start here


class UploadRefused(DeviceFileError):
    """An upload or delete that koii studio won't do, explained."""


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
        self.uploads_path = home / "uploads.json"
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
        ours = {slot for slot in self.uploads() if self._ours(slot, sounds)}
        return {
            "sounds": [{**describe_sound(s), "ours": s.slot in ours} for s in sounds],
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

    # -- uploads ----------------------------------------------------------------------

    def uploads(self) -> Dict[int, Dict]:
        """Sounds koii studio put on the device: slot -> {name, crc, uploaded}."""
        if not self.uploads_path.exists():
            return {}
        return {int(slot): entry for slot, entry in json.loads(self.uploads_path.read_text()).items()}

    def _record_upload(self, sound: Sound) -> None:
        uploads = self.uploads()
        uploads[sound.slot] = {"name": sound.name, "crc": sound.crc, "uploaded": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        self._save_uploads(uploads)

    def _save_uploads(self, uploads: Dict[int, Dict]) -> None:
        self.uploads_path.parent.mkdir(parents=True, exist_ok=True)
        self.uploads_path.write_text(json.dumps({str(k): v for k, v in sorted(uploads.items())}, indent=2))

    def is_ours(self, slot: int, sounds: Optional[List[Sound]] = None) -> bool:
        """
        True if the slot holds a sound koii studio uploaded and nobody has changed since. Pass a listing
        you've just read to check many slots without reading the device again for each.
        """
        return self._ours(slot, sounds if sounds is not None else self.sounds(refresh=True))

    def _ours(self, slot: int, sounds: List[Sound]) -> bool:
        """True if the slot holds exactly the sound koii studio uploaded there (or left there unfinished)."""
        entry = self.uploads().get(slot)
        current = next((s for s in sounds if s.slot == slot), None)
        if not (entry and current and current.crc is not None):
            return False
        return current.crc in (entry.get("crc"), entry.get("device_crc"))

    def suggest_slot(self, also_taken: Optional[set] = None) -> int:
        """The first empty slot from FIRST_SUGGESTED_SLOT, else the first empty one (also skipping also_taken)."""
        taken = {s.slot for s in self.sounds()} | (also_taken or set())
        for slot in list(range(FIRST_SUGGESTED_SLOT, SLOT_COUNT + 1)) + list(range(1, FIRST_SUGGESTED_SLOT)):
            if slot not in taken:
                return slot
        raise UploadRefused("there are no empty slots on the device")

    def upload(self, slot: int, pcm: bytes, name: str, channels: int = 1,
               settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Upload 16-bit little-endian PCM at 46,875 Hz, following the rules in the module docstring.
        settings is extra sample metadata in the device's own keys (see koii_studio.synth.instrument).
        """
        if latest_backup(self.backups) is None:
            raise UploadRefused("take a backup first (backup_device), so nothing can be lost")
        if self.busy:
            raise UploadRefused("wait for the backup to finish")
        seconds = len(pcm) / (2 * channels * DEVICE_SAMPLE_RATE)
        if seconds > MAX_UPLOAD_SECONDS:
            raise UploadRefused(f"that's {seconds:.1f}s; koii studio uploads at most {MAX_UPLOAD_SECONDS:.0f}s per sound")
        if not pcm:
            raise UploadRefused("there's no audio to upload")
        sounds = self.sounds(refresh=True)
        occupied = next((s for s in sounds if s.slot == slot), None)
        if occupied and not self._ours(slot, sounds):
            raise UploadRefused(f"slot {slot} holds '{occupied.name}', which koii studio didn't put there; choose an empty slot "
                                f"(e.g. {self.suggest_slot()})")
        self.events.publish("upload", stage="writing", slot=slot, name=clean_sample_name(name))

        def progress(done: int, total: int) -> None:
            self.events.publish("upload", stage="writing", slot=slot, done=done, total=total)

        try:
            sound = self.client.upload_sound(slot, pcm, name, channels, progress, settings)
        except DeviceFileError:
            # The audio may already be in the slot even though a later step failed. Mark it as koii studio's
            # (unfinished), so it can be retried or deleted instead of being stranded as someone else's.
            self._sounds = None
            entry = {"name": clean_sample_name(name), "crc": zlib.crc32(pcm), "unfinished": True,
                     "uploaded": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
            try:   # what the device holds now, in case the audio arrived damaged
                entry["device_crc"] = self.client.sound_metadata(slot).get("crc")
            except DeviceFileError:
                pass
            uploads = self.uploads()
            uploads[slot] = entry
            self._save_uploads(uploads)
            raise
        self._record_upload(sound)
        self._sounds = None
        self.events.publish("upload", stage="done", slot=slot, name=sound.name)
        self.events.publish("samples", stage="changed")
        return {**describe_sound(sound), "replaced": bool(occupied),
                "message": f"uploaded '{sound.name}' to slot {slot} ({seconds:.2f}s), checked against the device's "
                           f"checksum. To put it on a pad: press SOUND, choose the pad, then use − / + until the screen shows {slot}"}

    def upload_file(self, path: str, slot: Optional[int] = None, name: Optional[str] = None,
                    keep_stereo: bool = False) -> Dict[str, Any]:
        """Upload a WAV file from disk, converted to the device's format."""
        from koii_studio.audio import wav_for_device
        file = Path(path).expanduser()
        if not file.is_file():
            raise UploadRefused(f"no file at {file}")
        try:
            pcm, channels, seconds = wav_for_device(file, keep_stereo)
        except Exception as error:  # wave raises a few different types for unreadable files
            raise UploadRefused(f"couldn't read {file.name} as a PCM WAV file ({error})") from error
        return self.upload(slot or self.suggest_slot(), pcm, name or file.stem, channels)

    def change_settings(self, slot: int, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Change the sample settings (root, loop, play mode …) of a sound koii studio uploaded."""
        sounds = self.sounds(refresh=True)
        if not self._ours(slot, sounds):
            raise UploadRefused(f"slot {slot} isn't a sound koii studio uploaded; it only changes its own uploads")
        stored = self.client.set_sound_settings(slot, settings)
        self._sounds = None
        self.events.publish("samples", stage="changed")
        return stored

    def delete_upload(self, slot: int) -> str:
        """Delete a sound, but only one koii studio uploaded and that hasn't changed since."""
        sounds = self.sounds(refresh=True)
        if not any(s.slot == slot for s in sounds):
            raise UploadRefused(f"slot {slot} is already empty")
        if not self._ours(slot, sounds):
            raise UploadRefused(f"slot {slot} isn't a sound koii studio uploaded; it only deletes its own uploads")
        self.client.delete_sound(slot)
        uploads = self.uploads()
        uploads.pop(slot, None)
        self._save_uploads(uploads)
        self._sounds = None
        self.events.publish("samples", stage="changed")
        return f"deleted koii studio's upload in slot {slot}"

    # -- backups --------------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._job is not None and self._job.is_alive()

    def start_backup(self) -> str:
        if self.busy:
            return "a backup is already running"
        self._cancel.clear()
        self._progress = Progress("starting")
        self._job = threading.Thread(target=self._run_backup, name="koii-studio-backup", daemon=True)
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
