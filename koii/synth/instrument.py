"""
Turn a rendered design into what the EP-133 stores: the audio plus the sample
settings that make it play like an instrument (root note and fine tune, a
seamless loop, play mode, envelope, level and tempo).

The metadata keys and value types are the ones the device itself uses; every
factory sound carries the same set (see DEVICE.md). Rules from the device:
enums are strings, loop points are frames, and sound.playmode must be written
together with envelope.release.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np

from koii.synth.analysis import crossfade_loop, detect_pitch, find_loop
from koii.synth.engine import Rendered

PITCH_CONFIDENCE = 0.8       # below this, "auto" root leaves the sound at C4
LOOP_QUALITY = 0.9           # below this, "auto" loop gives up rather than click
DEFAULT_ROOT = 60            # the device's own default (C4): plays back at the recorded pitch on C4


@dataclass
class DeviceSound:
    pcm: bytes
    channels: int
    metadata: Dict[str, Any]
    notes: List[str] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return len(self.pcm) / (2 * self.channels * 46875)


def _to_pcm(audio: np.ndarray) -> bytes:
    return (np.round(np.clip(audio, -1, 1).T * 32767).astype("<i2")).tobytes()


def _root(instrument: Dict[str, Any], audio: np.ndarray, notes: List[str]) -> Dict[str, Any]:
    """sound.rootnote and sound.pitch (semitones of fine tune that bring the sound onto its root)."""
    root = instrument["root"]
    if root == "none":
        return {"sound.rootnote": DEFAULT_ROOT, "sound.pitch": 0.0}
    if root != "auto":
        notes.append(f"root note set to MIDI {root}")
        return {"sound.rootnote": int(root), "sound.pitch": 0.0}
    pitch = detect_pitch(audio)
    if not pitch["frequency"] or pitch["confidence"] < PITCH_CONFIDENCE:
        notes.append("no clear pitch, so the root note stays at C4")
        return {"sound.rootnote": DEFAULT_ROOT, "sound.pitch": 0.0}
    fine = round(-pitch["cents"] / 100, 2) + 0.0   # + 0.0 turns -0.0 into 0.0
    notes.append(f"detected {pitch['name']} ({pitch['frequency']:.1f} Hz, {round(pitch['cents']):+d} cents); "
                 f"root set to {pitch['name']}" + (f", fine tune {fine:+.2f}" if fine else ""))
    return {"sound.rootnote": int(pitch["note"]), "sound.pitch": fine}


def prepare(rendered: Rendered) -> DeviceSound:
    """The audio and metadata to upload for a rendered design."""
    instrument = rendered.design["instrument"]
    audio = rendered.audio
    notes: List[str] = []
    metadata: Dict[str, Any] = _root(instrument, audio, notes)

    playmode = instrument["playmode"]
    loop_start, loop_end = -1, -1
    if instrument["loop"] == "auto":
        pitch = detect_pitch(audio)
        frequency = pitch["frequency"] if pitch["confidence"] >= PITCH_CONFIDENCE else None
        loop = find_loop(audio, frequency)
        if loop and loop["quality"] >= LOOP_QUALITY:
            audio = crossfade_loop(audio, loop)
            loop_start, loop_end = int(loop["start"]), int(loop["end"])
            notes.append(f"loop {loop_start / 46875:.3f}–{loop_end / 46875:.3f}s (match {loop['quality']:.2f}), "
                         f"crossfaded")
            if playmode == "oneshot":
                playmode = "key"
                notes.append("play mode changed to key: the device only sustains loops in key or legato mode")
        else:
            notes.append("no seamless loop found (the sound may be too short or still changing), so it plays once")

    metadata.update({
        "sound.playmode": playmode,
        "envelope.release": int(instrument["release"]),
        "envelope.attack": int(instrument["attack"]),
        "sound.amplitude": int(instrument["amplitude"]),
        "sound.loopstart": loop_start,
        "sound.loopend": loop_end,
    })
    if instrument["tempo"] == "bpm":
        metadata.update({"time.mode": "bpm", "sound.bpm": float(instrument["bpm"]), "sound.bars": float(instrument["bars"])})
        notes.append(f"tempo sync on: {instrument['bars']:g} bar(s) at {instrument['bpm']:g} BPM")
    else:
        metadata["time.mode"] = "off"
    return DeviceSound(pcm=_to_pcm(audio), channels=audio.shape[0], metadata=metadata, notes=notes)
