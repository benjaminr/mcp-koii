"""
Fingerprints of the sounds on the device, taken from the latest backup, so the
designer can say which existing sounds a new one is closest to.

Fingerprints are cached in ~/.koii/fingerprints.json by checksum, so only new
or changed sounds are analysed again. Building the index runs in the
background; until it finishes, `nearest` returns nothing.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from koii.backup import MANIFEST, latest_backup
from koii.synth.analysis import features, nearest
from koii.synth.edit import read_wav_bytes, to_device_rate

logger = logging.getLogger(__name__)

FINGERPRINT_VERSION = 2   # bump when analysis.features changes


class FactoryIndex:
    def __init__(self, home: Path):
        self.backups = home / "backups"
        self.cache_path = home / "fingerprints.json"
        self._library: Dict[int, Dict[str, Any]] = {}
        self._backup: Optional[Path] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return bool(self._library) and not self.building

    @property
    def building(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> Dict[str, Any]:
        return {"ready": self.ready, "building": self.building, "sounds": len(self._library),
                "backup": self._backup.name if self._backup else None}

    def ensure(self) -> None:
        """Start (re)building if there's a newer backup than the one indexed."""
        backup = latest_backup(self.backups)
        if backup is None or backup == self._backup or self.building:
            return
        self._thread = threading.Thread(target=self._build, args=(backup,), name="koii-fingerprints", daemon=True)
        self._thread.start()

    def wait(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def nearest(self, audio: np.ndarray, count: int = 3) -> List[Dict[str, Any]]:
        self.ensure()
        with self._lock:
            library = dict(self._library)
        if not library:
            return []
        return nearest(features(audio), library, count)

    def _build(self, backup: Path) -> None:
        try:
            manifest = json.loads((backup / MANIFEST).read_text())
            cache = self._read_cache()
            library: Dict[int, Dict[str, Any]] = {}
            for entry in manifest.get("sounds", []):
                key = f"{entry.get('crc')}"
                if key not in cache:
                    audio, rate = read_wav_bytes((backup / "sounds" / entry["file"]).read_bytes())
                    cache[key] = [round(float(value), 4) for value in features(to_device_rate(audio, rate))]
                library[int(entry["slot"])] = {"name": entry["name"], "features": cache[key]}
            self._write_cache(cache)
            with self._lock:
                self._library, self._backup = library, backup
        except Exception:  # an unreadable backup shouldn't take the designer down
            logger.exception("couldn't fingerprint the sounds in %s", backup)

    def _read_cache(self) -> Dict[str, List[float]]:
        try:
            cached = json.loads(self.cache_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return cached.get("fingerprints", {}) if cached.get("version") == FINGERPRINT_VERSION else {}

    def _write_cache(self, cache: Dict[str, List[float]]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps({"version": FINGERPRINT_VERSION, "fingerprints": cache}))
