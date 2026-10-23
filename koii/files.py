"""
The EP-133's file system over SysEx: the sample library and project archives.

This is the private protocol TE's EP Sample Tool uses. It isn't documented by
TE; this follows the community reverse engineering in kmorrill/ep-series-sysex
(MIT licence, verified on OS 2.5.1), docs/sysex-protocol.md and
docs/file-protocol.md. Safety rules from that work, all enforced here:

- The device's file system handles one session at a time; overlapping
  sessions (even read-only) freeze it until it's power-cycled. Every session
  holds the shared lock /tmp/ep-device.lock, the same file the community
  tools use, so they serialise against each other too. Don't run TE's EP
  Sample Tool at the same time.
- A firmware "debug frame" means the device is unhappy: stop immediately and
  power-cycle before any more file traffic. Never retry automatically.
- Reads are exact-size, never past the end of a file, and a response's status
  byte is stripped before decoding (decoding it shifts every byte).

This module only reads for now: list, stat, metadata, read and audition.
"""

import fcntl
import io
import json
import logging
import os
import time
import wave
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

import mido

logger = logging.getLogger(__name__)

TE_MANUFACTURER = [0x00, 0x20, 0x76]
EP133_PRODUCT = 0x33
PROTOCOL_MARKER = 0x40
DEBUG_MARKER = 0x33
CMD_FILE = 0x05
BIT_IS_REQUEST = 0x40
BIT_REQUEST_ID = 0x20

SOUNDS_NODE = 1000
PROJECTS_NODE = 2000
SLOTS = range(1, 1000)
GET_PAGE_BYTES = 324          # raw bytes per read page on OS 2.5.x
PAGE_PAUSE_SECONDS = 0.006    # the community client's pacing between pages
LOCK_PATH = Path("/tmp/ep-device.lock")
LOCK_TIMEOUT_SECONDS = 15
REQUEST_TIMEOUT_SECONDS = 3.0
DEBUG_GRACE_SECONDS = 2.5     # a looping device announces itself about once a second
DEVICE_SAMPLE_RATE = 46875


class DeviceFileError(RuntimeError):
    """Something went wrong talking to the device's file system."""


class DeviceUnhappy(DeviceFileError):
    """The device sent a firmware debug frame. Stop, power-cycle it, then try again."""

    def __init__(self, text: str):
        super().__init__(
            f"the EP-133 reported an internal error ({text}). Stop, switch it off and on again, "
            "and close any other tool talking to it (such as TE's EP Sample Tool) before retrying"
        )
        self.text = text


class Rejected(DeviceFileError):
    """The device refused a request cleanly (safe; it stays healthy)."""

    def __init__(self, status: int, reason: str):
        super().__init__(f"the EP-133 refused the request: {reason or f'status {status}'}")
        self.status = status
        self.reason = reason


class DeviceBusy(DeviceFileError):
    pass


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

def pack7(raw: bytes) -> List[int]:
    """8-bit bytes -> SysEx-safe 7-bit groups: a flag byte (high bits) then up to 7 low-7-bit bytes."""
    encoded: List[int] = []
    for offset in range(0, len(raw), 7):
        chunk = raw[offset:offset + 7]
        flags = 0
        for bit, byte in enumerate(chunk):
            if byte & 0x80:
                flags |= 1 << bit
        encoded.append(flags)
        encoded.extend(byte & 0x7F for byte in chunk)
    return encoded


def unpack7(encoded: List[int]) -> bytes:
    raw = bytearray()
    index = 0
    while index < len(encoded):
        flags = encoded[index]
        index += 1
        for bit in range(7):
            if index >= len(encoded):
                break
            byte = encoded[index]
            index += 1
            raw.append(byte | 0x80 if flags & (1 << bit) else byte)
    return bytes(raw)


