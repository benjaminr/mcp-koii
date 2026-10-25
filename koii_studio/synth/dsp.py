"""
Signal processing for the sound designer: envelopes, LFOs, band-limited
oscillators, sweeping filters and the effects. Everything works on numpy
float arrays at the device rate; stereo signals are shaped (2, frames).
"""

import math
from typing import Dict, Optional

import numpy as np
from scipy import signal

from koii_studio.synth.schema import DEVICE_RATE

RATE = DEVICE_RATE
FILTER_BLOCK = 64       # samples per coefficient update when a filter sweeps


def times(frames: int) -> np.ndarray:
    return np.arange(frames) / RATE


# -- envelopes and modulators -------------------------------------------------------

def envelope(frames: int, attack: float, hold: float, decay: float, sustain: float, release: float,
             curve: float, gate: Optional[float] = None) -> np.ndarray:
    """
    Attack, hold, decay to sustain, then release starting at `gate` seconds (by
    default so the release ends with the sample). Times in milliseconds;
    `curve` 0 is linear, 1 sharply exponential.
    """
    t = times(frames)
    attack_s, hold_s, decay_s, release_s = attack / 1000, hold / 1000, decay / 1000, release / 1000
    length = frames / RATE
    gate = length - release_s if gate is None else gate
    gate = max(0.0, gate)
    shape = 1 + curve * 7  # exponent for the falling segments

    def fall(x: np.ndarray) -> np.ndarray:  # 1 -> 0 over x in 0..1
        x = np.clip(x, 0, 1)
        return (1 - x) ** shape

    env = np.zeros(frames)
    rising = t < attack_s
    env[rising] = (t[rising] / attack_s) ** (1 / (1 + curve)) if attack_s > 0 else 1
    held = (t >= attack_s) & (t < attack_s + hold_s)
    env[held] = 1
    after = t >= attack_s + hold_s
    since = t[after] - attack_s - hold_s
    env[after] = sustain + (1 - sustain) * fall(since / decay_s)
    # Release from whatever level the envelope has reached at the gate.
    released = t >= gate
    if released.any():
        level_at_gate = np.interp(gate, t, env) if gate < length else 0.0
        env[released] = level_at_gate * fall((t[released] - gate) / release_s)
    return env


def lfo(frames: int, shape: str, rate: float, fade: float, seed: int = 0) -> np.ndarray:
    """A low-frequency oscillator in −1..1, faded in over `fade` milliseconds."""
    t = times(frames)
    phase = (t * rate) % 1.0
    if shape == "sine":
        wave = np.sin(2 * np.pi * phase)
    elif shape == "triangle":
        wave = 1 - 4 * np.abs(phase - 0.5)
    elif shape == "square":
        wave = np.where(phase < 0.5, 1.0, -1.0)
    elif shape == "saw":
        wave = 2 * phase - 1
    else:  # random steps, smoothed a little
        rng = np.random.default_rng(seed)
        steps = rng.uniform(-1, 1, int(t[-1] * rate) + 2 if frames else 1)
        wave = steps[np.floor(t * rate).astype(int)]
        wave = signal.lfilter([0.02], [1, -0.98], wave)
    if fade > 0:
        wave = wave * np.clip(t / (fade / 1000), 0, 1)
    return wave


# -- oscillators -------------------------------------------------------------------

def _polyblep(phase: np.ndarray, step: np.ndarray) -> np.ndarray:
    """PolyBLEP correction that softens the steps in saw and square waves (less aliasing)."""
    out = np.zeros_like(phase)
    low = phase < step
    x = phase[low] / step[low]
    out[low] = x + x - x * x - 1
    high = phase > 1 - step
    x = (phase[high] - 1) / step[high]
    out[high] = x * x + x + x + 1
    return out


