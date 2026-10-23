"""
Editing recorded and loaded sounds: (channels, frames) float arrays at the
EP-133's 46,875 Hz.

Edits are plain JSON steps applied in order, so a source stays untouched and
its edits can be changed later:

    [{"op": "trim", "start": 0.12, "end": 1.4},
     {"op": "fade", "in": 0.005, "out": 0.08},
     {"op": "pitch", "semitones": -12, "keep_length": true},
     {"op": "normalise", "peak": -1}]
"""

import io
import wave
from fractions import Fraction
from math import gcd
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.signal import resample_poly

from koii.synth.schema import DEVICE_RATE, MAX_SECONDS, DesignError

MAX_SOURCE_SECONDS = 60.0     # recordings may be longer than a device sample; trim before uploading


# -- files and rates ----------------------------------------------------------------------------

def read_wav_bytes(data: bytes) -> Tuple[np.ndarray, int]:
    """A PCM WAV file (8, 16, 24 or 32-bit integer, or 32-bit float) as (channels, frames) floats."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise DesignError("that isn't a WAV file")
    if _wav_format(data) == 3:
        return _read_float_wav(data)
    with wave.open(io.BytesIO(data), "rb") as audio:
        channels, width, rate = audio.getnchannels(), audio.getsampwidth(), audio.getframerate()
        raw = audio.readframes(audio.getnframes())
    if width == 1:
        samples = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        samples = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif width == 3:
        bytes_ = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        ints = (bytes_[:, 0].astype(np.int32) | (bytes_[:, 1].astype(np.int32) << 8) | (bytes_[:, 2].astype(np.int32) << 16))
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        samples = ints.astype(np.float32) / (1 << 23)
    else:
        samples = np.frombuffer(raw, "<i4").astype(np.float32) / 2 ** 31
    return samples.reshape(-1, channels).T.copy(), rate


def _wav_format(data: bytes) -> int:
    """The WAV format tag: 1 is integer PCM, 3 is float, 0xFFFE is 'extensible' (look inside)."""
    position = 12
    while position + 8 <= len(data):
        chunk, size = data[position:position + 4], int.from_bytes(data[position + 4:position + 8], "little")
        if chunk == b"fmt ":
            tag = int.from_bytes(data[position + 8:position + 10], "little")
            if tag == 0xFFFE and size >= 26:
                tag = int.from_bytes(data[position + 32:position + 34], "little")
            return tag
        position += 8 + size + (size & 1)
    raise DesignError("the WAV file has no format chunk")


def _read_float_wav(data: bytes) -> Tuple[np.ndarray, int]:
    channels = rate = bits = None
    position, samples = 12, None
    while position + 8 <= len(data):
        chunk, size = data[position:position + 4], int.from_bytes(data[position + 4:position + 8], "little")
        body = data[position + 8:position + 8 + size]
        if chunk == b"fmt ":
            channels = int.from_bytes(body[2:4], "little")
            rate = int.from_bytes(body[4:8], "little")
            bits = int.from_bytes(body[14:16], "little")
        elif chunk == b"data":
            samples = body
        position += 8 + size + (size & 1)
    if not (channels and rate and samples is not None and bits in (32, 64)):
        raise DesignError("couldn't read that floating-point WAV file")
    values = np.frombuffer(samples[:len(samples) - len(samples) % (bits // 8 * channels)], "<f4" if bits == 32 else "<f8")
    return values.astype(np.float32).reshape(-1, channels).T.copy(), rate


def to_device_rate(audio: np.ndarray, rate: int) -> np.ndarray:
    """Resample to 46,875 Hz with a polyphase filter (48 kHz → 125/128, 44.1 kHz → 625/588)."""
    if rate == DEVICE_RATE:
        return audio.astype(np.float32)
    divisor = gcd(DEVICE_RATE, int(rate))
    up, down = DEVICE_RATE // divisor, int(rate) // divisor
    if up > 4096 or down > 4096:   # an unusual rate: go through 48 kHz
        audio = resample_poly(audio, 48000 // gcd(48000, rate), rate // gcd(48000, rate), axis=-1)
        up, down = 125, 128
    return resample_poly(audio, up, down, axis=-1).astype(np.float32)


def wav_bytes(audio: np.ndarray, rate: int = DEVICE_RATE) -> bytes:
    """A 16-bit WAV file, for previews and the sources store."""
    audio = audio if audio.ndim == 2 else audio[np.newaxis, :]
    pcm = (np.round(np.clip(audio, -1, 1).T * 32767).astype("<i2")).tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as file:
        file.setnchannels(audio.shape[0])
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(pcm)
    return out.getvalue()


def load_for_device(data: bytes, keep_stereo: bool = True) -> np.ndarray:
    """A WAV file's audio at 46,875 Hz, mono or stereo (more channels mix down)."""
    audio, rate = read_wav_bytes(data)
    if audio.shape[0] > 2 or (audio.shape[0] == 2 and not keep_stereo):
        audio = audio.mean(axis=0, keepdims=True)
    if audio.shape[1] / rate > MAX_SOURCE_SECONDS:
        raise DesignError(f"that's {audio.shape[1] / rate:.0f}s; sources can be at most {MAX_SOURCE_SECONDS:.0f}s")
    return to_device_rate(audio, rate)