def build_request(request_id: int, payload: bytes, product: int = EP133_PRODUCT) -> List[int]:
    """SysEx body (without F0/F7) for one FILE request."""
    request_id &= 0x0FFF
    return (TE_MANUFACTURER + [product, PROTOCOL_MARKER, BIT_IS_REQUEST | BIT_REQUEST_ID | (request_id >> 7),
                               request_id & 0x7F, CMD_FILE] + pack7(payload))


def is_debug_frame(data: List[int]) -> bool:
    return data[:3] == TE_MANUFACTURER and len(data) >= 5 and data[4] == DEBUG_MARKER


def match_response(data: List[int], request_id: int) -> Optional[Tuple[int, bytes]]:
    """(status, payload) if `data` answers `request_id`, else None. Raises DeviceUnhappy on a debug frame."""
    if data[:3] != TE_MANUFACTURER:
        return None
    if is_debug_frame(data):
        raise DeviceUnhappy(bytes(data[5:]).decode("utf-8", "replace").strip())
    request_id &= 0x0FFF
    if len(data) < 9 or data[4] != PROTOCOL_MARKER:
        return None
    if data[5] != BIT_REQUEST_ID | (request_id >> 7) or data[6] != request_id & 0x7F or data[7] != CMD_FILE:
        return None
    return data[8], unpack7(data[9:])


def _u16(value: int) -> bytes:
    return value.to_bytes(2, "big")


def _name(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class Sound:
    slot: int
    name: str
    bytes: int
    flags: int = 0
    metadata: Dict = field(default_factory=dict)

    @property
    def channels(self) -> int:
        return int(self.metadata.get("channels") or 1)

    @property
    def sample_rate(self) -> int:
        return int(self.metadata.get("samplerate") or DEVICE_SAMPLE_RATE)

    @property
    def seconds(self) -> float:
        frames = self.bytes / (2 * self.channels)
        return frames / self.sample_rate

    @property
    def crc(self) -> Optional[int]:
        """The device's CRC-32 of the sample's audio bytes (checked on hardware)."""
        value = self.metadata.get("crc")
        return int(value) if value is not None else None


def pcm_to_wav(pcm: bytes, sample_rate: int, channels: int, byte_order: str = "little") -> bytes:
    """Raw 16-bit PCM -> a WAV file. WAV is little-endian, so big-endian data is swapped first."""
    if byte_order == "big":
        swapped = bytearray(len(pcm) - len(pcm) % 2)
        swapped[0::2] = pcm[1:len(swapped):2]
        swapped[1::2] = pcm[0:len(swapped):2]
        pcm = bytes(swapped)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm[: len(pcm) - len(pcm) % (2 * channels)])
    return buffer.getvalue()


