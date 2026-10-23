"""A simulated EP-133 file system that answers FILE requests like the real one."""

import json
import zlib
from collections import deque

import mido

from koii import files, pads
from koii.files import pack7, unpack7


def sound(name, pcm, **metadata):
    """(name, pcm, metadata) with the device's CRC-32 filled in."""
    return name, pcm, {"name": name, "channels": 1, "samplerate": 46875, "format": "s16",
                       "crc": zlib.crc32(pcm), **metadata}


class FakeEP133:
    def __init__(self, sounds, projects=None, pads=None, active_project=1):
        self.sounds = sounds                  # slot -> (name, pcm, metadata)
        self.projects = projects or {}        # fid -> (name, tar bytes)
        self.pads = pads or {}                # pad node -> metadata
        self.active_project = active_project
        self.inbox = deque()
        self.requests = []
        self.misbehave = None
        self.open_node = None
        self.writing = None        # (slot, name, expected size, bytearray) while a write is open

    # mido-like port interface
    def poll(self):
        return self.inbox.popleft() if self.inbox else None

    def close(self):
        pass

    def send(self, message):
        data = list(message.data)
        request_id = ((data[5] & 0x1F) << 7) | data[6]
        payload = unpack7(data[8:])
        self.requests.append(payload)
        if self.misbehave == "debug":
            return self._raw([0x00, 0x20, 0x76, 0x33, 0x33] + list(b"err pattern 213"))
        if self.misbehave == "silent":
            return None
        status, body = self._handle(payload)
        self._raw([0x00, 0x20, 0x76, 0x33, 0x40, 0x20 | (request_id >> 7), request_id & 0x7F, 0x05, status] + pack7(body))

    def _raw(self, data):
        self.inbox.append(mido.Message("sysex", data=data))

    def _file(self, node):
        if node in self.sounds:
            name, data, _ = self.sounds[node]
            return name, data
        return self.projects[node]

    def _handle(self, payload):
        command = payload[0]
        if command == 0x01:
            return 0, bytes([0x00]) + (512).to_bytes(4, "big")
        if command == 0x04:
            page = int.from_bytes(payload[1:3], "big")
            node = int.from_bytes(payload[3:5], "big")
            if page > 0:
                return 0, page.to_bytes(2, "big")
            entries = ({slot: (n, d) for slot, (n, d, _) in self.sounds.items()} if node == files.SOUNDS_NODE
                       else self.projects)
            body = bytearray((0).to_bytes(2, "big"))
            for fid, (name, data) in sorted(entries.items()):
                body += fid.to_bytes(2, "big") + bytes([0x05]) + len(data).to_bytes(4, "big") + name.encode() + b"\0"
            return 0, bytes(body)
        if command == 0x07 and payload[1] == 0x02:
            slot = int.from_bytes(payload[2:4], "big")
            if slot == files.PROJECTS_NODE:
                metadata = {"active": pads.project_node(self.active_project)}
            elif slot in self.pads or 3200 <= slot < 12000:
                metadata = self.pads.get(slot, {"sym": 0})
            elif slot not in self.sounds:
                return 1, b"invalid id"
            else:
                metadata = self.sounds[slot][2]
            return 0, (0).to_bytes(2, "big") + json.dumps(metadata).encode() + b"\0"
        if command == 0x03 and payload[1] == 0x00:
            node = int.from_bytes(payload[2:4], "big")
            name, data = self._file(node)
            self.open_node = node
            return 0, node.to_bytes(2, "big") + bytes([0x05]) + len(data).to_bytes(4, "big") + name.encode() + b"\0"
        if command == 0x03 and payload[1] == 0x01:
            page = int.from_bytes(payload[2:4], "big")
            data = self._file(self.open_node)[1]
            chunk = data[page * files.GET_PAGE_BYTES:(page + 1) * files.GET_PAGE_BYTES]
            assert chunk, "the client read past the end of the file"
            return 0, page.to_bytes(2, "big") + chunk
        if command == 0x05:
            return 0, b""
        if command == 0x02 and payload[1] == 0x00:
            node = int.from_bytes(payload[3:5], "big")
            size = int.from_bytes(payload[7:11], "big")
            name = payload[11:].split(b"\0", 1)[0].decode()
            self.writing = (node, name, size, bytearray())
            return 0, node.to_bytes(2, "big")
        if command == 0x02 and payload[1] == 0x01:
            node, name, size, data = self.writing
            chunk = payload[4:]
            if not chunk:  # empty page: end of file; the device computes the checksum itself
                assert len(data) == size, "the client didn't send the size it promised"
                self.sounds[node] = (name, bytes(data), {"name": name, "channels": 1, "samplerate": 46875,
                                                         "format": "s16", "crc": zlib.crc32(bytes(data))})
                self.writing = None
            else:
                data.extend(chunk)
            return 0, b""
        if command == 0x07 and payload[1] == 0x01:
            node = int.from_bytes(payload[2:4], "big")
            values = json.loads(payload[4:].split(b"\0", 1)[0])
            if node == files.PROJECTS_NODE:
                self.active_project = (values["active"] - pads.FIRST_PROJECT_NODE) // pads.NODES_PER_PROJECT + 1
                return 0, b""
            within = node % pads.NODES_PER_PROJECT
            if within == pads.GROUPS_NODE_OFFSET or within in range(pads.FIRST_PAD_NODE, 600, pads.NODES_PER_GROUP):
                return 0, b""   # group and pad cursors: accepted, nothing to keep
            if 3200 <= node < 12000:
                pad = dict(self.pads.get(node, {"sym": 0}))
                if values.get("sym"):  # like the device: a new sample brings its own defaults
                    defaults = self.sounds[values["sym"]][2]
                    pad.update({"envelope.attack": defaults.get("envelope.attack", 0),
                                "sound.pitch": defaults.get("sound.pitch", 0.0)})
                self.pads[node] = {**pad, **values}
                return 0, b""
            if len(str(values.get("name", ""))) > 16:   # like OS 2.5
                return 1, b"invalid length"
            name, data, metadata = self.sounds[node]
            self.sounds[node] = (name, data, {**metadata, **values})
            return 0, b""
        if command == 0x0B:
            node = int.from_bytes(payload[1:3], "big")
            if node not in self.sounds and node not in self.projects:
                return 1, b"invalid id"
            name, data = self._file(node)
            return 0, node.to_bytes(2, "big") + (1000).to_bytes(2, "big") + bytes([0x1D]) + len(data).to_bytes(4, "big") + name.encode() + b"\0"
        if command == 0x06:
            node = int.from_bytes(payload[1:3], "big")
            if len(payload) != 3 or node not in self.sounds:
                return 1, b"failed to delete"
            del self.sounds[node]
            return 0, b""
        return 1, b"unknown"


def client_for(fake, lock_path):
    return files.DeviceFiles(open_input=lambda name: fake, open_output=lambda name: fake,
                             input_names=lambda: ["EP-133"], output_names=lambda: ["EP-133"], lock_path=lock_path)