# -- edits --------------------------------------------------------------------------------------

def _frames(seconds: float) -> int:
    return int(round(seconds * DEVICE_RATE))


def trim(audio: np.ndarray, start: float = 0.0, end: Optional[float] = None) -> np.ndarray:
    """Keep start–end seconds."""
    first = max(0, _frames(start))
    last = audio.shape[1] if end is None else min(audio.shape[1], _frames(end))
    if last - first < 32:
        raise DesignError("trim would leave almost nothing")
    return audio[:, first:last].copy()


def trim_silence(audio: np.ndarray, threshold_db: float = -50.0, keep: float = 0.002) -> np.ndarray:
    """Cut quiet audio from both ends, keeping a couple of milliseconds before the first sound."""
    level = np.max(np.abs(audio), axis=0)
    loud = np.where(level > 10 ** (threshold_db / 20))[0]
    if not len(loud):
        return audio.copy()
    first = max(0, loud[0] - _frames(keep))
    return audio[:, first:loud[-1] + 1].copy()


def fade(audio: np.ndarray, fade_in: float = 0.0, fade_out: float = 0.0) -> np.ndarray:
    out = audio.copy()
    frames = out.shape[1]
    length_in, length_out = min(frames, _frames(fade_in)), min(frames, _frames(fade_out))
    if length_in:
        out[:, :length_in] *= np.linspace(0, 1, length_in) ** 2
    if length_out:
        out[:, frames - length_out:] *= np.linspace(1, 0, length_out) ** 2
    return out


def reverse(audio: np.ndarray) -> np.ndarray:
    return audio[:, ::-1].copy()


def normalise(audio: np.ndarray, peak: float = -1.0) -> np.ndarray:
    loudest = float(np.max(np.abs(audio))) if audio.size else 0.0
    if loudest < 1e-9:
        return audio.copy()
    return (audio * (10 ** (peak / 20) / loudest)).astype(np.float32)


def gain(audio: np.ndarray, db: float) -> np.ndarray:
    return (audio * 10 ** (db / 20)).astype(np.float32)