def oscillator(frequency: np.ndarray, wave: str, width: float = 0.5, phase0: float = 0.0) -> np.ndarray:
    """A band-limited waveform following a per-sample frequency curve."""
    step = np.clip(frequency / RATE, 1e-6, 0.49)
    phase = (phase0 + np.cumsum(step) - step[0]) % 1.0
    if wave == "sine":
        return np.sin(2 * np.pi * phase)
    if wave == "triangle":
        return 1 - 4 * np.abs(phase - 0.5)
    if wave == "saw":
        return (2 * phase - 1) - _polyblep(phase, step)
    duty = 0.5 if wave == "square" else width
    square = np.where(phase < duty, 1.0, -1.0)
    square += _polyblep(phase, step)
    square -= _polyblep((phase - duty) % 1.0, step)
    return square


# -- filters ------------------------------------------------------------------------

def biquad(kind: str, frequency: float, q: float, gain_db: float = 0.0):
    """RBJ cookbook biquad coefficients (b, a)."""
    frequency = min(max(frequency, 10.0), RATE * 0.49)
    w = 2 * math.pi * frequency / RATE
    cos_w, sin_w = math.cos(w), math.sin(w)
    alpha = sin_w / (2 * q)
    a_gain = 10 ** (gain_db / 40)
    if kind == "lowpass":
        b = [(1 - cos_w) / 2, 1 - cos_w, (1 - cos_w) / 2]
        a = [1 + alpha, -2 * cos_w, 1 - alpha]
    elif kind == "highpass":
        b = [(1 + cos_w) / 2, -(1 + cos_w), (1 + cos_w) / 2]
        a = [1 + alpha, -2 * cos_w, 1 - alpha]
    elif kind == "bandpass":
        b = [alpha, 0, -alpha]
        a = [1 + alpha, -2 * cos_w, 1 - alpha]
    elif kind == "notch":
        b = [1, -2 * cos_w, 1]
        a = [1 + alpha, -2 * cos_w, 1 - alpha]
    elif kind == "peak":
        b = [1 + alpha * a_gain, -2 * cos_w, 1 - alpha * a_gain]
        a = [1 + alpha / a_gain, -2 * cos_w, 1 - alpha / a_gain]
    elif kind == "lowshelf":
        root = 2 * math.sqrt(a_gain) * alpha
        b = [a_gain * ((a_gain + 1) - (a_gain - 1) * cos_w + root), 2 * a_gain * ((a_gain - 1) - (a_gain + 1) * cos_w),
             a_gain * ((a_gain + 1) - (a_gain - 1) * cos_w - root)]
        a = [(a_gain + 1) + (a_gain - 1) * cos_w + root, -2 * ((a_gain - 1) + (a_gain + 1) * cos_w),
             (a_gain + 1) + (a_gain - 1) * cos_w - root]
    elif kind == "highshelf":
        root = 2 * math.sqrt(a_gain) * alpha
        b = [a_gain * ((a_gain + 1) + (a_gain - 1) * cos_w + root), -2 * a_gain * ((a_gain - 1) + (a_gain + 1) * cos_w),
             a_gain * ((a_gain + 1) + (a_gain - 1) * cos_w - root)]
        a = [(a_gain + 1) - (a_gain - 1) * cos_w + root, 2 * ((a_gain - 1) - (a_gain + 1) * cos_w),
             (a_gain + 1) - (a_gain - 1) * cos_w - root]
    else:
        raise ValueError(f"unknown filter {kind}")
    return np.array(b) / a[0], np.array(a) / a[0]


def sweep_filter(x: np.ndarray, kind: str, cutoff: np.ndarray, q: float) -> np.ndarray:
    """Filter whose cutoff follows a per-sample curve, updated every FILTER_BLOCK samples."""
    out = np.empty_like(x)
    state = np.zeros(2)
    for start in range(0, len(x), FILTER_BLOCK):
        block = slice(start, start + FILTER_BLOCK)
        b, a = biquad(kind, float(cutoff[start]), q)
        out[block], state = signal.lfilter(b, a, x[block], zi=state)
    return out


def static_filter(x: np.ndarray, kind: str, frequency: float, q: float = 0.707, gain_db: float = 0.0) -> np.ndarray:
    b, a = biquad(kind, frequency, q, gain_db)
    return signal.lfilter(b, a, x, axis=-1)


