"""Sample packs: installing puts samples, pads, patterns and songs in place; removing frees the space."""

import json

import numpy as np
import pytest

from koii import files
from koii.backup import backup_device
from koii.events import EventBus
from koii.packs import PackError, PackStore, read_pack
from koii.pads import PadEditor
from koii.samples import DeviceLibrary
from koii.synth.edit import wav_bytes

from fake_device import FakeEP133, client_for, sound

KICK = 7          # a factory sound already on the device
KEYS_UPLOAD = 602  # where the 'keys' design ends up


def make_pack(home, **overrides):
    folder = home / "packs" / "tiny"
    (folder / "samples").mkdir(parents=True)
    for name in ("vox", "stab"):
        tone = np.sin(np.arange(4000) * 0.05).astype(np.float32)[None, :] * 0.5
        (folder / "samples" / f"{name}.wav").write_bytes(wav_bytes(tone, 46875))
    manifest = {
        "format": 1, "name": "tiny", "title": "Tiny demo", "description": "two chops",
        "samples": [{"id": "vox", "file": "samples/vox.wav", "name": "tiny vox",
                     "settings": {"sound.playmode": "oneshot", "envelope.release": 255}},
                    {"id": "stab", "file": "samples/stab.wav", "name": "tiny stab"}],
        "pads": {"B.": {"sample": "vox"}, "B0": {"sample": "stab", "level": 80},
                 "A.": {"sound": KICK}, "D1": {"design": "keys", "channel": 3, "mode": "key"}},
        "patterns": {"tiny-beat": "kick: x...x...x...x...\n"},
        "songs": {"tiny-song": "tiny-beat x2"},
        **overrides,
    }
    (folder / "pack.json").write_text(json.dumps(manifest))
    return folder


@pytest.fixture
def store(monkeypatch, tmp_path):
    for name in ("PAGE_PAUSE_SECONDS", "PUT_PAGE_PAUSE_SECONDS", "PREFLIGHT_SECONDS"):
        monkeypatch.setattr(files, name, 0)
    monkeypatch.setattr("koii.pads.SETTLE_SECONDS", 0)
    monkeypatch.setattr("koii.pads.PROJECT_SETTLE_SECONDS", 0)
    fake = FakeEP133({KICK: sound("kick grit", b"\x01\x00" * 600)}, active_project=2)
    client = client_for(fake, tmp_path / "lock")
    events = EventBus()
    samples = DeviceLibrary(events, tmp_path, client)
    backup_device(client, tmp_path / "backups")
    saved = {"patterns": {}, "songs": {}, "designs": 0}

    def upload_design(name):
        saved["designs"] += 1
        samples.upload(KEYS_UPLOAD, b"\x03\x00" * 900, name)
        return KEYS_UPLOAD

    pads = PadEditor(events, tmp_path, client)
    packs = PackStore(events, tmp_path, samples, pads,
                      save_pattern=lambda name, text: saved["patterns"].__setitem__(name, text),
                      save_song=lambda name, text: saved["songs"].__setitem__(name, text),
                      upload_design=upload_design)
    make_pack(tmp_path)
    return fake, packs, saved


def test_installing_a_pack_fills_a_project_and_the_library(store):
    fake, packs, saved = store
    result = packs.install(packs.get("tiny"), project=9)
    assert fake.active_project == 9
    vox_slot = fake.pads[11310]["sym"]                       # B. in project 9
    assert fake.sounds[vox_slot][2]["name"] == "tiny vox"
    assert fake.pads[11311]["sound.amplitude"] == 80          # B0, with its level
    assert fake.pads[11210]["sym"] == KICK                    # A. uses the factory kick
    assert fake.pads[11507]["sym"] == KEYS_UPLOAD and fake.pads[11507]["midi.channel"] == 3   # D1
    assert saved["patterns"] == {"tiny-beat": "kick: x...x...x...x...\n"} and "tiny-song" in saved["songs"]
    assert "project 9" in result["message"]
    listed = packs.list()[0]
    assert listed["installed"]["project"] == 9 and len(listed["installed"]["slots"]) == 2


def test_installing_again_reuses_what_is_on_the_device(store):
    fake, packs, saved = store
    packs.install(packs.get("tiny"), project=9)
    uploads = len([r for r in fake.requests if r[:2] == bytes([0x02, 0x00])])
    packs.install(packs.get("tiny"), project=9)
    assert len([r for r in fake.requests if r[:2] == bytes([0x02, 0x00])]) == uploads   # nothing uploaded twice
    assert saved["designs"] == 1


def test_removing_a_pack_frees_its_slots_and_empties_its_pads(store):
    fake, packs, saved = store
    packs.install(packs.get("tiny"), project=9)
    slots = packs.list()[0]["installed"]["slots"]
    result = packs.remove(packs.get("tiny"))
    assert all(slot not in fake.sounds for slot in slots)
    assert fake.pads[11310]["sym"] == 0 and fake.pads[11210]["sym"] == KICK    # factory pads stay
    assert packs.list()[0]["installed"] is None and "tiny-song" in saved["songs"]
    assert "2 samples deleted" in result["message"]


def test_a_broken_pack_is_refused_clearly(tmp_path):
    folder = make_pack(tmp_path, pads={"B.": {"sample": "missing"}})
    with pytest.raises(PackError, match="uses sample 'missing'"):
        read_pack(folder)
