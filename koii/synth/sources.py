"""
Sounds to sample from: recordings, loaded files, slices and bounces, kept in
~/.koii/sources as 16-bit WAVs at 46,875 Hz with an index beside them.

The factory library is available too: "slot:203" is sound 203 as saved by the
latest backup, so a design can resample, granulate or layer the EP-133's own
sounds without touching the device.
"""

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from koii.backup import latest_backup
from koii.synth.edit import read_wav_bytes, to_device_rate, wav_bytes
from koii.synth.schema import DEVICE_RATE, DesignError

SLOT_PREFIX = "slot:"
CACHE_LIMIT = 24


class SourceStore:
    def __init__(self, home: Path):
        self.folder = home / "sources"
        self.backups = home / "backups"
        self.index_path = self.folder / "index.json"
        self._cache: Dict[str, np.ndarray] = {}
        self._lock = threading.Lock()

    # -- the index ----------------------------------------------------------------------------

    def _index(self) -> Dict[str, Dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        return json.loads(self.index_path.read_text())

    def _save_index(self, index: Dict[str, Dict[str, Any]]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(index, indent=2))

    def list(self) -> List[Dict[str, Any]]:
        """Saved sources, newest first."""
        entries = [{"id": source_id, **entry} for source_id, entry in self._index().items()]
        return sorted(entries, key=lambda entry: entry.get("created", ""), reverse=True)

    def info(self, source_id: str) -> Dict[str, Any]:
        if source_id.startswith(SLOT_PREFIX):
            audio = self.load(source_id)
            return {"id": source_id, "name": f"device sound {source_id[len(SLOT_PREFIX):]}", "origin": "backup",
                    "seconds": round(audio.shape[1] / DEVICE_RATE, 3), "channels": audio.shape[0]}
        entry = self._index().get(source_id)
        if entry is None:
            raise DesignError(f"no source '{source_id}'")
        return {"id": source_id, **entry}

    # -- adding and removing ------------------------------------------------------------------

    def add(self, audio: np.ndarray, name: str, origin: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Save audio (channels, frames at 46,875 Hz) and return its index entry."""
        audio = np.asarray(audio, np.float32)
        if audio.ndim == 1:
            audio = audio[np.newaxis, :]
        if audio.shape[0] not in (1, 2) or audio.shape[1] < 32:
            raise DesignError("a source must be mono or stereo and not empty")
        data = wav_bytes(audio)
        source_id = hashlib.sha256(data).hexdigest()[:10]
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{source_id}.wav").write_bytes(data)
        entry = {"name": (name or "source")[:40], "origin": origin, "seconds": round(audio.shape[1] / DEVICE_RATE, 3),
                 "channels": audio.shape[0], "created": time.strftime("%Y-%m-%dT%H:%M:%S"), **(extra or {})}
        with self._lock:
            index = self._index()
            index[source_id] = entry
            self._save_index(index)
            self._cache[source_id] = audio
        return {"id": source_id, **entry}

    def add_wav(self, data: bytes, name: str, origin: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Save a WAV file of any common format and rate, converted to 46,875 Hz."""
        audio, rate = read_wav_bytes(data)
        if audio.shape[0] > 2:
            audio = audio.mean(axis=0, keepdims=True)
        return self.add(to_device_rate(audio, rate), name, origin, extra)

    def delete(self, source_id: str) -> None:
        with self._lock:
            index = self._index()
            if source_id not in index:
                raise DesignError(f"no source '{source_id}'")
            del index[source_id]
            self._save_index(index)
            self._cache.pop(source_id, None)
        (self.folder / f"{source_id}.wav").unlink(missing_ok=True)

    def rename(self, source_id: str, name: str) -> Dict[str, Any]:
        with self._lock:
            index = self._index()
            if source_id not in index:
                raise DesignError(f"no source '{source_id}'")
            index[source_id]["name"] = name[:40]
            self._save_index(index)
        return {"id": source_id, **index[source_id]}

    # -- loading ------------------------------------------------------------------------------

    def load(self, source_id: str) -> np.ndarray:
        """A source's audio as (channels, frames) floats at 46,875 Hz."""
        with self._lock:
            if source_id in self._cache:
                return self._cache[source_id]
        path = self._path(source_id)
        audio, rate = read_wav_bytes(path.read_bytes())
        audio = to_device_rate(audio, rate)
        with self._lock:
            if len(self._cache) >= CACHE_LIMIT:
                self._cache.pop(next(iter(self._cache)))
            self._cache[source_id] = audio
        return audio

    def _path(self, source_id: str) -> Path:
        if source_id.startswith(SLOT_PREFIX):
            return self._backup_wav(source_id[len(SLOT_PREFIX):])
        if source_id not in self._index():
            raise DesignError(f"no source '{source_id}'")
        return self.folder / f"{source_id}.wav"

    def _backup_wav(self, slot_text: str) -> Path:
        if not slot_text.isdigit():
            raise DesignError(f"'{SLOT_PREFIX}{slot_text}' isn't a slot number")
        backup = latest_backup(self.backups)
        if backup is None:
            raise DesignError("sampling device sounds needs a backup (backup_device) to read them from")
        slot = int(slot_text)
        for path in (backup / "sounds").glob(f"{slot:03d} *.wav"):
            return path
        raise DesignError(f"slot {slot} isn't in the latest backup")

    def loader(self) -> Callable[[str], np.ndarray]:
        """What koii.synth.engine.render calls to fetch a sample layer's audio."""
        return self.load
