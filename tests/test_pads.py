"""Setting the EP-133's pads over USB: names, the device's rules, read-back checks and undo."""

import pytest

from koii_studio import files
from koii_studio.events import EventBus
from koii_studio.pads import PadEditor, PadError, changes_for, parse_pad

from fake_device import FakeEP133, client_for, sound

PIANO = 602
CHORDS_PAD = 4507          # D1 in project 2


def pad(sym, **settings):
    return {"sym": sym, "sound.playmode": "oneshot", "sample.start": 0, "sample.end": 1000, "envelope.attack": 0,
            "envelope.release": 255, "sound.pitch": 0.0, "sound.amplitude": 100, "sound.pan": 0,
            "sound.mutegroup": False, "time.mode": "off", "midi.channel": 0, **settings}


@pytest.fixture
def device(monkeypatch, tmp_path):
    for name in ("PAGE_PAUSE_SECONDS", "PUT_PAGE_PAUSE_SECONDS", "PREFLIGHT_SECONDS"):
        monkeypatch.setattr(files, name, 0)
    monkeypatch.setattr("koii_studio.pads.SETTLE_SECONDS", 0)
    fake = FakeEP133({PIANO: sound("clean keys", b"\x01\x00" * 2000, **{"envelope.attack": 0}),
                      604: sound("glass pad", b"\x02\x00" * 4000, **{"envelope.attack": 40})},
                     pads={CHORDS_PAD: pad(PIANO), 4310: pad(401, **{"midi.channel": 2})}, active_project=2)
    events = EventBus()
    return fake, PadEditor(events, tmp_path, client_for(fake, tmp_path / "lock")), events


def test_pads_are_named_as_on_the_keypad():
    assert parse_pad("d1").node(2) == CHORDS_PAD
    assert parse_pad("A.").node(1) == 3210          # the lowest pad, note 36
    assert parse_pad("BE").label == "BEnter"
    for wrong in ("E1", "A10", "D", "kick"):
        with pytest.raises(PadError, match="isn't a pad"):
            parse_pad(wrong)


def test_a_new_play_mode_goes_with_a_release_as_the_device_requires():
    assert changes_for({"mode": "key"}, pad(PIANO)) == {"sound.playmode": "key", "envelope.release": 128}
    assert changes_for({"release": 90}, pad(PIANO)) == {"envelope.release": 90, "sound.playmode": "oneshot"}
    assert changes_for({"channel": "none"}, pad(PIANO, **{"midi.channel": 3})) == {"midi.channel": 0}
    with pytest.raises(PadError, match="channel must be 1–16"):
        changes_for({"channel": 17}, pad(PIANO))
    with pytest.raises(PadError, match="mode must be"):
        changes_for({"mode": "loop"}, pad(PIANO))
    with pytest.raises(PadError, match="unknown pad setting volume"):
        changes_for({"volume": 3}, pad(PIANO))


def test_a_melodic_pad_is_set_up_in_one_change_and_checked(device):
    fake, editor, _ = device
    result = editor.set("D1", channel=3, mode="key", level=60)
    assert result["project"] == 2
    assert fake.pads[CHORDS_PAD]["midi.channel"] == 3 and fake.pads[CHORDS_PAD]["sound.playmode"] == "key"
    assert fake.pads[CHORDS_PAD]["envelope.release"] == 128 and fake.pads[CHORDS_PAD]["sound.amplitude"] == 60
    assert fake.pads[4310]["midi.channel"] == 2            # other pads untouched
    assert "channel None → 3" in result["message"] and "mode oneshot → key" in result["message"]


def test_changing_a_pads_sound_plays_the_whole_new_sample(device):
    fake, editor, _ = device
    editor.set("D1", sound=604)
    stored = fake.pads[CHORDS_PAD]
    assert stored["sym"] == 604 and stored["sample.start"] == 0 and stored["sample.end"] == 4000
    assert stored["envelope.attack"] == 40                 # the new sample's own defaults come with it
    with pytest.raises(PadError, match="slot 777 is empty"):
        editor.set("D1", sound=777)


def test_the_last_change_can_be_undone(device):
    fake, editor, _ = device
    editor.set("D1", channel=5, mode="legato", level=40)
    editor.undo()
    assert fake.pads[CHORDS_PAD] == pad(PIANO)
    with pytest.raises(PadError, match="no pad changes to undo"):
        editor.undo()


def test_undo_waits_for_the_project_it_changed(device):
    fake, editor, _ = device
    editor.set("D1", channel=4)
    fake.active_project = 3
    with pytest.raises(PadError, match="open it on the device"):
        editor.undo()


def test_a_whole_group_can_be_read(device):
    _, editor, _ = device
    group = editor.get(group="D")
    assert group["project"] == 2 and len(group["pads"]) == 12
    chords = next(p for p in group["pads"] if p["pad"] == "D1")
    assert chords["sound"] == PIANO and chords["mode"] == "oneshot"
    assert next(p for p in group["pads"] if p["pad"] == "D7")["sound"] is None


def test_another_project_can_be_opened_and_its_pads_set(device, monkeypatch):
    fake, editor, _ = device
    monkeypatch.setattr("koii_studio.pads.PROJECT_SETTLE_SECONDS", 0)
    assert editor.open_project(9)["message"] == "project 9 is open (was 2)"
    editor.set("A.", sound=PIANO)
    assert fake.pads[11210]["sym"] == PIANO and fake.pads[CHORDS_PAD]["sym"] == PIANO   # project 2's pad untouched
    assert editor.open_project(9)["message"] == "project 9 is open already"
    with pytest.raises(PadError, match="projects are 1–9"):
        editor.open_project(10)


def test_undo_takes_off_a_channel_the_pad_didnt_have_before(device):
    fake, editor, _ = device
    del fake.pads[CHORDS_PAD]["midi.channel"]
    editor.set("D1", channel=3)
    result = editor.undo()
    assert fake.pads[CHORDS_PAD]["midi.channel"] == 0
    assert result["after"]["channel"] is None
    with pytest.raises(PadError, match="no pad changes"):
        editor.undo()


def test_an_undo_the_device_didnt_take_can_be_tried_again(device, monkeypatch):
    fake, editor, _ = device
    editor.set("D1", level=60)
    real_handle = fake._handle

    def ignoring_writes(payload):   # the device answers, but keeps the pad as it is
        if payload[0] == 0x07 and payload[1] == 0x01:
            return 0, b""
        return real_handle(payload)

    monkeypatch.setattr(fake, "_handle", ignoring_writes)
    with pytest.raises(PadError, match="didn't put back"):
        editor.undo()
    monkeypatch.setattr(fake, "_handle", real_handle)
    editor.undo()
    assert fake.pads[CHORDS_PAD]["sound.amplitude"] == 100
