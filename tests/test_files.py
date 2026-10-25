"""
The device file protocol, against a simulated EP-133 that answers like the
real one (frames, packing, paging, rejections, debug frames).
"""

import io
import threading
import wave

import pytest

from koii_studio import files
from koii_studio.files import (
    DeviceBusy, DeviceFileError, DeviceUnhappy, Rejected, build_request, device_lock,
    match_response, pack7, pcm_to_wav, roughness, unpack7,
)

from fake_device import FakeEP133, client_for, sound


def test_pack7_matches_the_documented_example():
    # docs/sysex-protocol.md: raw 07 D0 00 2C encodes as 02 07 50 00 2C
    assert pack7(bytes([0x07, 0xD0, 0x00, 0x2C])) == [0x02, 0x07, 0x50, 0x00, 0x2C]
    assert unpack7([0x02, 0x07, 0x50, 0x00, 0x2C]) == bytes([0x07, 0xD0, 0x00, 0x2C])


def test_pack7_round_trips_every_byte_value():
    raw = bytes(range(256)) * 3
    encoded = pack7(raw)
    assert all(0 <= value < 0x80 for value in encoded)
    assert unpack7(encoded) == raw


def test_request_frame_layout():
    frame = build_request(0x305, bytes([0x0B, 0x00, 0x01]))
    assert frame[:5] == [0x00, 0x20, 0x76, 0x33, 0x40]
    assert frame[5] == 0x60 | (0x305 >> 7) and frame[6] == 0x305 & 0x7F and frame[7] == 0x05


def test_responses_strip_the_status_byte_before_unpacking():
    response = [0x00, 0x20, 0x76, 0x33, 0x40, 0x20 | (0x305 >> 7), 0x305 & 0x7F, 0x05, 0x00] + pack7(b"\x81\x02")
    assert match_response(response, 0x305) == (0, b"\x81\x02")
    assert match_response(response, 0x306) is None


def test_a_debug_frame_stops_everything():
    with pytest.raises(DeviceUnhappy, match="switch it off and on"):
        match_response([0x00, 0x20, 0x76, 0x33, 0x33] + list(b"err lfs 6327"), 0x300)


# -- against a simulated device ------------------------------------------------------------

@pytest.fixture
def device(tmp_path, monkeypatch):
    pcm = b"".join((80 * i).to_bytes(2, "little", signed=True) for i in range(-400, 400))
    fake = FakeEP133({
        1: sound("MICRO KICK", pcm),
        303: sound("CLAP REAL", b"\x01\x00" * 10, channels=2),
    })
    monkeypatch.setattr(files, "PAGE_PAUSE_SECONDS", 0)
    return fake, client_for(fake, tmp_path / "ep-device.lock")


def test_lists_the_sample_library_with_names(device):
    fake, client = device
    sounds = client.list_sounds(with_metadata=True)
    assert [(s.slot, s.name, s.channels) for s in sounds] == [(1, "MICRO KICK", 1), (303, "CLAP REAL", 2)]
    assert sounds[0].seconds == pytest.approx(800 / 46875)


def test_reads_exactly_the_file_size_and_no_further(device):
    fake, client = device
    progress = []
    pcm, sound = client.read_sound(1, progress=lambda done, total: progress.append((done, total)))
    assert pcm == fake.sounds[1][1] and sound.name == "MICRO KICK"
    assert progress[-1] == (1600, 1600)
    pages = [r for r in fake.requests if r[:2] == bytes([0x03, 0x01])]
    assert len(pages) == -(-1600 // files.GET_PAGE_BYTES)


def test_clean_rejections_are_reported(device):
    fake, client = device
    with pytest.raises(Rejected, match="invalid id"):
        client.sound_metadata(42)


def test_a_debug_frame_mid_session_raises(device):
    fake, client = device
    fake.misbehave = "debug"
    with pytest.raises(DeviceUnhappy):
        client.list_sounds()


def test_silence_is_reported_with_advice(device, monkeypatch):
    fake, client = device
    monkeypatch.setattr(files, "REQUEST_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(files, "DEBUG_GRACE_SECONDS", 0.05)
    fake.misbehave = "silent"
    with pytest.raises(DeviceFileError, match="EP Sample Tool"):
        client.list_sounds()


def test_a_file_shorter_than_the_device_said_stops_the_read(device):
    fake, client = device
    fake.misbehave = "short"
    with pytest.raises(DeviceFileError, match="ended after"):
        client.read_sound(1)


def test_slots_are_checked_before_anything_is_sent(device):
    fake, client = device
    with pytest.raises(DeviceFileError, match="1–999"):
        client.read_sound(0)
    assert fake.requests == []


def test_sessions_never_overlap(tmp_path):
    lock = tmp_path / "ep-device.lock"
    entered = threading.Event()
    release = threading.Event()

    def hold():
        with device_lock("first", lock):
            entered.set()
            release.wait(5)

    holder = threading.Thread(target=hold)
    holder.start()
    entered.wait(5)
    with pytest.raises(DeviceBusy, match="busy"):
        with device_lock("second", lock, timeout=0.2):
            pass
    release.set()
    holder.join()
    with device_lock("third", lock, timeout=1):
        pass


def test_pcm_converts_to_wav_in_either_byte_order():
    pcm_little = (1234).to_bytes(2, "little", signed=True) * 4
    pcm_big = (1234).to_bytes(2, "big", signed=True) * 4
    for pcm, order in ((pcm_little, "little"), (pcm_big, "big")):
        with wave.open(io.BytesIO(pcm_to_wav(pcm, 46875, 1, order))) as audio:
            assert audio.getframerate() == 46875 and audio.getnchannels() == 1
            assert audio.readframes(4) == pcm_little


def test_the_right_byte_order_is_much_smoother():
    pcm = b"".join(int(8000 * (i % 50) / 50).to_bytes(2, "little", signed=True) for i in range(2000))
    assert roughness(pcm, "little") * 10 < roughness(pcm, "big")


def test_a_damaged_download_is_caught_by_the_checksum(device):
    fake, client = device
    name, pcm, metadata = fake.sounds[1]
    fake.sounds[1] = (name, pcm, {**metadata, "crc": metadata["crc"] ^ 1})
    with pytest.raises(DeviceFileError, match="checksum"):
        client.read_sound(1)
