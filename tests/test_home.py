"""Where koii studio keeps its files, and carrying them over from before the rename."""

from pathlib import Path

import pytest

from koii_studio.config import default_home, setting
from koii_studio.library import Library


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for name in ("KOII_STUDIO_HOME", "KOII_HOME", "KOII_STUDIO_WEB_PORT", "KOII_WEB_PORT"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_files_from_before_the_rename_move_to_the_new_folder(home):
    (home / ".koii").mkdir()
    (home / ".koii" / "designs.json").write_text("{}")

    library = Library()

    assert library.home == home / ".koii-studio"
    assert (library.home / "designs.json").read_text() == "{}"
    assert not (home / ".koii").exists()


def test_looking_up_the_home_folder_moves_nothing(home):
    (home / ".koii").mkdir()

    assert default_home() == home / ".koii-studio"
    assert (home / ".koii").exists()


def test_an_existing_new_folder_is_never_replaced_by_the_old_one(home):
    (home / ".koii").mkdir()
    (home / ".koii-studio").mkdir()

    Library()

    assert (home / ".koii").exists()


def test_settings_still_answer_to_their_names_from_before_the_rename(home, monkeypatch):
    monkeypatch.setenv("KOII_WEB_PORT", "9000")
    assert setting("WEB_PORT", "8133") == "9000"

    monkeypatch.setenv("KOII_STUDIO_WEB_PORT", "9100")
    assert setting("WEB_PORT", "8133") == "9100"


def test_a_home_set_with_the_old_setting_is_still_used(home, monkeypatch):
    monkeypatch.setenv("KOII_HOME", str(home / "elsewhere"))
    assert default_home() == home / "elsewhere"
