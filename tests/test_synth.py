"""The sound engine: designs are checked, render the same way every time, and analyse correctly."""

import numpy as np
import pytest

from koii.synth import presets, variation
from koii.synth.analysis import analyse, crossfade_loop, detect_pitch, envelope_times, find_loop
from koii.synth.engine import render
from koii.synth.instrument import prepare
from koii.synth.schema import DesignError, default_design, get_path, numeric_specs, validate

RATE = 46875


def sine_design(frequency, length=1.0, **instrument):
    design = default_design()
    design["length"] = length
    design["layers"][0].update(engine="analog", pitch=frequency, params={"wave": "sine"},
                               amp={"attack": 2, "decay": 800, "sustain": 0.9, "release": 20})
    design["instrument"] = {"playmode": "key", "root": "auto", "loop": "off", **instrument}
    return design


# -- the format ---------------------------------------------------------------------------------

def test_a_minimal_design_gets_every_default_filled_in():
    checked = validate({"layers": [{"engine": "fm"}]})
    assert checked["length"] == 0.6 and checked["instrument"]["playmode"] == "oneshot"
    assert set(checked["layers"][0]) >= {"params", "amp", "pitch_env", "filter", "lfos"}
    assert checked["layers"][0]["params"]["mod_ratio"] == 2


@pytest.mark.parametrize("change, where", [
    ({"layers": [{"engine": "theremin"}]}, "layers[0].engine"),
    ({"layers": [{"amp": {"decay": 99999}}]}, "layers[0].amp.decay"),
    ({"layers": [{"filter": {"type": "comb"}}]}, "layers[0].filter.type"),
    ({"layers": [{}], "effects": [{"type": "reverb", "mix": 2}]}, "effects[0].mix"),
    ({"layers": [{}], "colour": "red"}, "unknown key"),
    ({"layers": []}, "at least one layer"),
    ({"layers": [{}], "instrument": {"root": 200}}, "instrument.root"),
])
def test_a_wrong_design_is_refused_with_the_exact_place(change, where):
    with pytest.raises(DesignError, match=where.replace("[", r"\[").replace("]", r"\]")):
        validate(change)


def test_every_preset_and_kit_is_a_valid_design():
    for name in presets.PRESETS:
        validate(presets.preset(name))
    for style in presets.KIT_STYLES:
        kit = presets.kit(style)
        assert [item["pad"] for item in kit] == presets.KIT_PADS
        for item in kit:
            validate(item["design"])


# -- rendering ----------------------------------------------------------------------------------

def test_the_same_design_always_renders_the_same_audio():
    design = presets.preset("909 snare")   # noise and all
    first, second = render(design), render(design)
    assert np.array_equal(first.audio, second.audio)


def test_renders_are_the_length_asked_for_and_normalised():
    rendered = render(presets.preset("bell"))
    assert rendered.audio.shape == (1, round(3.0 * RATE))
    assert abs(20 * np.log10(np.max(np.abs(rendered.audio))) - (-1.0)) < 0.05
    assert len(rendered.pcm()) == rendered.audio.shape[1] * 2


def test_stereo_designs_render_two_different_channels():
    design = presets.preset("pad")
    design["stereo"] = True
    design["layers"][0]["pan"] = -0.6
    audio = render(design).audio
    assert audio.shape[0] == 2 and not np.allclose(audio[0], audio[1])


@pytest.mark.parametrize("name", ["kick", "acid bass", "marimba", "riser", "vinyl crackle", "electric piano"])
def test_presets_make_sound_without_clipping_or_dc(name):
    audio = render(presets.preset(name)).audio
    assert np.all(np.isfinite(audio))
    assert np.max(np.abs(audio)) <= 1.0
    assert abs(float(np.mean(audio))) < 0.01


# -- analysis -----------------------------------------------------------------------------------

@pytest.mark.parametrize("frequency, name", [(55.0, "A1"), (130.81, "C3"), (261.63, "C4"), (440.0, "A4"), (1046.5, "C6")])
def test_pitch_detection_names_the_note_within_a_few_cents(frequency, name):
    pitch = detect_pitch(render(sine_design(frequency)).audio)
    assert pitch["name"] == name
    assert abs(pitch["cents"]) < 5 and pitch["confidence"] > 0.9


def test_noise_is_reported_as_unpitched():
    pitch = detect_pitch(render(presets.preset("909 snare")).audio)
    assert pitch["frequency"] is None or pitch["confidence"] < 0.7


def test_attack_and_decay_describe_the_first_sound():
    kick = envelope_times(render(presets.preset("kick")).audio)
    pad = envelope_times(render(presets.preset("pad")).audio)
    assert kick["attack"] < 0.02 < pad["attack"]
    hits = np.zeros((1, RATE), np.float32)
    hits[0, 1000:1100] = 0.5
    hits[0, 30000:30100] = 1.0      # a louder hit later doesn't make the attack long
    assert envelope_times(hits)["attack"] < 0.01