# -- noise ---------------------------------------------------------------------------

def noise(frames: int, colour: str, rng: np.random.Generator) -> np.ndarray:
    white = rng.standard_normal(frames)
    if colour == "white":
        out = white
    elif colour == "pink":   # Paul Kellet's filter approximation
        b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
        a = [1, -2.494956002, 2.017265875, -0.522189400]
        out = signal.lfilter(b, a, white)
    elif colour == "brown":
        out = signal.lfilter([1], [1, -0.995], white)
    elif colour == "blue":
        out = np.diff(white, prepend=0.0)
    else:  # crackle: sparse clicks
        out = np.where(rng.random(frames) < 0.002, rng.standard_normal(frames) * 4, 0.0)
    peak = np.max(np.abs(out)) or 1.0
    return out / peak


# -- effects -------------------------------------------------------------------------

def _per_channel(x: np.ndarray, function) -> np.ndarray:
    return np.stack([function(channel) for channel in x]) if x.ndim == 2 else function(x)


def effect_eq(x, p):
    def run(channel):
        channel = static_filter(channel, "lowshelf", p["low_freq"], 0.707, p["low"])
        channel = static_filter(channel, "peak", p["mid_freq"], p["mid_q"], p["mid"])
        return static_filter(channel, "highshelf", p["high_freq"], 0.707, p["high"])
    return _per_channel(x, run)


def effect_drive(x, p):
    k = 1 + p["amount"] * 24
    if p["mode"] == "tanh":
        wet = np.tanh(k * x) / np.tanh(k)
    elif p["mode"] == "fold":
        wet = np.sin(np.clip(k * x, -50, 50) * np.pi / 2)
    elif p["mode"] == "clip":
        level = 1 / k
        wet = np.clip(x, -level, level) / level
    else:  # tube: asymmetric, warmer
        wet = np.where(x >= 0, np.tanh(k * x), np.tanh(k * 0.6 * x) / 0.6) / np.tanh(k)
    return x + (wet - x) * p["mix"]


def effect_lofi(x, p, rng):
    hold = max(1, int(round(RATE / p["rate"])))
    def run(channel):
        held = np.repeat(channel[::hold], hold)[: len(channel)]
        levels = 2 ** (int(p["bits"]) - 1)
        crushed = np.round(held * levels) / levels
        if p["noise"]:
            crushed = crushed + rng.standard_normal(len(channel)) * p["noise"] * 0.1
        return channel + (crushed - channel) * p["mix"]
    return _per_channel(x, run)


def _follower(level: np.ndarray, attack_ms: float, release_ms: float) -> np.ndarray:
    attack = math.exp(-1 / (RATE * attack_ms / 1000))
    release = math.exp(-1 / (RATE * release_ms / 1000))
    out = np.empty_like(level)
    current = 0.0
    for i, value in enumerate(level):
        coefficient = attack if value > current else release
        current = coefficient * current + (1 - coefficient) * value
        out[i] = current
    return out


def effect_compressor(x, p):
    mono = np.max(np.abs(x), axis=0) if x.ndim == 2 else np.abs(x)
    level = _follower(mono, p["attack"], p["release"])
    level_db = 20 * np.log10(np.maximum(level, 1e-6))
    over = np.maximum(0, level_db - p["threshold"])
    gain_db = -over * (1 - 1 / p["ratio"]) + p["makeup"]
    return x * 10 ** (gain_db / 20)


def effect_transient(x, p):
    mono = np.max(np.abs(x), axis=0) if x.ndim == 2 else np.abs(x)
    fast = _follower(mono, 0.5, 20)
    slow = _follower(mono, 15, 120)
    burst = np.clip((fast - slow) / (slow + 1e-4), 0, 4)
    tail = np.clip((slow - fast) / (slow + 1e-4), 0, 1)
    gain = 1 + p["attack"] * burst * 0.5 + p["sustain"] * tail
    return x * np.clip(gain, 0, 4)


