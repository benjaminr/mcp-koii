import json
import threading
import time
import wave

import pytest

from koii import files
from koii.backup import backup_device, latest_backup
from koii.events import EventBus
from koii.samples import DeviceLibrary

from fake_device import FakeEP133, client_for, sound


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(files, "PAGE_PAUSE_SECONDS", 0)
    pcm = b"".join((i * 7 % 3000).to_bytes(2, "little", signed=True) for i in range(1500))
    return FakeEP133(
        {1: sound("micro kick", pcm), 7: sound("kick grit", pcm[:800]), 559: sound("search/chord", pcm[:4000])},
        projects={3000: ("01", b"tar one" * 50), 4000: ("02", b"tar two" * 40)},
    )


def test_a_backup_holds_every_sound_as_wav_with_metadata_and_every_project(fake, tmp_path):
    client = client_for(fake, tmp_path / "lock")
    stages = []
    result = backup_device(client, tmp_path / "backups", lambda p: stages.append(p.stage))
    manifest = json.loads((result.path / "manifest.json").read_text())
    assert manifest["complete"] and [s["slot"] for s in manifest["sounds"]] == [1, 7, 559]
    assert manifest["sounds"][2]["file"] == "559 search_chord.wav"
    with wave.open(str(result.path / "sounds" / "001 micro kick.wav")) as audio:
        assert audio.getframerate() == 46875 and audio.readframes(audio.getnframes()) == fake.sounds[1][1]
    assert sorted(p.name for p in (result.path / "projects").iterdir()) == ["01.tar", "02.tar"]
    assert stages[0] == "listing" and stages[-1] == "done"
    assert latest_backup(tmp_path / "backups") == result.path


def test_a_second_backup_reuses_unchanged_sounds(fake, tmp_path):
    client = client_for(fake, tmp_path / "lock")
    first = backup_device(client, tmp_path / "backups")
    name, pcm, metadata = fake.sounds[7]
    fake.sounds[7] = sound(name, pcm[::-1])
    time.sleep(1.1)  # folders are named by the second
    second = backup_device(client, tmp_path / "backups")
    assert first.reused == 0 and second.reused == 2
    assert second.bytes_read < first.bytes_read
    assert latest_backup(tmp_path / "backups") == second.path


def test_a_cancelled_backup_is_not_counted(fake, tmp_path):
    client = client_for(fake, tmp_path / "lock")
    cancel = threading.Event()
    cancel.set()
    result = backup_device(client, tmp_path / "backups", cancel=cancel)
    assert not json.loads((result.path / "manifest.json").read_text())["complete"]
    assert latest_backup(tmp_path / "backups") is None


def test_the_library_runs_backups_in_the_background_and_reports_progress(fake, tmp_path):
    events = EventBus()
    feed = events.subscribe()
    library = DeviceLibrary(events, tmp_path, client_for(fake, tmp_path / "lock"))
    assert "started" in library.start_backup()
    library._job.join(10)
    seen = []
    while not feed.empty():
        seen.append(feed.get())
    assert seen[-1]["type"] == "backup" and seen[-1]["stage"] == "done"
    assert library.backup_status()["latest"]
    assert "micro kick" in library.summary() and "1 match 'grit'" in library.summary("grit")
