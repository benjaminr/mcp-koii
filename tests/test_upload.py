"""Uploads follow the rules: backup first, empty or own slots only, checked against the device's CRC."""

import zlib

import pytest

from koii import files
from koii.backup import backup_device
from koii.events import EventBus
from koii.files import DeviceFileError
from koii.samples import DeviceLibrary, UploadRefused

from fake_device import FakeEP133, client_for, sound


@pytest.fixture
def setup(monkeypatch, tmp_path):
    for name in ("PAGE_PAUSE_SECONDS", "PUT_PAGE_PAUSE_SECONDS", "PREFLIGHT_SECONDS"):
        monkeypatch.setattr(files, name, 0)
    fake = FakeEP133({1: sound("micro kick", b"\x01\x00" * 500), 600: sound("factory pad", b"\x02\x00" * 300)})
    client = client_for(fake, tmp_path / "lock")
    library = DeviceLibrary(EventBus(), tmp_path, client)
    return fake, client, library, tmp_path


def tone(frames=4000):
    return b"".join(((i * 37) % 20000 - 10000).to_bytes(2, "little", signed=True) for i in range(frames))


def test_uploads_need_a_backup_first(setup):
    fake, client, library, home = setup
    with pytest.raises(UploadRefused, match="backup first"):
        library.upload(601, tone(), "test")
    assert 601 not in fake.sounds


def test_an_upload_is_written_page_by_page_and_checked(setup):
    fake, client, library, home = setup
    backup_device(client, home / "backups")
    pcm = tone(5000)
    result = library.upload(601, pcm, "koii kick")
    assert fake.sounds[601][1] == pcm and fake.sounds[601][2]["crc"] == zlib.crc32(pcm)
    assert fake.sounds[601][2]["name"] == "koii kick" and fake.sounds[601][2]["samplerate"] == 46875
    pages = [r for r in fake.requests if r[:2] == bytes([0x02, 0x01])]
    assert len(pages) == -(-len(pcm) // 433) + 1  # data pages plus the empty end-of-file page
    assert result["slot"] == 601 and "screen shows 601" in result["message"]
    assert library.uploads()[601]["crc"] == zlib.crc32(pcm)


def test_koii_never_overwrites_sounds_it_didnt_upload(setup):
    fake, client, library, home = setup
    backup_device(client, home / "backups")
    with pytest.raises(UploadRefused, match="koii didn't put there"):
        library.upload(600, tone(), "oops")
    assert fake.sounds[600][0] == "factory pad"
    assert library.suggest_slot() == 601


def test_its_own_uploads_can_be_replaced_and_deleted(setup):
    fake, client, library, home = setup
    backup_device(client, home / "backups")
    library.upload(601, tone(), "first")
    assert library.upload(601, tone(3000), "second")["replaced"]
    assert library.listing()["sounds"][-1]["ours"]
    with pytest.raises(UploadRefused, match="only deletes its own"):
        library.delete_upload(1)
    assert "deleted" in library.delete_upload(601)
    assert 601 not in fake.sounds and 601 not in library.uploads()


def test_a_sound_changed_on_the_device_is_no_longer_treated_as_ours(setup):
    fake, client, library, home = setup
    backup_device(client, home / "backups")
    library.upload(601, tone(), "mine")
    name, data, metadata = fake.sounds[601]
    fake.sounds[601] = sound("resampled on the device", data[::-1])
    with pytest.raises(UploadRefused, match="koii didn't put there"):
        library.upload(601, tone(), "again")


def test_a_corrupted_write_is_reported(setup, monkeypatch):
    fake, client, library, home = setup
    backup_device(client, home / "backups")
    original = fake._handle

    def damage(payload):
        status, body = original(payload)
        if payload[:2] == bytes([0x02, 0x01]) and payload[4:] == b"" and 601 in fake.sounds:
            name, data, metadata = fake.sounds[601]
            fake.sounds[601] = (name, data, {**metadata, "crc": metadata["crc"] ^ 0xFF})
        return status, body

    monkeypatch.setattr(fake, "_handle", damage)
    with pytest.raises(DeviceFileError, match="didn't store the sound intact"):
        library.upload(601, tone(), "damaged")
    assert 601 not in library.uploads()


def test_limits(setup):
    fake, client, library, home = setup
    backup_device(client, home / "backups")
    with pytest.raises(UploadRefused, match="at most 20s"):
        library.upload(601, b"\x00\x00" * (46875 * 21), "long")
    with pytest.raises(UploadRefused, match="no audio"):
        library.upload(601, b"", "empty")
    with pytest.raises(DeviceFileError, match="whole 16-bit frames"):
        client.upload_sound(601, b"\x00\x00\x00", "odd", channels=2)
    assert files.clean_sample_name("ünïcode name that is far too long") == "_n_code name that is"