def _fractional_delay(channel: np.ndarray, delay_samples: np.ndarray) -> np.ndarray:
    index = np.arange(len(channel)) - delay_samples
    return np.interp(index, np.arange(len(channel)), channel, left=0.0)


def effect_chorus(x, p):
    t = times(x.shape[-1])
    base = 0.012 * RATE
    swing = 0.006 * RATE * p["depth"]
    def voice(channel, offset):
        return _fractional_delay(channel, base + swing * np.sin(2 * np.pi * p["rate"] * t + offset))
    if x.ndim == 2:
        wet = np.stack([voice(x[0], 0), voice(x[1], np.pi / 2)])
    else:
        wet = 0.5 * (voice(x, 0) + voice(x, np.pi * 2 / 3))
    return x * (1 - p["mix"] * 0.5) + wet * p["mix"]


def effect_delay(x, p):
    samples = max(1, int(p["time"] / 1000 * RATE))
    def run(channel):
        wet = np.zeros_like(channel)
        tap = channel.copy()
        for repeat in range(1, 32):
            tap = static_filter(tap, "lowpass", 800 + p["tone"] * 15000) * (p["feedback"] if repeat > 1 else 1)
            shift = samples * repeat
            if shift >= len(channel) or np.max(np.abs(tap)) < 1e-4:
                break
            wet[shift:] += tap[: len(channel) - shift]
        return channel + wet * p["mix"]
    return _per_channel(x, run)


def effect_reverb(x, p, rng):
    """Convolution with a generated impulse response: decaying noise that darkens as it fades."""
    frames = x.shape[-1]
    length = min(int(p["decay"] * RATE * 1.2), frames * 2, int(10 * RATE))
    t = times(length)
    channels = 2 if x.ndim == 2 else 1
    responses = []
    for c in range(channels):
        tail = rng.standard_normal(length) * np.exp(-6.9 * t / p["decay"])
        # Darken progressively: blend a heavily low-passed copy in over time.
        dark = static_filter(tail, "lowpass", 900 + 9000 * (1 - p["damping"]))
        blend = np.clip(t / (p["decay"] * 0.6), 0, 1) * p["damping"]
        tail = tail * (1 - blend) + dark * blend
        # Early reflections scale with size.
        for tap in range(6):
            when = int((0.004 + rng.random() * 0.04 * (0.3 + p["size"])) * RATE)
            if when < length:
                tail[when] += (0.6 - tap * 0.08) * rng.choice([-1, 1])
        predelay = int(p["predelay"] / 1000 * RATE)
        tail = np.concatenate([np.zeros(predelay), tail])[:length]
        responses.append(tail / (np.sqrt(np.sum(tail ** 2)) + 1e-9))
    dry = x if x.ndim == 2 else x[np.newaxis, :]
    wet = np.stack([signal.fftconvolve(dry[c % dry.shape[0]], responses[c])[:frames] for c in range(channels)])
    wet = wet if x.ndim == 2 else wet[0]
    scale = (np.sqrt(np.mean(x ** 2)) + 1e-9) / (np.sqrt(np.mean(wet ** 2)) + 1e-9)
    return x * (1 - p["mix"] * 0.5) + wet * scale * p["mix"]


def effect_width(x, p):
    if x.ndim == 1:
        return x
    left, right = x
    if p["haas"] > 0:
        right = _fractional_delay(right, np.full(len(right), p["haas"] / 1000 * RATE))
    mid, side = (left + right) / 2, (left - right) / 2 * p["amount"]
    return np.stack([mid + side, mid - side])


def apply_effect(x: np.ndarray, effect: Dict, rng: np.random.Generator) -> np.ndarray:
    kind = effect["type"]
    if kind == "lofi":
        return effect_lofi(x, effect, rng)
    if kind == "reverb":
        return effect_reverb(x, effect, rng)
    return {"eq": effect_eq, "drive": effect_drive, "compressor": effect_compressor, "transient": effect_transient,
            "chorus": effect_chorus, "delay": effect_delay, "width": effect_width}[kind](x, effect)