def test_a_found_loop_is_seamless():
    audio = render(sine_design(110, 2.0)).audio
    loop = find_loop(audio, 110)
    assert loop and loop["quality"] > 0.95 and loop["end"] - loop["start"] > 0.2 * RATE
    joined = crossfade_loop(audio, loop)[0]
    # Jumping from the end back to the start shouldn't be a bigger step than the wave takes anyway.
    jump = abs(joined[loop["end"] - 1] - joined[loop["start"]])
    assert jump < 2 * np.max(np.abs(np.diff(joined[loop["start"]:loop["end"]])))


def test_analysis_has_everything_the_page_draws():
    report = analyse(render(presets.preset("pluck")).audio)
    assert len(report["spectrum"]) == 64 and len(report["spectrogram"][0]) == 48
    assert report["peak_db"] == pytest.approx(-1.0, abs=0.05)


# -- instrument settings ------------------------------------------------------------------------

def test_a_sustaining_instrument_gets_its_root_and_a_loop():
    sound = prepare(render(sine_design(220, 2.0, loop="auto", playmode="oneshot")))
    assert sound.metadata["sound.rootnote"] == 57          # A3
    assert abs(sound.metadata["sound.pitch"]) < 0.05
    assert 0 < sound.metadata["sound.loopstart"] < sound.metadata["sound.loopend"]
    assert sound.metadata["sound.playmode"] == "key"         # loops only sustain in key or legato mode
    assert any("play mode changed" in note for note in sound.notes)


def test_a_drum_stays_a_one_shot_on_c4():
    sound = prepare(render(presets.preset("snare")))
    assert sound.metadata["sound.playmode"] == "oneshot" and sound.metadata["sound.rootnote"] == 60
    assert sound.metadata["sound.loopstart"] == -1 and sound.metadata["time.mode"] == "off"


def test_device_settings_use_the_devices_own_keys_and_types():
    design = sine_design(220, 1.0, release=128, amplitude=90, tempo="bpm", bpm=96, bars=2)
    metadata = prepare(render(design)).metadata
    assert isinstance(metadata["sound.playmode"], str) and isinstance(metadata["time.mode"], str)
    assert metadata["envelope.release"] == 128 and metadata["sound.amplitude"] == 90
    assert metadata["time.mode"] == "bpm" and metadata["sound.bpm"] == 96.0 and metadata["sound.bars"] == 2.0


# -- variation ----------------------------------------------------------------------------------

def test_variations_are_repeatable_and_respect_locks():
    kick = presets.preset("kick")
    first = variation.randomise(kick, 0.5, locks=["layers.*.amp"], seed=7)
    assert first == variation.randomise(kick, 0.5, locks=["layers.*.amp"], seed=7)
    original = validate(kick)
    for path, _ in numeric_specs(original):
        if path[:1] == ("layers",) and path[2] == "amp" or path == ("length",):
            assert get_path(first, path) == get_path(original, path)
    assert first != original


def test_no_amount_means_no_change():
    kick = validate(presets.preset("kick"))
    assert variation.randomise(kick, 0.0, seed=1) == kick


def test_length_varies_only_when_unlocked():
    kick = presets.preset("kick")
    lengths = {variation.randomise(kick, 0.8, locks=["!length"], seed=s)["length"] for s in range(5)}
    assert len(lengths) > 1


def test_evolve_names_each_variation():
    children = variation.evolve(presets.preset("pluck"), count=4, seed=2)
    assert [child["name"] for child in children] == ["pluck 1", "pluck 2", "pluck 3", "pluck 4"]
    assert len({str(child) for child in children}) == 4


def test_morphing_goes_from_one_sound_to_the_other():
    kick, snare = presets.preset("kick"), presets.preset("snare")
    assert variation.morph(kick, snare, 0)["layers"][0]["pitch"] == validate(kick)["layers"][0]["pitch"]
    assert variation.morph(kick, snare, 1)["layers"][0]["pitch"] == validate(snare)["layers"][0]["pitch"]
    halfway = variation.morph(kick, snare, 0.5)["layers"][0]["pitch"]
    assert 48 < halfway < 190


def test_morphing_different_engines_crossfades_the_layers():
    pad, bell = presets.preset("pad"), presets.preset("bell")
    halfway = variation.morph(pad, bell, 0.5)
    assert [layer["engine"] for layer in halfway["layers"]] == ["analog", "fm"]
    assert all(layer["level"] < 0.8 for layer in halfway["layers"])
    render(halfway)
