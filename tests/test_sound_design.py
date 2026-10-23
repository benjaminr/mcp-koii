"""Sampling, editing, the design library, and putting designed sounds on the (fake) device."""

import base64
import io
import wave

import numpy as np
import pytest

from koii import files
from koii.backup import backup_device
from koii.events import EventBus
from koii.samples import DeviceLibrary, UploadRefused
from koii.sound_design import SoundDesigner
from koii.synth import edit, presets
from koii.synth.analysis import detect_pitch
from koii.synth.designs import DesignStore
from koii.synth.engine import render
from koii.synth.schema import DesignError
from koii.synth.sources import SourceStore

from fake_device import FakeEP133, client_for, sound

RATE = 46875


def hits_at(times, seconds=2.0, names=("kick", "snare", "hat", "clap", "rim", "tom")):
    """A recording of drum hits at the given times, like a bar played on the device."""
    bar = np.zeros((1, int(seconds * RATE)), np.float32)
    for at, name in zip(times, names):
        hit = render(presets.preset(name)).audio
        start = int(at * RATE)
        bar[:, start:start + hit.shape[1]] += hit[:, :bar.shape[1] - start]
    return bar


def wav_base64(audio, rate=RATE):
    return base64.b64encode(edit.wav_bytes(audio, rate)).decode()


# -- editing ------------------------------------------------------------------------------------

def test_onsets_find_each_hit_without_cutting_its_transient():
    times = [0.0, 0.5, 0.75, 1.25, 1.5]
    found = np.array(edit.onsets(hits_at(times))) / RATE
    assert len(found) == len(times)
    assert np.all(found <= np.array(times) + 0.001)       # never late
    assert np.all(found >= np.array(times) - 0.012)       # and not far early


def test_chopping_makes_one_slice_per_hit():
    audio = hits_at([0.0, 0.5, 1.0, 1.5])
    slices = edit.chop(audio, edit.onsets(audio))
    assert len(slices) == 4
    assert sum(piece.shape[1] for piece in slices) <= audio.shape[1]


def test_pitch_shift_changes_the_note_and_keeps_the_length():
    organ = render(presets.preset("organ")).audio
    down = edit.pitch_shift(organ, -12)
    assert detect_pitch(down)["name"] == "C3"
    assert abs(down.shape[1] - organ.shape[1]) < 0.02 * organ.shape[1]
    tape = edit.pitch_shift(organ, 12, keep_length=False)
    assert abs(tape.shape[1] - organ.shape[1] / 2) < 0.01 * organ.shape[1]


def test_time_stretch_keeps_the_pitch():
    organ = render(presets.preset("organ")).audio
    longer = edit.time_stretch(organ, 1.5)
    assert longer.shape[1] > 1.4 * organ.shape[1]
    assert detect_pitch(longer)["name"] == "C4"


def test_an_edit_chain_applies_in_order_and_names_a_bad_step():
    audio = render(presets.preset("organ")).audio
    edited = edit.apply_edits(audio, [{"op": "trim", "start": 0.1, "end": 0.6}, {"op": "reverse"},
                                      {"op": "normalise", "peak": -6}])
    assert abs(edited.shape[1] - 0.5 * RATE) <= 1
    assert 20 * np.log10(np.max(np.abs(edited))) == pytest.approx(-6, abs=0.01)
    with pytest.raises(DesignError, match="edit 2 \\(stretch\\)"):
        edit.apply_edits(audio, [{"op": "reverse"}, {"op": "stretch", "factor": 10}])
    with pytest.raises(DesignError, match="edit 1: op must be"):
        edit.apply_edits(audio, [{"op": "explode"}])


@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_wav_files_of_any_integer_depth_load_at_the_devices_rate(width):
    seconds, rate = 0.5, 48000
    tone = np.sin(2 * np.pi * 440 * np.arange(int(seconds * rate)) / rate) * 0.5
    scale = 2 ** (8 * width - 1) - 1
    if width == 1:
        raw = (tone * 127 + 128).astype(np.uint8).tobytes()
    else:
        ints = np.round(tone * scale).astype(np.int64)
        raw = b"".join(int(v).to_bytes(width, "little", signed=True) for v in ints)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(width)
        file.setframerate(rate)
        file.writeframes(raw)
    audio = edit.load_for_device(buffer.getvalue())
    assert abs(audio.shape[1] - seconds * RATE) <= 2
    assert detect_pitch(audio)["name"] == "A4"


# -- stores -------------------------------------------------------------------------------------

def test_sources_are_kept_and_reloaded_exactly(tmp_path):
    store = SourceStore(tmp_path)
    audio = render(presets.preset("pluck")).audio
    entry = store.add(audio, "pluck", "file")
    fresh = SourceStore(tmp_path)
    assert np.allclose(fresh.load(entry["id"]), audio, rtol=0, atol=2 / 32767)   # 16-bit
    assert fresh.list()[0]["name"] == "pluck"
    fresh.delete(entry["id"])
    with pytest.raises(DesignError, match="no source"):
        fresh.load(entry["id"])


def test_saved_designs_remember_their_slots(tmp_path):
    store = DesignStore(tmp_path)
    store.save(presets.preset("kick"), "My Kick")
    store.link_slot("my kick", 601)
    store.save(presets.preset("snare"), "snare")
    store.link_slot("snare", 601)               # a slot holds one sound, so the kick loses it
    assert store.for_slot(601) == "snare"
    assert {d["name"]: d["slots"] for d in store.list()} == {"my kick": [], "snare": [601]}
    with pytest.raises(DesignError, match="can't be a design name"):
        store.save(presets.preset("kick"), "../../etc")


