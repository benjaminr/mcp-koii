import math
import wave

import pytest

from koii_studio.audio import DEVICE_RATE, read_wav, resample, wav_for_device


def write_wav(path, rate, channels, width, frames):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(b"".join(frames))
    return path


def tone(rate, hz, seconds, width=2, channels=1, level=0.5):
    scale = 2 ** (8 * width - 1) - 1
    frames = []
    for i in range(int(rate * seconds)):
        value = int(level * scale * math.sin(2 * math.pi * hz * i / rate))
        frames.append(value.to_bytes(width, "little", signed=True) * channels)
    return frames


def test_cd_audio_is_converted_to_the_device_rate(tmp_path):
    path = write_wav(tmp_path / "a.wav", 44100, 2, 2, tone(44100, 440, 0.5, channels=2))
    pcm, channels, seconds = wav_for_device(path)
    assert channels == 1 and seconds == pytest.approx(0.5, abs=0.001)
    assert len(pcm) == int(44100 * 0.5 * DEVICE_RATE / 44100) * 2


def test_stereo_can_be_kept(tmp_path):
    path = write_wav(tmp_path / "s.wav", 48000, 2, 2, tone(48000, 440, 0.1, channels=2))
    pcm, channels, _ = wav_for_device(path, keep_stereo=True)
    assert channels == 2 and len(pcm) % 4 == 0


def test_24_bit_files_are_read(tmp_path):
    path = write_wav(tmp_path / "h.wav", 46875, 1, 3, tone(46875, 1000, 0.05, width=3, level=0.25))
    data, rate = read_wav(path)
    assert rate == 46875 and max(data[0]) == pytest.approx(0.25, abs=0.001)


def test_resampling_keeps_pitch_and_level():
    source = [math.sin(2 * math.pi * 1000 * i / 44100) for i in range(4410)]
    out = resample(source, 44100)
    crossings = sum(1 for a, b in zip(out, out[1:]) if a < 0 <= b)
    assert crossings == pytest.approx(100, abs=1)
    assert max(out[200:-200]) == pytest.approx(1.0, abs=0.02)