def roughness(pcm: bytes, byte_order: str) -> float:
    """Mean jump between neighbouring samples; the right byte order gives a much smoother signal."""
    count = min(len(pcm) // 2, 20000)
    if count < 2:
        return 0.0
    values = [int.from_bytes(pcm[i * 2:i * 2 + 2], byte_order, signed=True) for i in range(count)]
    return sum(abs(b - a) for a, b in zip(values, values[1:])) / (count - 1)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@contextmanager
def device_lock(owner: str, path: Path = LOCK_PATH, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """The cross-process lock that keeps file sessions from overlapping."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.seek(0)
                    holder = handle.read().strip() or "another program"
                    raise DeviceBusy(f"the EP-133's file system is busy ({holder}); try again when it's finished")
                time.sleep(0.1)
        handle.seek(0)
        handle.truncate()
        handle.write(f"koii:{owner} pid={os.getpid()} acquired={time.strftime('%Y-%m-%d %H:%M:%S %z')}\n")
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class Session:
    """One locked file session over a pair of MIDI ports."""

    def __init__(self, midi_in, midi_out, product: int = EP133_PRODUCT):
        self.midi_in = midi_in
        self.midi_out = midi_out
        self.product = product
        self.request_id = 0x300

    def request(self, payload: bytes, timeout: float = REQUEST_TIMEOUT_SECONDS) -> bytes:
        request_id = self.request_id & 0x0FFF
        self.request_id += 1
        self.midi_out.send(mido.Message("sysex", data=build_request(request_id, payload, self.product)))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.midi_in.poll()
            if message is None:
                time.sleep(0.002)
                continue
            if message.type != "sysex":
                continue
            matched = match_response(list(message.data), request_id)
            if matched is None:
                continue
            status, body = matched
            if status != 0:
                raise Rejected(status, body.decode("utf-8", "replace").strip("\0 "))
            return body
        # Before calling it a timeout, check whether the device is in an error loop.
        grace = time.monotonic() + DEBUG_GRACE_SECONDS
        while time.monotonic() < grace:
            message = self.midi_in.poll()
            if message is not None and message.type == "sysex":
                match_response(list(message.data), request_id)
            time.sleep(0.02)
        raise DeviceFileError("the EP-133 didn't answer. Is TE's EP Sample Tool open? If so, close it; "
                              "otherwise switch the device off and on again")

    def init(self) -> int:
        """
        Start the file session; returns the device's chunk size. The docs describe flag 0 for
        reading, but the verified community client always sends 1, so this does the same.
        """
        body = self.request(bytes([0x01, 0x01]) + (4 * 1024 * 1024).to_bytes(4, "big"))
        return int.from_bytes(body[1:5], "big") if len(body) >= 5 else 512

    def list(self, node: int) -> List[Dict]:
        entries: List[Dict] = []
        page = 0
        while True:
            body = self.request(bytes([0x04]) + _u16(page) + _u16(node))
            if len(body) <= 2:
                return entries
            if int.from_bytes(body[:2], "big") != page:
                raise DeviceFileError(f"listing came back out of order (page {int.from_bytes(body[:2], 'big')}, wanted {page})")
            offset = 2
            while offset + 7 <= len(body):
                end = body.index(0, offset + 7) if 0 in body[offset + 7:] else len(body)
                entries.append({
                    "id": int.from_bytes(body[offset:offset + 2], "big"),
                    "flags": body[offset + 2],
                    "size": int.from_bytes(body[offset + 3:offset + 7], "big"),
                    "name": body[offset + 7:end].decode("utf-8", "replace"),
                })
                offset = end + 1
            page += 1

    def stat(self, node: int) -> Dict:
        body = self.request(bytes([0x0B]) + _u16(node))
        if len(body) < 9:
            raise DeviceFileError(f"unexpected answer about node {node}")
        return {"id": int.from_bytes(body[0:2], "big"), "parent": int.from_bytes(body[2:4], "big"),
                "flags": body[4], "size": int.from_bytes(body[5:9], "big"), "name": _name(body[9:])}

    def metadata(self, node: int) -> Dict:
        text = ""
        page = 0
        while True:
            body = self.request(bytes([0x07, 0x02]) + _u16(node) + _u16(page))
            if len(body) <= 2:
                break
            if int.from_bytes(body[:2], "big") != page:
                raise DeviceFileError("metadata came back out of order")
            text += _name(body[2:])
            if body[-1] == 0:
                break
            page += 1
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_raw": text}

    def read(self, node: int, progress: Optional[Callable[[int, int], None]] = None) -> Tuple[bytes, Dict]:
        """Read a whole file: exactly as many bytes as the device says it holds, never more."""
        opened = self.request(bytes([0x03, 0x00]) + _u16(node) + bytes(4))
        if len(opened) < 7:
            raise DeviceFileError(f"couldn't open node {node}")
        size = int.from_bytes(opened[3:7], "big")
        data = bytearray()
        page = 0
        while len(data) < size:
            body = self.request(bytes([0x03, 0x01]) + _u16(page))
            if len(body) < 2 or int.from_bytes(body[:2], "big") != page:
                raise DeviceFileError(f"reading node {node} went out of step at page {page}")
            data.extend(body[2:])
            page += 1
            if progress:
                progress(min(len(data), size), size)
            time.sleep(PAGE_PAUSE_SECONDS)
        return bytes(data[:size]), {"size": size, "flags": opened[2], "name": _name(opened[7:])}

    def audition(self, node: int) -> None:
        """Play a sample slot's raw audio on the device (no trim or envelope)."""
        self.request(bytes([0x05, 0x01]) + _u16(node))


class DeviceFiles:
    """The EP-133's sample library and projects. Every call runs one complete, locked session."""

    def __init__(self, port_hint: str = "EP-133",
                 open_input: Callable = mido.open_input, open_output: Callable = mido.open_output,
                 input_names: Callable = mido.get_input_names, output_names: Callable = mido.get_output_names,
                 lock_path: Path = LOCK_PATH):
        self.port_hint = port_hint
        self._open_input = open_input
        self._open_output = open_output
        self._input_names = input_names
        self._output_names = output_names
        self.lock_path = lock_path

    def _port(self, names: List[str], direction: str) -> str:
        for name in names:
            if self.port_hint.lower() in name.lower():
                return name
        raise DeviceFileError(f"no EP-133 MIDI {direction} found. Is it plugged in? Available: {', '.join(names) or 'none'}")

    @contextmanager
    def session(self, owner: str) -> Iterator[Session]:
        input_name = self._port(self._input_names(), "input")
        output_name = self._port(self._output_names(), "output")
        with device_lock(owner, self.lock_path):
            midi_in = self._open_input(input_name)
            midi_out = self._open_output(output_name)
            try:
                while midi_in.poll() is not None:  # drop anything left over
                    pass
                session = Session(midi_in, midi_out)
                session.init()
                yield session
            finally:
                midi_in.close()
                midi_out.close()

    # -- reading ----------------------------------------------------------------------

    def list_sounds(self, with_metadata: bool = False) -> List[Sound]:
        with self.session("list_sounds") as session:
            sounds = [Sound(slot=e["id"], name=e["name"], bytes=e["size"], flags=e["flags"])
                      for e in session.list(SOUNDS_NODE) if e["id"] in SLOTS]
            if with_metadata:
                for sound in sounds:
                    sound.metadata = session.metadata(sound.slot)
                    sound.name = sound.metadata.get("name") or sound.name
        return sorted(sounds, key=lambda s: s.slot)

    def sound_metadata(self, slot: int) -> Dict:
        _check_slot(slot)
        with self.session("sound_metadata") as session:
            return session.metadata(slot)

    def read_sound(self, slot: int, progress: Optional[Callable[[int, int], None]] = None) -> Tuple[bytes, Sound]:
        """Download a sample's raw audio (little-endian 16-bit), checked against the device's CRC-32."""
        _check_slot(slot)
        with self.session("read_sound") as session:
            metadata = session.metadata(slot)
            pcm, info = session.read(slot, progress)
        sound = Sound(slot=slot, name=metadata.get("name") or info["name"], bytes=info["size"], metadata=metadata)
        if sound.crc is not None and zlib.crc32(pcm) != sound.crc:
            raise DeviceFileError(f"slot {slot} arrived damaged (checksum mismatch); try again")
        return pcm, sound

    def list_projects(self) -> List[Dict]:
        with self.session("list_projects") as session:
            return session.list(PROJECTS_NODE)

    def read_project(self, node: int, progress: Optional[Callable[[int, int], None]] = None) -> Tuple[bytes, Dict]:
        with self.session("read_project") as session:
            return session.read(node, progress)

    def audition(self, slot: int) -> None:
        _check_slot(slot)
        with self.session("audition") as session:
            session.audition(slot)


def _check_slot(slot: int) -> None:
    if slot not in SLOTS:
        raise DeviceFileError(f"sample slots are 1–999, not {slot}")
