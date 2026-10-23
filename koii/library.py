"""
Persistent storage for patterns, songs and kit aliases.

Everything lives in one JSON file (default ~/.koii/library.json, or $KOII_HOME),
so work survives server restarts and can be versioned or shared.
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from koii import device
from koii.notation import Issue, NotationError, Pattern, parse_arrangement, parse_pattern, parse_target

_NAME_RE = re.compile(r"^[A-Za-z][\w\-]{0,63}$")


def default_home() -> Path:
    return Path(os.environ.get("KOII_HOME", Path.home() / ".koii"))


class LibraryError(ValueError):
    pass


class Library:
    def __init__(self, home: Optional[Path] = None):
        self.home = Path(home) if home else default_home()
        self.path = self.home / "library.json"
        self.patterns: Dict[str, Dict] = {}
        self.songs: Dict[str, Dict] = {}
        self.aliases: Dict[str, str] = {}
        self._load()

    # -- persistence --------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        self.patterns = data.get("patterns", {})
        self.songs = data.get("songs", {})
        self.aliases = data.get("aliases", {})

    def _save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "patterns": self.patterns, "songs": self.songs, "aliases": self.aliases}
        fd, tmp = tempfile.mkstemp(dir=self.home, prefix=".library-", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    # -- names --------------------------------------------------------------

    @staticmethod
    def _check_name(name: str) -> str:
        if not _NAME_RE.match(name) or re.fullmatch(r"[x×]\d+", name, re.IGNORECASE):
            raise LibraryError(f"'{name}' isn't a valid name. Use letters, digits, _ or -, starting with a letter")
        if device.parse_pad(name):
            raise LibraryError(f"'{name}' looks like a pad label; pick another name")
        return name

    def _find(self, name: str) -> Tuple[Optional[str], Optional[str]]:
        """Case-insensitive lookup. Returns (kind, stored name)."""
        for kind, table in (("pattern", self.patterns), ("song", self.songs)):
            for stored in table:
                if stored.lower() == name.lower():
                    return kind, stored
        return None, None

    # -- aliases ------------------------------------------------------------

    def effective_aliases(self) -> Dict[str, str]:
        merged = dict(device.DEFAULT_ALIASES)
        merged.update(self.aliases)
        return merged

    def set_alias(self, name: str, target: str) -> str:
        name = name.lower()
        self._check_name(name)
        parsed = parse_target(target)
        if parsed is None:
            raise LibraryError(f"'{target}' isn't a pad (A1, B., CEnter), MIDI note (0-127) or channel (ch1-ch16)")
        self.aliases[name] = parsed.label if parsed.kind != "note" else str(parsed.note)
        self._save()
        return self.aliases[name]

    def remove_alias(self, name: str) -> str:
        name = name.lower()
        if name in self.aliases:
            del self.aliases[name]
            self._save()
            default = device.DEFAULT_ALIASES.get(name)
            return f"removed '{name}'" + (f" (back to the built-in {default})" if default else "")
        if name in device.DEFAULT_ALIASES:
            raise LibraryError(f"'{name}' is built in; point it somewhere else with set_alias instead")
        raise LibraryError(f"no alias '{name}'")

    # -- patterns & songs ---------------------------------------------------

    def parse(self, text: str) -> Pattern:
        return parse_pattern(text, self.effective_aliases())

    def save_pattern(self, name: str, text: str) -> Pattern:
        self._check_name(name)
        kind, stored = self._find(name)
        if kind == "song":
            raise LibraryError(f"'{stored}' is already a song; pick another name")
        pattern = self.parse(text)
        if stored and stored != name:
            del self.patterns[stored]
        self.patterns[name] = {"text": text, "saved": _now()}
        self._save()
        return pattern

    def save_song(self, name: str, arrangement: str, bpm: Optional[int] = None) -> None:
        self._check_name(name)
        kind, stored = self._find(name)
        if kind == "pattern":
            raise LibraryError(f"'{stored}' is already a pattern; pick another name")
        parse_arrangement(arrangement)
        if stored and stored != name:
            del self.songs[stored]
        self.songs[name] = {"arrangement": arrangement, "bpm": bpm, "saved": _now()}
        self._save()

    def get_pattern(self, name: str) -> Optional[Pattern]:
        kind, stored = self._find(name)
        if kind != "pattern":
            return None
        try:
            return self.parse(self.patterns[stored]["text"])
        except NotationError as e:
            # Can happen if an alias the pattern relied on was changed later.
            raise NotationError([Issue(0, None, f"saved pattern '{stored}' no longer parses:")] + e.issues)

    def get_song(self, name: str) -> Optional[Tuple[str, Optional[int]]]:
        kind, stored = self._find(name)
        if kind != "song":
            return None
        song = self.songs[stored]
        return song["arrangement"], song.get("bpm")

    def lookup(self, name: str) -> Tuple[Optional[str], Optional[str]]:
        return self._find(name)

    def delete(self, name: str) -> str:
        kind, stored = self._find(name)
        if kind is None:
            raise LibraryError(f"nothing saved as '{name}'")
        (self.patterns if kind == "pattern" else self.songs).pop(stored)
        self._save()
        return f"deleted {kind} '{stored}'"

    def names(self) -> List[str]:
        return sorted(list(self.patterns) + list(self.songs), key=str.lower)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
