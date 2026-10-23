"""
Measuring sounds: pitch (YIN), loudness, brightness, decay, spectra for
display, seamless loop points, and similarity to the factory library.

These are how koii checks its own sounds (it can't listen), and how the
designer shows what a sound is doing.
"""

import math
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import signal

from koii.synth.dsp import RATE, static_filter

NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
DISPLAY_BANDS = 64
SPECTROGRAM_FRAMES = 160
FEATURE_BANDS = (60, 150, 400, 1000, 2500, 6000, 12000)


def mono(audio: np.ndarray) -> np.ndarray:
    return audio.mean(axis=0) if audio.ndim == 2 else audio


def note_for(frequency: float) -> Tuple[int, float]:
    """(nearest MIDI note, cents above it) for a frequency."""
    exact = 69 + 12 * math.log2(frequency / 440)
    note = int(round(exact))
    return note, (exact - note) * 100


def note_name(note: int) -> str:
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


# -- pitch ------------------------------------------------------------------------------

def yin(frame: np.ndarray, low: float = 30.0, high: float = 2000.0, threshold: float = 0.12) -> Tuple[Optional[float], float]:
    """YIN pitch estimate for one frame: (frequency or None, confidence 0..1)."""
    max_lag = min(len(frame) // 2, int(RATE / low))
    min_lag = max(2, int(RATE / high))
    if max_lag <= min_lag + 2:
        return None, 0.0
    frame = frame - frame.mean()
    window = len(frame) - max_lag
    # Difference function, then cumulative-mean normalisation (the core of YIN).
    diff = np.empty(max_lag)
    reference = frame[:window]
    for lag in range(max_lag):
        gap = reference - frame[lag:lag + window]
        diff[lag] = np.dot(gap, gap)
    cumulative = np.cumsum(diff[1:])
    normalised = np.ones(max_lag)
    normalised[1:] = diff[1:] * np.arange(1, max_lag) / np.maximum(cumulative, 1e-12)
    candidates = np.where(normalised[min_lag:] < threshold)[0]
    if len(candidates):
        lag = candidates[0] + min_lag
        while lag + 1 < max_lag and normalised[lag + 1] < normalised[lag]:
            lag += 1
    else:
        lag = int(np.argmin(normalised[min_lag:]) + min_lag)
    confidence = float(np.clip(1 - normalised[lag], 0, 1))
    # Parabolic interpolation for sub-sample accuracy.
    if 1 <= lag < max_lag - 1:
        a, b, c = normalised[lag - 1], normalised[lag], normalised[lag + 1]
        denominator = a - 2 * b + c
        # A flat curve (noise, silence) can put the vertex anywhere; never move more than a sample.
        shift = 0.5 * (a - c) / denominator if denominator > 1e-9 else 0.0
        lag = lag + float(np.clip(shift, -1.0, 1.0))
    frequency = RATE / lag
    if not low <= frequency <= high:
        return None, 0.0
    return frequency, confidence


def detect_pitch(audio: np.ndarray) -> Dict:
    """Pitch of the steadiest part of a sound (after the attack). Confidence below ~0.7 means unpitched."""
    x = mono(audio)
    frame_size = 4096
    if len(x) < frame_size // 2:
        return {"frequency": None, "confidence": 0.0}
    peak_at = int(np.argmax(np.abs(x)))
    estimates = []
    for start in range(min(peak_at + int(0.03 * RATE), max(0, len(x) - frame_size)),
                       max(1, len(x) - frame_size // 2), frame_size // 2):
        frame = x[start:start + frame_size]
        if len(frame) < frame_size // 2 or np.sqrt(np.mean(frame ** 2)) < 1e-3:
            continue
        frequency, confidence = yin(frame)
        if frequency:
            estimates.append((confidence, frequency))
        if len(estimates) >= 6:
            break
    if not estimates:
        return {"frequency": None, "confidence": 0.0}
    good = [f for c, f in estimates if c > 0.6] or [max(estimates)[1]]
    frequency = float(np.median(good))
    confidence = float(np.median([c for c, _ in estimates]))
    note, cents = note_for(frequency)
    return {"frequency": frequency, "confidence": confidence, "note": note, "name": note_name(note),
            "cents": round(cents, 1) + 0.0}   # + 0.0 turns -0.0 into 0.0


# -- loudness, brightness, envelope ---------------------------------------------------------

def loudness(audio: np.ndarray) -> Dict:
    x = audio if audio.ndim == 2 else audio[np.newaxis, :]
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x ** 2)))
    # Approximate integrated loudness: K-weighting (high shelf + high-pass), no gating.
    weighted = static_filter(static_filter(x, "highshelf", 1500, 0.707, 4.0), "highpass", 38, 0.5)
    power = float(np.mean(np.sum(weighted ** 2, axis=0) / x.shape[0] * 2 if x.shape[0] == 2 else weighted[0] ** 2))
    return {
        "peak_db": 20 * math.log10(peak) if peak > 0 else -120.0,
        "rms_db": 20 * math.log10(rms) if rms > 0 else -120.0,
        "lufs": -0.691 + 10 * math.log10(power) if power > 0 else -120.0,
    }


