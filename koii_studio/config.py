"""
Where koii studio keeps its files, and its environment settings.

Settings are KOII_STUDIO_<name> (HOME, WEB, WEB_PORT); each still answers to its name from
before the project was renamed, KOII_<name>. Files live in $KOII_STUDIO_HOME or
~/.koii-studio, and a ~/.koii folder from before the rename is moved there once, on start.
"""

import os
from pathlib import Path

HOME_FOLDER = ".koii-studio"
OLD_HOME_FOLDER = ".koii"


def setting(name: str, default: str) -> str:
    """The environment setting KOII_STUDIO_<name>, or KOII_<name>, or the default (an empty one counts as unset)."""
    return os.environ.get(f"KOII_STUDIO_{name}") or os.environ.get(f"KOII_{name}") or default


def default_home() -> Path:
    """Where the library, designs, packs and backups live."""
    configured = setting("HOME", "")
    return Path(configured) if configured else Path.home() / HOME_FOLDER


def move_old_home() -> None:
    """Move ~/.koii to ~/.koii-studio, unless a home is configured or the new folder exists."""
    if setting("HOME", ""):
        return
    home = Path.home() / HOME_FOLDER
    old_home = Path.home() / OLD_HOME_FOLDER
    if not home.exists() and old_home.is_dir():
        old_home.rename(home)
