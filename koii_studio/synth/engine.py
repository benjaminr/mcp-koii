"""
Render a sound design to audio at the EP-133's rate.

Each layer makes a dry sound from its engine, follows its pitch envelope and
LFOs, goes through its own filter and amplitude envelope, and is placed in
the mix. The effects then run on the mix in order, the result is cleaned up
(DC removed, a short fade at the end) and normalised.
"""

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import numpy as np

from koii_studio.synth import dsp
from koii_studio.synth.edit import to_pcm
from koii_studio.synth.schema import DesignError, validate

RATE = dsp.RATE
END_FADE_SECONDS = 0.004

# Partial ratios and relative decays for the struck-resonator materials.
MATERIALS = {
    "marimba": ([1, 3.93, 9.24, 16.0], [1, 0.45, 0.2, 0.1], [1, 0.25, 0.08, 0.03]),
    "kalimba": ([1, 5.4, 11.2, 17.9], [1, 0.4, 0.25, 0.15], [1, 0.35, 0.12, 0.05]),
    "glass": ([1, 2.32, 4.25, 6.63, 9.38], [1, 0.8, 0.6, 0.45, 0.3], [1, 0.6, 0.4, 0.25, 0.15]),
    "bell": ([0.5, 1, 1.19, 1.56, 2, 2.66, 3.01], [1.6, 1, 0.8, 0.6, 0.5, 0.35, 0.3], [0.5, 1, 0.6, 0.5, 0.4, 0.3, 0.2]),
    "wood": ([1, 2.57, 4.88, 7.37], [1, 0.3, 0.12, 0.06], [1, 0.3, 0.1, 0.05]),
    "metal": ([1, 1.41, 2.15, 2.83, 3.75, 4.6], [1, 0.9, 0.8, 0.7, 0.6, 0.5], [1, 0.7, 0.6, 0.5, 0.4, 0.3]),
    "membrane": ([1, 1.59, 2.14, 2.3, 2.65, 2.92], [1, 0.5, 0.35, 0.3, 0.25, 0.2], [1, 0.5, 0.35, 0.3, 0.2, 0.15]),
}
# The 808's six square oscillators (Hz at tune 1) for cymbals and hats, and its two for the cowbell.
CLUSTERS = {"cymbal": [205.3, 304.4, 369.6, 522.7, 540.0, 800.0], "cowbell": [540.0, 800.0]}

SourceLoader = Callable[[str], Optional[np.ndarray]]


@dataclass
class Rendered:
    audio: np.ndarray        # (channels, frames), float32, peak-normalised
    design: Dict             # the validated design
    seconds: float

    @property
    def channels(self) -> int:
        return self.audio.shape[0]

    def pcm(self) -> bytes:
        """Interleaved 16-bit little-endian PCM, ready for the device."""
        return to_pcm(self.audio)


def _seed(design: Dict) -> int:
    """Noise is random, but the same design always renders the same way."""
    digest = hashlib.sha256(json.dumps(design, sort_keys=True).encode()).digest()
    return int.from_bytes(digest[:4], "little")


def _pitch_curve(layer: Dict, frames: int) -> np.ndarray:
    """Per-sample frequency: base pitch, swept down from the pitch-envelope start, plus pitch LFOs."""
    t = dsp.times(frames)
    env = layer["pitch_env"]
    semitones = env["amount"] * np.exp(-t / max(env["time"] / 1000, 1e-4) * 4.6)
    for index, lfo in enumerate(layer["lfos"]):
        if lfo["target"] == "pitch":
            semitones = semitones + 12 * lfo["depth"] * dsp.lfo(frames, lfo["shape"], lfo["rate"], lfo["fade"], index)
    return layer["pitch"] * 2 ** (semitones / 12)


# -- engines ---------------------------------------------------------------------------

def _analog(layer, frequency, frames, rng):
    p = layer["params"]
    voices = int(round(p["voices"]))
    out = np.zeros(frames)
    for voice in range(voices):
        spread = 0 if voices == 1 else (voice / (voices - 1) - 0.5) * 2
        detuned = frequency * 2 ** (spread * p["detune"] / 1200)
        out += dsp.oscillator(detuned, p["wave"], p["width"], rng.random() if voices > 1 else 0.0)
    out /= math.sqrt(voices)
    if p["sub"]:
        out += p["sub"] * dsp.oscillator(frequency / 2, "sine")
    return out


def _fm(layer, frequency, frames, rng):
    p = layer["params"]
    t = dsp.times(frames)
    index = p["index"] * np.exp(-t / (p["index_decay"] / 1000))
    phase = np.cumsum(frequency / RATE)
    modulator = np.sin(2 * np.pi * phase * p["mod_ratio"])
    if p["index2"]:
        modulator = modulator + p["index2"] / max(p["index"], 1e-3) * np.sin(2 * np.pi * phase * p["mod2_ratio"]) * \
            (index / max(p["index"], 1e-3))
    return np.sin(2 * np.pi * phase * p["ratio"] + index * modulator)