def time_stretch(audio: np.ndarray, factor: float) -> np.ndarray:
    """
    Make a sound `factor` times as long without changing its pitch (WSOLA: overlapping
    windows, each nudged to where it lines up best with the last).
    """
    if not 0.25 <= factor <= 4:
        raise DesignError(f"stretch must be 0.25–4× (got {factor})")
    if abs(factor - 1) < 1e-3:
        return audio.copy()
    window = 2048
    hop_out = window // 4
    hop_in = hop_out / factor
    tolerance = 512
    mono = audio.mean(axis=0)
    frames_in = audio.shape[1]
    count = max(1, int((frames_in - window) / hop_in))
    out = np.zeros((audio.shape[0], count * hop_out + window), np.float32)
    weight = np.zeros(count * hop_out + window, np.float32)
    shape = np.hanning(window).astype(np.float32)
    previous_end = 0
    for index in range(count):
        nominal = int(index * hop_in)
        if index == 0:
            chosen = 0
        else:
            # Find the offset whose start best continues what was played last.
            reference = mono[previous_end:previous_end + hop_out]
            low, high = max(0, nominal - tolerance), min(frames_in - window, nominal + tolerance)
            if high <= low or len(reference) < hop_out:
                chosen = min(max(0, nominal), max(0, frames_in - window))
            else:
                search = mono[low:high + hop_out]
                scores = np.correlate(search, reference, mode="valid")
                chosen = low + int(np.argmax(scores))
        segment = audio[:, chosen:chosen + window]
        if segment.shape[1] < window:
            break
        position = index * hop_out
        out[:, position:position + window] += segment * shape
        weight[position:position + window] += shape
        previous_end = chosen + hop_out
    weight[weight < 1e-3] = 1.0
    return (out / weight)[:, :int(frames_in * factor)]


def pitch_shift(audio: np.ndarray, semitones: float, keep_length: bool = True) -> np.ndarray:
    """
    Shift pitch by semitones. keep_length=False is a tape-style shift (higher is shorter);
    keep_length=True stretches first, so the sound keeps its duration.
    """
    if not -36 <= semitones <= 36:
        raise DesignError(f"pitch shift must be within ±36 semitones (got {semitones})")
    if abs(semitones) < 1e-3:
        return audio.copy()
    ratio = 2 ** (semitones / 12)
    source = time_stretch(audio, ratio) if keep_length else audio
    # Resample by the ratio: play `ratio` times faster.
    up, down = _ratio_fraction(1 / ratio)
    return resample_poly(source, up, down, axis=-1).astype(np.float32)


def _ratio_fraction(ratio: float, limit: int = 1000) -> Tuple[int, int]:
    fraction = Fraction(ratio).limit_denominator(limit)
    return fraction.numerator, fraction.denominator


def to_mono(audio: np.ndarray) -> np.ndarray:
    return audio.mean(axis=0, keepdims=True)


# -- onsets and chopping ------------------------------------------------------------------------

def onsets(audio: np.ndarray, sensitivity: float = 0.5, min_gap: float = 0.06) -> List[int]:
    """
    Frames where new sounds start (spectral flux peaks). sensitivity 0–1: higher finds
    quieter hits. The first onset is always where the sound begins.
    """
    mono = audio.mean(axis=0)
    size, hop = 1024, 256
    if len(mono) < size * 2:
        return [0]
    window = np.hanning(size)
    count = 1 + (len(mono) - size) // hop
    frames = np.lib.stride_tricks.sliding_window_view(mono, size)[::hop][:count] * window
    spectrum = np.log1p(np.abs(np.fft.rfft(frames, axis=1)) * 10)
    flux = np.concatenate([[0], np.maximum(0, np.diff(spectrum, axis=0)).sum(axis=1)])
    flux /= flux.max() + 1e-9
    # Adaptive threshold: a local median plus a margin that sensitivity lowers.
    width = 16
    padded = np.pad(flux, width, mode="edge")
    local = np.array([np.median(padded[i:i + 2 * width + 1]) for i in range(len(flux))])
    threshold = local + (1 - sensitivity) * 0.5 + 0.02
    gap = max(1, int(min_gap * DEVICE_RATE / hop))
    found: List[int] = []
    for i in range(1, len(flux) - 1):
        if flux[i] > threshold[i] and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1]:
            if not found or i - found[-1] >= gap:
                found.append(i)
    starts = [_refine_onset(mono, i * hop, size) for i in found]
    first_sound = int(np.argmax(np.abs(mono) > 0.02 * np.max(np.abs(mono)))) if np.max(np.abs(mono)) > 0 else 0
    starts = [s for s in starts if s > first_sound + gap * hop]
    return [max(0, first_sound - 64)] + _snap_to_zero(mono, starts)