def brightness(audio: np.ndarray) -> float:
    """Spectral centroid in Hz: higher means brighter."""
    x = mono(audio)
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    frequencies = np.fft.rfftfreq(len(x), 1 / RATE)
    total = spectrum.sum()
    return float((spectrum * frequencies).sum() / total) if total else 0.0


def envelope_times(audio: np.ndarray) -> Dict:
    """
    Attack and decay of the first sound, in seconds: attack from where it starts (10% of
    the loudest level) to where it reaches 90% of its own peak (the top it reaches before
    falling to half), decay from there to −40 dB. Measuring the first sound, not the
    loudest moment, keeps a recording of several hits honest.
    """
    x = np.abs(mono(audio))
    smooth = signal.lfilter([0.01], [1, -0.99], x)
    peak = float(np.max(smooth)) if len(smooth) else 0.0
    if peak <= 0:
        return {"attack": 0.0, "decay": 0.0}
    start = int(np.argmax(smooth >= peak * 0.1))
    rest = smooth[start:]
    falling = np.where(rest < 0.5 * np.maximum.accumulate(rest))[0]
    first_sound = rest[:falling[0]] if len(falling) else rest
    own_peak = float(np.max(first_sound))
    top = start + int(np.argmax(first_sound >= own_peak * 0.9))
    below = np.where(smooth[top:] < smooth[top] * 0.01)[0]
    decay = (below[0] if len(below) else len(smooth) - top) / RATE
    return {"attack": (top - start) / RATE, "decay": float(decay)}


# -- display data -----------------------------------------------------------------------------

SPECTRUM_LOW, SPECTRUM_HIGH = 25.0, 20000.0


def _band_edges(count: int, low: float = SPECTRUM_LOW, high: float = SPECTRUM_HIGH) -> np.ndarray:
    return low * (high / low) ** (np.arange(count + 1) / count)


def spectrum_bands(audio: np.ndarray, count: int = DISPLAY_BANDS) -> List[float]:
    """Average level per log-spaced band in dB, for drawing."""
    x = mono(audio)
    size = 1 << int(math.ceil(math.log2(max(len(x), 2048))))
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x)), size)) / max(len(x), 1)
    frequencies = np.fft.rfftfreq(size, 1 / RATE)
    edges = _band_edges(count)
    levels = []
    for low, high in zip(edges[:-1], edges[1:]):
        band = spectrum[(frequencies >= low) & (frequencies < high)]
        value = float(np.sqrt(np.mean(band ** 2))) if len(band) else 0.0
        levels.append(round(20 * math.log10(value) if value > 0 else -120.0, 1))
    return levels