def _pluck(layer, frequency, frames, rng):
    """Karplus–Strong: a noise burst in a delay line one period long, filtered on each pass."""
    p = layer["params"]
    period = max(2, int(RATE / float(frequency[0])))
    excitation = rng.uniform(-1, 1, period)
    # Picking position: comb the excitation so some harmonics are missing, as on a real string.
    notch = max(1, int(period * p["pick"]))
    excitation = excitation - np.roll(excitation, notch) * 0.5
    blend = 0.5 + 0.49 * p["brightness"]          # how much of the newest sample is kept on each pass
    loss = 0.990 + 0.0099 * p["sustain"]
    line = excitation.copy()
    out = np.empty(frames)
    previous = 0.0
    for i in range(frames):
        index = i % period
        value = line[index]
        out[i] = value
        filtered = loss * (blend * value + (1 - blend) * previous)
        previous = value
        line[index] = filtered
    return out


def _modal(layer, frequency, frames, rng):
    p = layer["params"]
    ratios, amplitudes, decays = MATERIALS[p["material"]]
    t = dsp.times(frames)
    out = np.zeros(frames)
    for k, (ratio, amplitude, decay) in enumerate(zip(ratios, amplitudes, decays)):
        stretched = ratio * (1 + p["inharmonic"] * (k / max(1, len(ratios) - 1)))
        partial = frequency * stretched
        # Upper partials die faster with more damping, and are louder with a harder strike.
        life = p["decay"] / 1000 * decay * (1 - p["damping"] * min(0.9, k * 0.25))
        level = amplitude * (0.3 + p["hardness"] * 0.7) ** k
        out += level * np.sin(2 * np.pi * np.cumsum(partial / RATE)) * np.exp(-t / max(life, 1e-3))
    click = rng.uniform(-1, 1, frames) * np.exp(-t / 0.002) * p["hardness"] * 0.3
    return out + click


def _metal(layer, frequency, frames, rng):
    p = layer["params"]
    out = np.zeros(frames)
    for base in CLUSTERS[p["cluster"]]:
        out += dsp.oscillator(np.full(frames, base * p["tune"]), "square", phase0=rng.random())
    out /= len(CLUSTERS[p["cluster"]])
    if p["cluster"] == "cymbal":
        out = dsp.static_filter(out, "highpass", 6000, 0.7)
    else:
        out = dsp.static_filter(out, "bandpass", 1600 * p["tune"], 1.2) * 3
    return out


def _additive(layer, frequency, frames, rng):
    p = layer["params"]
    t = dsp.times(frames)
    phase = np.cumsum(frequency / RATE)
    out = np.zeros(frames)
    for harmonic in (1, 2, 3, 4, 5, 6, 8, 12, 16):
        level = p[f"h{harmonic}"]
        if level <= 0 or frequency[0] * harmonic > RATE / 2:
            continue
        fade = np.exp(-t * p["decay_tilt"] * (harmonic - 1) * 2.5)
        out += level * np.sin(2 * np.pi * phase * harmonic) * fade
    return out / max(1.0, sum(p[f"h{h}"] for h in (1, 2, 3, 4, 5, 6, 8, 12, 16)) * 0.5)


def _noise(layer, frequency, frames, rng):
    p = layer["params"]
    out = dsp.noise(frames, p["colour"], rng)
    bursts = int(round(p["bursts"]))
    if bursts > 1:
        t = dsp.times(frames)
        spacing = p["spacing"] / 1000
        gate = np.zeros(frames)
        for b in range(bursts - 1):
            start = b * spacing
            gate += ((t >= start) & (t < start + spacing)) * np.exp(-(t - start) / (spacing * 0.3))
        gate += (t >= (bursts - 1) * spacing)
        out = out * np.clip(gate, 0, 1)
    return out