def _refine_onset(mono: np.ndarray, window_start: int, size: int, block: int = 64) -> int:
    """
    The flux only says a hit is somewhere in a 1024-frame window; find the block where the
    energy jumps most and start a couple of blocks before it, so the transient stays whole.
    """
    low = max(0, window_start - size // 4)
    high = min(len(mono), window_start + size + size // 4)
    blocks = (high - low) // block
    if blocks < 3:
        return low
    energy = np.sqrt(np.mean(mono[low:low + blocks * block].reshape(blocks, block) ** 2, axis=1)) + 1e-6
    rise = energy[1:] / energy[:-1]
    start = int(np.argmax(rise))
    # Walk back to the quiet before the hit: past any dip that is still well above the floor
    # (a clap's first bursts come before its loudest one).
    floor = float(np.min(energy[:start + 1]))
    while start > 0 and (energy[start - 1] < energy[start] or energy[start] > 4 * floor):
        start -= 1
    return low + start * block


def _snap_to_zero(mono: np.ndarray, positions: Sequence[int], reach: int = 256) -> List[int]:
    snapped = []
    for position in positions:
        low = max(1, position - reach)
        window = mono[low:position + 1]
        crossings = np.where(np.sign(window[:-1]) != np.sign(window[1:]))[0]
        snapped.append(int(low + crossings[-1] + 1) if len(crossings) else int(position))
    return snapped


def chop(audio: np.ndarray, starts: Sequence[int], fade_out: float = 0.004, limit: int = 48) -> List[np.ndarray]:
    """Slices from each start to the next (the last to the end), with a short fade on each end."""
    edges = sorted(set(int(s) for s in starts if 0 <= s < audio.shape[1]))[:limit]
    slices = []
    for index, start in enumerate(edges):
        end = edges[index + 1] if index + 1 < len(edges) else audio.shape[1]
        if end - start < 256:
            continue
        slices.append(fade(audio[:, start:end], 0.0005, fade_out))
    return slices


def chop_even(audio: np.ndarray, count: int) -> List[int]:
    """Starts for `count` equal slices: for loops cut on the beat."""
    if not 1 <= count <= 48:
        raise DesignError(f"slice count must be 1–48 (got {count})")
    return [int(round(i * audio.shape[1] / count)) for i in range(count)]


# -- edit chains --------------------------------------------------------------------------------

EDIT_OPS = {
    "trim": lambda audio, step: trim(audio, float(step.get("start", 0)), step.get("end")),
    "trim_silence": lambda audio, step: trim_silence(audio, float(step.get("threshold", -50))),
    "fade": lambda audio, step: fade(audio, float(step.get("in", 0)), float(step.get("out", 0))),
    "reverse": lambda audio, step: reverse(audio),
    "normalise": lambda audio, step: normalise(audio, float(step.get("peak", -1))),
    "gain": lambda audio, step: gain(audio, float(step.get("db", 0))),
    "pitch": lambda audio, step: pitch_shift(audio, float(step.get("semitones", 0)), bool(step.get("keep_length", True))),
    "stretch": lambda audio, step: time_stretch(audio, float(step.get("factor", 1))),
    "mono": lambda audio, step: to_mono(audio),
}


def apply_edits(audio: np.ndarray, edits: Sequence[Dict[str, Any]]) -> np.ndarray:
    """Apply edit steps in order. Raises DesignError naming the step that's wrong."""
    for index, step in enumerate(edits or []):
        if not isinstance(step, dict) or step.get("op") not in EDIT_OPS:
            raise DesignError(f"edit {index + 1}: op must be one of {', '.join(EDIT_OPS)}")
        try:
            audio = EDIT_OPS[step["op"]](audio, step)
        except (TypeError, ValueError) as error:   # DesignError is a ValueError too
            raise DesignError(f"edit {index + 1} ({step['op']}): {error}") from error
    if audio.shape[1] / DEVICE_RATE > MAX_SOURCE_SECONDS:
        raise DesignError(f"the edited sound is {audio.shape[1] / DEVICE_RATE:.1f}s; at most {MAX_SOURCE_SECONDS:.0f}s")
    return audio


def fits_device(audio: np.ndarray) -> bool:
    return audio.shape[1] / DEVICE_RATE <= MAX_SECONDS
