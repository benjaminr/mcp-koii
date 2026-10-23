"""
Audio files to the EP-133's format: 16-bit little-endian PCM at 46,875 Hz,
mono or stereo. Used when Claude uploads a WAV from disk (the browser does
its own conversion).

Resampling uses a windowed-sinc (Lanczos) filter, which is plenty for short
samples and needs no extra dependencies.
"""

import math
import wave
from pathlib import Path
from typing import List, Tuple

DEVICE_RATE = 46875
LANCZOS_LOBES = 8


def read_wav(path: Path) -> Tuple[List[List[float]], int]:
    """A PCM WAV file as per-channel samples in -1..1, plus its sample rate."""
    with wave.open(str(path), "rb") as audio:
        channels, width, rate = audio.getnchannels(), audio.getsampwidth(), audio.getframerate()
        raw = audio.readframes(audio.getnframes())
    if width not in (1, 2, 3, 4):
        raise ValueError(f"{path.name}: unsupported sample width ({width * 8}-bit)")
    scale = float(2 ** (8 * width - 1))
    frames = len(raw) // (width * channels)
    data: List[List[float]] = [[0.0] * frames for _ in range(channels)]
    for frame in range(frames):
        for channel in range(channels):
            start = (frame * channels + channel) * width
            chunk = raw[start:start + width]
            value = chunk[0] - 128 if width == 1 else int.from_bytes(chunk, "little", signed=True)
            data[channel][frame] = value / (128.0 if width == 1 else scale)
    return data, rate


def resample(samples: List[float], source_rate: int, target_rate: int = DEVICE_RATE) -> List[float]:
    if source_rate == target_rate or not samples:
        return list(samples)
    ratio = target_rate / source_rate
    cutoff = min(1.0, ratio)  # low-pass when going down, so nothing aliases
    count = int(len(samples) * ratio)
    out = [0.0] * count
    half = LANCZOS_LOBES / cutoff
    for index in range(count):
        centre = index / ratio
        first = max(0, int(math.floor(centre - half)) + 1)
        last = min(len(samples) - 1, int(math.floor(centre + half)))
        total = 0.0
        weights = 0.0
        for source in range(first, last + 1):
            x = (source - centre) * cutoff
            if x == 0:
                weight = 1.0
            elif abs(x) >= LANCZOS_LOBES:
                continue
            else:
                px = math.pi * x
                weight = math.sin(px) / px * math.sin(px / LANCZOS_LOBES) / (px / LANCZOS_LOBES)
            total += samples[source] * weight
            weights += weight
        out[index] = total / weights if weights else 0.0
    return out


def to_pcm(channels: List[List[float]]) -> bytes:
    """Per-channel floats -> interleaved 16-bit little-endian PCM, clipped to range."""
    frames = min(len(c) for c in channels)
    pcm = bytearray()
    for frame in range(frames):
        for channel in channels:
            value = max(-1.0, min(1.0, channel[frame]))
            pcm += int(round(value * 32767)).to_bytes(2, "little", signed=True)
    return bytes(pcm)


def wav_for_device(path: Path, keep_stereo: bool = False) -> Tuple[bytes, int, float]:
    """(PCM at 46,875 Hz, channel count, seconds) for a WAV file. More than two channels mix to mono."""
    data, rate = read_wav(path)
    if len(data) > 2 or (len(data) == 2 and not keep_stereo):
        data = [[sum(values) / len(data) for values in zip(*data)]]
    converted = [resample(channel, rate) for channel in data]
    return to_pcm(converted), len(converted), len(converted[0]) / DEVICE_RATE