def _sample(layer, frequency, frames, rng, sources: Optional[SourceLoader]):
    p = layer["params"]
    audio = sources(p["source"]) if sources and p["source"] else None
    if audio is None:
        raise DesignError(f"the sample layer's source '{p['source']}' isn't loaded; record or load a sound first")
    mono = audio.mean(axis=0) if audio.ndim == 2 else audio
    start, end = int(p["start"] * len(mono)), max(int(p["end"] * len(mono)), int(p["start"] * len(mono)) + 1)
    region = mono[start:end]
    if p["reverse"] == "yes":
        region = region[::-1]
    # Pitch relative to C4 (261.63 Hz): the layer's pitch transposes the sample.
    ratio = frequency / 261.63
    if p["mode"] == "play":
        position = np.cumsum(ratio) - ratio[0]
        return np.interp(position, np.arange(len(region)), region, right=0.0)
    out = np.zeros(frames)
    grain = max(8, int(p["grain"] / 1000 * RATE))
    window = np.hanning(grain)
    count = max(1, int(frames / RATE * p["density"]))
    for g in range(count):
        at = int(g / count * frames)
        centre = (at / frames) + (rng.random() - 0.5) * p["spray"]
        source_at = int(np.clip(centre, 0, 1) * max(1, len(region) - grain))
        shift = 2 ** (rng.uniform(-1, 1) * p["grain_pitch"] / 12) * float(ratio[min(at, frames - 1)])
        read = source_at + np.arange(grain) * shift
        piece = np.interp(read, np.arange(len(region)), region, right=0.0) * window
        stop = min(frames, at + grain)
        out[at:stop] += piece[: stop - at]
    return out / max(1.0, count * grain / max(frames, 1) * 0.5)


ENGINES = {"analog": _analog, "fm": _fm, "pluck": _pluck, "modal": _modal, "metal": _metal,
           "additive": _additive, "noise": _noise}


# -- rendering --------------------------------------------------------------------------

def _layer_audio(layer: Dict, frames: int, rng: np.random.Generator, sources: Optional[SourceLoader]) -> np.ndarray:
    delay = int(layer["delay"] / 1000 * RATE)
    length = max(0, frames - delay)
    if length == 0:
        return np.zeros(frames)
    frequency = _pitch_curve(layer, length)
    if layer["engine"] == "sample":
        dry = _sample(layer, frequency, length, rng, sources)
    else:
        dry = ENGINES[layer["engine"]](layer, frequency, length, rng)
    dry = np.nan_to_num(dry)

    filt = layer["filter"]
    if filt["type"] != "off":
        t = dsp.times(length)
        progress = np.clip(t / (filt["time"] / 1000), 0, 1)
        cutoff = filt["cutoff"] * (filt["end"] / filt["cutoff"]) ** progress
        for index, lfo in enumerate(layer["lfos"]):
            if lfo["target"] == "cutoff":
                cutoff = cutoff * 2 ** (4 * lfo["depth"] * dsp.lfo(length, lfo["shape"], lfo["rate"], lfo["fade"], 10 + index))
        dry = dsp.sweep_filter(dry, filt["type"], np.clip(cutoff, 20, RATE * 0.45), filt["resonance"])

    amp = layer["amp"]
    gain = dsp.envelope(length, amp["attack"], amp["hold"], amp["decay"], amp["sustain"], amp["release"], amp["curve"])
    for index, lfo in enumerate(layer["lfos"]):
        if lfo["target"] == "amp":
            gain = gain * (1 - lfo["depth"] * 0.5 * (1 + dsp.lfo(length, lfo["shape"], lfo["rate"], lfo["fade"], 20 + index)))
    shaped = dry * gain * layer["level"]
    return np.concatenate([np.zeros(delay), shaped])


def _pan(mono: np.ndarray, layer: Dict, frames: int) -> np.ndarray:
    position = np.full(frames, layer["pan"])
    for index, lfo in enumerate(layer["lfos"]):
        if lfo["target"] == "pan":
            position = position + lfo["depth"] * dsp.lfo(frames, lfo["shape"], lfo["rate"], lfo["fade"], 30 + index)
    angle = (np.clip(position, -1, 1) + 1) * np.pi / 4
    return np.stack([mono * np.cos(angle), mono * np.sin(angle)])


def render(design: Dict, sources: Optional[SourceLoader] = None) -> Rendered:
    """Render a design (validated first). Same design, same sound."""
    design = validate(design)
    frames = max(1, int(round(design["length"] * RATE)))
    rng = np.random.default_rng(_seed(design))
    channels = 2 if design["stereo"] else 1
    mix = np.zeros((channels, frames))
    for layer in design["layers"]:
        audio = _layer_audio(layer, frames, rng, sources)
        mix += _pan(audio, layer, frames) if channels == 2 else audio[np.newaxis, :]
    signal_ = mix if channels == 2 else mix[0]
    for effect in design["effects"]:
        signal_ = np.nan_to_num(dsp.apply_effect(signal_, effect, rng))
    audio = signal_ if signal_.ndim == 2 else signal_[np.newaxis, :]

    audio = dsp.static_filter(audio, "highpass", 12, 0.707)  # remove DC
    fade = min(frames, int(END_FADE_SECONDS * RATE))
    if fade:
        audio[:, -fade:] *= np.linspace(1, 0, fade)
    peak = float(np.max(np.abs(audio)))
    if peak > 1e-6:
        audio = audio * (10 ** (design["normalise"] / 20) / peak)
    return Rendered(audio=audio.astype(np.float32), design=design, seconds=frames / RATE)
