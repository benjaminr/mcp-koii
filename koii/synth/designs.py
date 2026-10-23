"""
Saved sound designs, in ~/.koii/designs.json, each remembering the slots it
was uploaded to so a sound on the device can be reopened, changed and
uploaded again.
"""

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from koii.synth.schema import DesignError, validate

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9 _.-]{0,39}$")


def design_key(name: str) -> str:
    key = " ".join(name.strip().lower().split())
    if not NAME_PATTERN.match(key):
        raise DesignError(f"'{name}' can't be a design name: use letters, numbers, spaces, '-', '_' or '.' (max 40)")
    return key


class DesignStore:
    def __init__(self, home: Path):
        self.path = home / "designs.json"
        self._lock = threading.Lock()

    def _read(self) -> Dict[str, Dict[str, Any]]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def _write(self, designs: Dict[str, Dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(designs, indent=1, sort_keys=True))
        temporary.replace(self.path)

    def list(self) -> List[Dict[str, Any]]:
        """name, slots and when it was saved, newest first (without the designs themselves)."""
        entries = [{"name": key, "slots": entry.get("slots", []), "saved": entry.get("saved"),
                    "notes": entry["design"].get("notes", "")}
                   for key, entry in self._read().items()]
        return sorted(entries, key=lambda entry: entry["saved"] or "", reverse=True)

    def get(self, name: str) -> Dict[str, Any]:
        entry = self._read().get(design_key(name))
        if entry is None:
            raise DesignError(f"no saved design '{name}'")
        return entry["design"]

    def save(self, design: Dict[str, Any], name: Optional[str] = None) -> str:
        checked = validate(design)
        key = design_key(name or checked["name"])
        checked["name"] = key
        with self._lock:
            designs = self._read()
            slots = designs.get(key, {}).get("slots", [])
            designs[key] = {"design": checked, "slots": slots, "saved": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self._write(designs)
        return key

    def delete(self, name: str) -> None:
        key = design_key(name)
        with self._lock:
            designs = self._read()
            if key not in designs:
                raise DesignError(f"no saved design '{name}'")
            del designs[key]
            self._write(designs)

    def link_slot(self, name: str, slot: int) -> None:
        """Remember that this design is on the device in `slot` (and no other design is)."""
        key = design_key(name)
        with self._lock:
            designs = self._read()
            for other in designs.values():
                if slot in other.get("slots", []):
                    other["slots"] = [s for s in other["slots"] if s != slot]
            if key in designs:
                designs[key]["slots"] = sorted(set(designs[key].get("slots", [])) | {slot})
            self._write(designs)

    def unlink_slot(self, slot: int) -> None:
        with self._lock:
            designs = self._read()
            for entry in designs.values():
                entry["slots"] = [s for s in entry.get("slots", []) if s != slot]
            self._write(designs)

    def slots_of(self, name: str) -> List[int]:
        """The slots this design was uploaded to."""
        return list(self._read().get(design_key(name), {}).get("slots", []))

    def for_slot(self, slot: int) -> Optional[str]:
        for key, entry in self._read().items():
            if slot in entry.get("slots", []):
                return key
        return None