# -- the designer and the device ------------------------------------------------------------------

@pytest.fixture
def studio(monkeypatch, tmp_path):
    for name in ("PAGE_PAUSE_SECONDS", "PUT_PAGE_PAUSE_SECONDS", "PREFLIGHT_SECONDS"):
        monkeypatch.setattr(files, name, 0)
    fake = FakeEP133({1: sound("micro kick", b"\x01\x00" * 500), 600: sound("factory pad", b"\x02\x00" * 300)})
    client = client_for(fake, tmp_path / "lock")
    events = EventBus()
    library = DeviceLibrary(events, tmp_path, client)
    backup_device(client, tmp_path / "backups")
    return fake, SoundDesigner(events, tmp_path, library), events


def test_an_uploaded_design_plays_like_an_instrument_on_the_device(studio):
    fake, designer, _ = studio
    result = designer.upload(presets.preset("organ"))
    slot = result["slot"]
    assert slot == 601                           # 600 is taken by a factory sound
    stored = fake.sounds[slot][2]
    assert stored["sound.rootnote"] == 60 and stored["sound.playmode"] == "key"
    assert 0 < stored["sound.loopstart"] < stored["sound.loopend"]
    assert stored["envelope.release"] == 120     # written together with the play mode
    assert designer.design_for_slot(slot)["name"] == "organ"
    assert "root set to C4" in result["message"]


def test_settings_change_in_place_only_for_koiis_own_uploads(studio):
    fake, designer, _ = studio
    slot = designer.upload(presets.preset("snare"))["slot"]
    before = fake.sounds[slot][1]
    designer.change_settings(slot, {"playmode": "legato", "release": 64, "tempo": "bpm", "bpm": 90, "bars": 1})
    stored = fake.sounds[slot][2]
    assert (stored["sound.playmode"], stored["envelope.release"], stored["time.mode"]) == ("legato", 64, "bpm")
    assert fake.sounds[slot][1] == before        # the audio wasn't touched
    with pytest.raises(UploadRefused, match="only changes its own"):
        designer.change_settings(600, {"release": 10})
    with pytest.raises(DesignError, match="upload the sound again"):
        designer.change_settings(slot, {"root": 48})


def test_a_kit_goes_to_twelve_slots_in_a_row(studio):
    fake, designer, events = studio
    started = designer.start_kit_upload("909")
    assert started["first"] == 601 and "A.      → 601" in started["message"]
    designer._kit_job.join(timeout=120)
    status = designer.kit_status()
    assert status["done"] == 12 and not status["running"] and status["error"] is None
    assert [fake.sounds[slot][2]["name"] for slot in (601, 612)] == ["909 kick", "909 crash"]


def test_a_device_sound_can_be_sampled_from_the_backup(studio):
    fake, designer, _ = studio
    design = designer.sample_design("slot:1", "resampled kick")
    assert designer.render(design).audio.shape[1] > 0
    with pytest.raises(DesignError, match="isn't in the latest backup"):
        designer.sources.load("slot:77")


def test_chopped_slices_upload_as_they_are(studio):
    fake, designer, _ = studio
    entry = designer.add_source(wav_base64(hits_at([0.0, 0.5, 1.0])), "break", "file")
    slices = designer.chop(entry["id"])
    assert [s["name"] for s in slices] == ["break 1", "break 2", "break 3"]
    started = designer.upload_slices([s["id"] for s in slices])
    designer._kit_job.join(timeout=60)
    assert designer.kit_status()["done"] == 3
    assert fake.sounds[started["first"]][2]["name"] == "break 1"


def test_a_bounce_becomes_an_exact_tempo_synced_loop(studio):
    fake, designer, _ = studio
    # One bar at 120 BPM is 2 s; the recording starts 0.3 s early and the first hit lands 30 ms
    # after the browser's estimate.
    recording = np.zeros((1, int(3.5 * RATE)), np.float32)
    recording[:, int(0.33 * RATE):int(0.33 * RATE) + int(2.0 * RATE)] = hits_at([0.0, 0.5, 1.0, 1.5])
    entry = designer.save_bounce(wav_base64(recording), "beat", bars=1, bpm=120, latency=0.3)
    assert entry["bpm"] == 120 and entry["seconds"] == pytest.approx(2.0, abs=0.001)
    loop = designer.sources.load(entry["id"])
    assert np.max(np.abs(loop[:, :int(0.001 * RATE)])) < 0.05     # starts right on the first hit
    result = designer.upload_bounce(entry["id"])
    stored = fake.sounds[result["slot"]][2]
    assert stored["time.mode"] == "bpm" and stored["sound.bpm"] == 120.0 and stored["sound.bars"] == 1.0


def test_a_bounce_longer_than_a_minute_is_refused(studio):
    _, designer, _ = studio
    with pytest.raises(DesignError, match="at most a minute"):
        designer.bounce_plan(bars=40, bpm=120)


def test_loops_outside_the_devices_tempo_range_fold_into_it():
    from koii.sound_design import device_tempo
    assert device_tempo(50, 1) == {"bpm": 100, "bars": 2}        # the same length, twice as fast
    assert device_tempo(200, 2) == {"bpm": 100.0, "bars": 1.0}
    with pytest.raises(DesignError, match="0.25–4 bars"):
        device_tempo(120, 8)