def spectrogram(audio: np.ndarray, frames: int = SPECTROGRAM_FRAMES, bands: int = 48) -> List[List[float]]:
    """Level in dB per (time slice, log band), for drawing."""
    x = mono(audio)
    size = 1024
    hop = max(1, (len(x) - size) // max(1, frames - 1)) if len(x) > size else 1
    padded = np.concatenate([x, np.zeros(size)])
    window = np.hanning(size)
    frequencies = np.fft.rfftfreq(size, 1 / RATE)
    edges = _band_edges(bands, 40, 20000)
    masks = [(frequencies >= a) & (frequencies < b) for a, b in zip(edges[:-1], edges[1:])]
    out = []
    for i in range(min(frames, max(1, len(x) // hop))):
        spectrum = np.abs(np.fft.rfft(padded[i * hop:i * hop + size] * window)) / size
        row = []
        for mask in masks:
            band = spectrum[mask]
            value = float(band.max()) if len(band) else 0.0
            row.append(round(20 * math.log10(value) if value > 0 else -120.0, 1))
        out.append(row)
    return out


# -- loops ------------------------------------------------------------------------------------

LOOP_TOLERANCE = 0.02     # how much worse than the best match a longer loop may be


def find_loop(audio: np.ndarray, frequency: Optional[float]) -> Optional[Dict]:
    """
    A seamless loop for a sustaining sound: a stretch in the steady part whose
    end matches its start, both on rising zero crossings, as a whole number of
    periods when the pitch is known. Returns frames {start, end, quality}.
    """
    x = mono(audio)
    frames = len(x)
    if frames < RATE * 0.15:
        return None
    period = RATE / frequency if frequency else RATE / 100
    rising = np.where((x[:-1] < 0) & (x[1:] >= 0))[0]
    if len(rising) < 4:
        return None
    window = int(max(period * 2, 0.01 * RATE))
    candidates = []
    region_start, region_end = int(frames * 0.35), int(frames * 0.85)
    starts = rising[(rising > region_start) & (rising < region_start + period * 8)]
    for start in starts[:12]:
        target_lengths = [int(round(period * n)) for n in range(4, 400)] if frequency else [int(0.1 * RATE * n) for n in range(1, 8)]
        for target in target_lengths:
            end_guess = start + target
            if end_guess + window >= region_end:
                break
            # Snap to the nearest rising zero crossing.
            nearest = rising[np.argmin(np.abs(rising - end_guess))]
            if nearest <= start + window or nearest + window >= frames:
                continue
            a, b = x[start:start + window], x[nearest:nearest + window]
            score = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
            candidates.append((score, int(start), int(nearest)))
    if not candidates:
        return None
    # Any loop nearly as good as the best will do; of those, the longest sounds least mechanical.
    best_score = max(score for score, _, _ in candidates)
    good_enough = [c for c in candidates if c[0] >= best_score - LOOP_TOLERANCE]
    score, start, end = max(good_enough, key=lambda c: c[2] - c[1])
    return {"start": start, "end": end, "quality": round(score, 3)}


def crossfade_loop(audio: np.ndarray, loop: Dict, fade_seconds: float = 0.02) -> np.ndarray:
    """Blend the audio before the loop start into the loop end, so the jump back is inaudible."""
    out = audio.copy()
    fade = min(int(fade_seconds * RATE), loop["start"], (loop["end"] - loop["start"]) // 2)
    if fade < 8:
        return out
    ramp = np.linspace(0, 1, fade)
    for channel in (out if out.ndim == 2 else [out]):
        end = loop["end"]
        channel[end - fade:end] = channel[end - fade:end] * (1 - ramp) + channel[loop["start"] - fade:loop["start"]] * ramp
    return out


# -- similarity ---------------------------------------------------------------------------------

def features(audio: np.ndarray) -> List[float]:
    """A small fingerprint: band balance, brightness, attack, decay, noisiness and pitch."""
    x = mono(audio).astype(np.float64)
    if not len(x) or np.max(np.abs(x)) < 1e-6:
        return [0.0] * (len(FEATURE_BANDS) + 5)
    x = x / np.max(np.abs(x))
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    frequencies = np.fft.rfftfreq(len(x), 1 / RATE)
    edges = (20,) + FEATURE_BANDS + (RATE / 2,)
    energies = np.array([np.sum(spectrum[(frequencies >= a) & (frequencies < b)] ** 2) for a, b in zip(edges[:-1], edges[1:])])
    balance = list(np.log10(energies / (energies.sum() + 1e-12) + 1e-6))
    flatness = float(np.exp(np.mean(np.log(spectrum + 1e-12))) / (np.mean(spectrum) + 1e-12))
    times = envelope_times(x)
    pitch = detect_pitch(x) if len(x) > 4096 else {"frequency": None, "confidence": 0}
    pitched = math.log2(pitch["frequency"] / 55) if pitch["frequency"] and pitch["confidence"] > 0.7 else -1.0
    return balance + [math.log10(brightness(x) + 1), math.log10(times["attack"] + 1e-3),
                      math.log10(times["decay"] + 1e-3), flatness * 4, pitched]


def nearest(target: List[float], library: Dict[int, Dict], count: int = 3) -> List[Dict]:
    """The closest sounds in a {slot: {name, features}} library."""
    weights = np.array([1.0] * (len(FEATURE_BANDS) + 1) + [1.5, 0.8, 1.5, 1.0, 0.8])
    t = np.array(target)
    scored = []
    for slot, entry in library.items():
        distance = float(np.sqrt(np.sum(weights * (np.array(entry["features"]) - t) ** 2)))
        scored.append({"slot": slot, "name": entry["name"], "distance": round(distance, 3)})
    return sorted(scored, key=lambda s: s["distance"])[:count]


def analyse(audio: np.ndarray) -> Dict:
    """Everything the designer shows about a sound."""
    pitch = detect_pitch(audio)
    return {
        "seconds": audio.shape[-1] / RATE, "channels": audio.shape[0] if audio.ndim == 2 else 1,
        "pitch": pitch, **loudness(audio), "brightness": brightness(audio), **envelope_times(audio),
        "spectrum": spectrum_bands(audio), "spectrogram": spectrogram(audio),
        "spectrum_range": [SPECTRUM_LOW, SPECTRUM_HIGH], "spectrogram_range": [40, 20000],
    }
