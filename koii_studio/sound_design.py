"""
The sound designer as the browser and Claude use it: render and analyse
designs, keep a library of them, sample and edit sources, build kits, and put
the results on the EP-133 with instrument settings.

The pieces live in koii_studio.synth (format, engine, analysis, variation, editing,
presets); this module joins them to the device library and the event bus.
Everything that writes to the device goes through koii_studio.samples, so the upload
rules there (backup first, empty or own slots only, checksum verified) apply.
"""

import base64
import copy
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from koii_studio.events import EventBus
from koii_studio.samples import FIRST_SUGGESTED_SLOT, SLOT_COUNT, DeviceLibrary, UploadRefused
from koii_studio.synth import edit, presets, variation
from koii_studio.synth.analysis import analyse
from koii_studio.synth.designs import DesignStore
from koii_studio.synth.engine import Rendered, render
from koii_studio.synth.factory import FactoryIndex
from koii_studio.synth.instrument import prepare
from koii_studio.synth.schema import DEVICE_RATE, MAX_SECONDS, DesignError, default_design, schema, validate
from koii_studio.synth.sources import SourceStore

KIT_SIZE = 12
BOUNCE_TAIL_SECONDS = 1.0     # recording keeps going this long after the pattern, for reverb tails
BOUNCE_SNAP_BEFORE = 0.02     # how far either side of the estimated start to look for the first hit
BOUNCE_SNAP_AFTER = 0.15
DEVICE_BPM = (60.0, 180.0)    # tempo sync limits, measured on the device
DEVICE_BARS = (0.25, 4.0)


def device_tempo(bpm: float, bars: float) -> Dict[str, float]:
    """
    The device syncs samples of 0.25–4 bars at 60–180 BPM. A loop outside that range is
    the same length at double or half the tempo with twice or half the bars.
    """
    while bpm < DEVICE_BPM[0]:
        bpm, bars = bpm * 2, bars * 2
    while bpm > DEVICE_BPM[1]:
        bpm, bars = bpm / 2, bars / 2
    if not DEVICE_BARS[0] <= bars <= DEVICE_BARS[1]:
        raise DesignError(f"the device tempo-syncs loops of {DEVICE_BARS[0]:g}–{DEVICE_BARS[1]:g} bars; "
                          f"this is {bars:g} bars at {bpm:g} BPM, so trim it or upload it without tempo sync")
    return {"bpm": round(bpm, 3), "bars": round(bars, 4)}


def _encode_wav(audio: np.ndarray) -> str:
    return base64.b64encode(edit.wav_bytes(audio)).decode()


def _decode(encoded: str, what: str = "audio") -> bytes:
    try:
        return base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise DesignError(f"'{what}' must be base64-encoded ({error})") from error


class SoundDesigner:
    def __init__(self, events: EventBus, home: Path, samples: DeviceLibrary):
        self.events = events
        self.samples = samples
        self.designs = DesignStore(home)
        self.sources = SourceStore(home)
        self.factory = FactoryIndex(home)
        self._kit_job: Optional[threading.Thread] = None
        self._kit_progress: Dict[str, Any] = {}

    # -- format and starting points ----------------------------------------------------------

    def schema(self) -> Dict[str, Any]:
        return {**schema(), "presets": presets.catalogue(), "kit_styles": list(presets.KIT_STYLES)}

    def preset(self, name: str) -> Dict[str, Any]:
        return validate(presets.preset(name))

    def new(self) -> Dict[str, Any]:
        return validate(default_design())

    # -- rendering ------------------------------------------------------------------------

    def render(self, design: Dict[str, Any]) -> Rendered:
        return render(design, self.sources.loader())

    def preview(self, design: Dict[str, Any], similar: bool = True) -> Dict[str, Any]:
        """
        Render a design for the browser: the audio as a WAV (what the device will get,
        loop crossfade included), an analysis, the device settings and the closest
        factory sounds.
        """
        rendered = self.render(design)
        device_sound = prepare(rendered)
        audio = np.frombuffer(device_sound.pcm, "<i2").reshape(-1, device_sound.channels).T.astype(np.float32) / 32767
        report = analyse(audio)
        return {
            "design": rendered.design,
            "wav": _encode_wav(audio),
            "analysis": report,
            "device": {"settings": device_sound.metadata, "notes": device_sound.notes,
                       "seconds": round(device_sound.seconds, 3), "bytes": len(device_sound.pcm),
                       "upload_seconds": round(len(device_sound.pcm) / 5000, 1)},
            "similar": self.factory.nearest(audio) if similar else [],
            "fingerprints": self.factory.status(),
        }

    def describe(self, design: Dict[str, Any]) -> str:
        """A few lines about how a design sounds, for Claude."""
        preview = self.preview(design)
        report, device = preview["analysis"], preview["device"]
        pitch = report["pitch"]
        pitched = (f"{pitch['name']} ({pitch['frequency']:.1f} Hz, {round(pitch['cents']):+d} cents)"
                   if pitch["frequency"] and pitch["confidence"] > 0.7 else "unpitched")
        lines = [
            f"'{preview['design']['name']}': {report['seconds']:.2f}s, {'stereo' if report['channels'] == 2 else 'mono'}, "
            f"{pitched}",
            f"loudness {report['lufs']:.1f} LUFS (peak {report['peak_db']:.1f} dBFS), brightness {report['brightness']:.0f} Hz, "
            f"attack {report['attack'] * 1000:.0f} ms, decays to −40 dB in {report['decay']:.2f}s",
            f"on the device: {device['settings']['sound.playmode']}, root {device['settings']['sound.rootnote']}"
            + (f", loop {device['settings']['sound.loopstart']}–{device['settings']['sound.loopend']}"
               if device['settings']['sound.loopstart'] >= 0 else "")
            + f"; about {device['upload_seconds']:.0f}s to upload",
        ]
        lines += [f"  · {note}" for note in device["notes"]]
        if preview["similar"]:
            lines.append("closest sounds already on the device: "
                         + ", ".join(f"{s['slot']} {s['name']}" for s in preview["similar"]))
        return "\n".join(lines)

    def show(self, design: Dict[str, Any], source: str = "claude") -> Dict[str, Any]:
        """Open a design in the browser's designer."""
        checked = validate(design)
        self.events.publish("design", design=checked, source=source)
        return checked

    # -- variation --------------------------------------------------------------------------

    def vary(self, design: Dict[str, Any], amount: float = 0.3, locks: Sequence[str] = (),
             count: int = 1, seed: Optional[int] = None) -> List[Dict[str, Any]]:
        if count == 1:
            return [variation.randomise(design, amount, locks, seed)]
        return variation.evolve(design, count, amount, locks, seed)

    def morph(self, a: Dict[str, Any], b: Dict[str, Any], t: float) -> Dict[str, Any]:
        return variation.morph(a, b, t)

    # -- the library of designs -------------------------------------------------------------

    def save(self, design: Dict[str, Any], name: Optional[str] = None) -> str:
        key = self.designs.save(design, name)
        self.events.publish("designs", stage="changed")
        return key

    def library(self) -> Dict[str, Any]:
        return {"designs": self.designs.list(), "sources": self.sources.list()}

    def delete_design(self, name: str) -> None:
        self.designs.delete(name)
        self.events.publish("designs", stage="changed")

    # -- putting sounds on the device ----------------------------------------------------------

    def upload(self, design: Dict[str, Any], slot: Optional[int] = None, save: bool = True) -> Dict[str, Any]:
        """Render, prepare and upload a design. Saves it (linked to the slot) so it can be reopened."""
        return self._upload_rendered(self.render(design), slot, save)

    def _upload_rendered(self, rendered: Rendered, slot: Optional[int], save: bool) -> Dict[str, Any]:
        device_sound = prepare(rendered)
        if device_sound.seconds > MAX_SECONDS:
            raise UploadRefused(f"the sound is {device_sound.seconds:.1f}s; shorten it to {MAX_SECONDS:.0f}s or less")
        slot = slot or self.samples.suggest_slot()
        result = self.samples.upload(slot, device_sound.pcm, rendered.design["name"], device_sound.channels,
                                     device_sound.metadata)
        if save:
            key = self.designs.save(rendered.design)
            self.designs.link_slot(key, slot)
            self.events.publish("designs", stage="changed")
        result["settings"] = device_sound.metadata
        result["notes"] = device_sound.notes
        result["message"] += "".join(f"\n  · {note}" for note in device_sound.notes)
        return result

    def ensure_uploaded(self, name: str) -> int:
        """A slot holding this saved design: one it's already in on the device, or a fresh upload."""
        design = self.designs.get(name)
        for slot in self.designs.slots_of(name):
            if self.samples.is_ours(slot):
                return slot
        return self.upload(design)["slot"]

    def delete_upload(self, slot: int) -> str:
        """Delete one of koii studio's uploads and forget which design it came from."""
        message = self.samples.delete_upload(slot)
        self.designs.unlink_slot(slot)
        self.events.publish("designs", stage="changed")
        return message

    def change_settings(self, slot: int, instrument: Dict[str, Any]) -> Dict[str, Any]:
        """
        Change an upload's play mode, envelope, level or tempo without uploading it again.
        Root and loop need the audio, so they change with a fresh upload instead.
        """
        allowed = {"playmode", "attack", "release", "amplitude", "tempo", "bpm", "bars"}
        unknown = set(instrument) - allowed
        if unknown:
            raise DesignError(f"can't change {', '.join(sorted(unknown))} in place; upload the sound again")
        current = self.samples.client.sound_metadata(slot)
        merged = validate({"layers": [{}], "instrument": {
            "playmode": current.get("sound.playmode", "oneshot"), "attack": current.get("envelope.attack", 0),
            "release": current.get("envelope.release", 255), "amplitude": current.get("sound.amplitude", 100),
            **instrument}})["instrument"]
        settings = {"sound.playmode": merged["playmode"], "envelope.release": int(merged["release"]),
                    "envelope.attack": int(merged["attack"]), "sound.amplitude": int(merged["amplitude"]),
                    "time.mode": "bpm" if merged["tempo"] == "bpm" else "off"}
        if merged["tempo"] == "bpm":
            settings.update({"sound.bpm": float(merged["bpm"]), "sound.bars": float(merged["bars"])})
        return self.samples.change_settings(slot, settings)

    def design_for_slot(self, slot: int) -> Optional[Dict[str, Any]]:
        key = self.designs.for_slot(slot)
        return self.designs.get(key) if key else None

    # -- kits ---------------------------------------------------------------------------------

    def kit(self, style: str) -> List[Dict[str, Any]]:
        return [{"pad": item["pad"], "role": item["role"], "design": validate(item["design"])}
                for item in presets.kit(style)]

    def free_run(self, count: int = KIT_SIZE, start: int = FIRST_SUGGESTED_SLOT) -> int:
        """The first slot of `count` consecutive empty slots."""
        taken = {sound.slot for sound in self.samples.sounds(refresh=True)}
        for first in list(range(start, SLOT_COUNT - count + 2)) + list(range(1, start)):
            if all(slot not in taken for slot in range(first, first + count)):
                return first
        raise UploadRefused(f"there aren't {count} empty slots in a row on the device")

    def start_kit_upload(self, style: str, first_slot: Optional[int] = None,
                         designs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Upload a kit (a style's twelve sounds, or the designs given) to consecutive slots, in the background."""
        items = ([{"pad": presets.KIT_PADS[i], "role": presets.KIT_ROLES[i], "design": validate(d)}
                  for i, d in enumerate(designs[:KIT_SIZE])] if designs else self.kit(style))
        return self._start_upload_job(style, items, first_slot)

    def _start_upload_job(self, label: str, items: List[Dict[str, Any]], first_slot: Optional[int]) -> Dict[str, Any]:
        if self._kit_job and self._kit_job.is_alive():
            raise UploadRefused("a kit is already uploading")
        first = first_slot or self.free_run(len(items))
        self._kit_progress = {"style": label, "first": first, "total": len(items), "done": 0, "slots": [], "error": None}
        self._kit_job = threading.Thread(target=self._upload_kit, args=(label, items, first), daemon=True,
                                         name="koii-studio-kit-upload")
        self._kit_job.start()
        return {**self._kit_progress, "message": self._kit_plan(label, items, first)}

    def kit_status(self) -> Dict[str, Any]:
        running = bool(self._kit_job and self._kit_job.is_alive())
        return {**self._kit_progress, "running": running}

    def _kit_plan(self, style: str, items: List[Dict[str, Any]], first: int) -> str:
        lines = [f"uploading the {style} kit to slots {first}–{first + len(items) - 1}. Then put them on pads "
                 f"(press SOUND, hold a pad, use − / + to reach the slot):"]
        for offset, item in enumerate(items):
            lines.append(f"  {item['pad']:<7} → {first + offset}  {item['design']['name']}")
        return "\n".join(lines)

    def _upload_kit(self, style: str, items: List[Dict[str, Any]], first: int) -> None:
        self.events.publish("kit", stage="start", style=style, first=first, total=len(items))
        for offset, item in enumerate(items):
            slot = first + offset
            try:
                if "source" in item:
                    self.upload_source(item["source"], slot, root="none")
                else:
                    self.upload(item["design"], slot)
            except Exception as error:  # report and stop; what's uploaded so far stays
                self._kit_progress["error"] = f"slot {slot}: {error}"
                self.events.publish("kit", stage="error", slot=slot, message=str(error))
                return
            self._kit_progress["done"] = offset + 1
            self._kit_progress["slots"].append({"slot": slot, "pad": item["pad"], "name": item["design"]["name"]})
            self.events.publish("kit", stage="progress", slot=slot, pad=item["pad"], done=offset + 1, total=len(items))
        self.events.publish("kit", stage="done", style=style, first=first, total=len(items))

    # -- sources: recordings, files, edits and slices ----------------------------------------

    def add_source(self, wav_base64: str, name: str, origin: str = "file",
                   extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        entry = self.sources.add_wav(_decode(wav_base64, "wav"), name, origin, extra)
        self.events.publish("designs", stage="changed")
        return entry

    def source_audio(self, source_id: str, edits: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
        """A source (with edits applied, if any) as a WAV plus its analysis and onsets."""
        audio = edit.apply_edits(self.sources.load(source_id), edits)
        return {"info": self.sources.info(source_id), "wav": _encode_wav(audio), "analysis": analyse(audio),
                "onsets": [round(frame / DEVICE_RATE, 4) for frame in edit.onsets(audio)],
                "fits_device": edit.fits_device(audio)}

    def save_edit(self, source_id: str, edits: Sequence[Dict[str, Any]], name: Optional[str] = None) -> Dict[str, Any]:
        """Apply edits and keep the result as a new source (the original stays as it was)."""
        original = self.sources.info(source_id)
        audio = edit.apply_edits(self.sources.load(source_id), edits)
        entry = self.sources.add(audio, name or f"{original['name']} edit", "edit",
                                 {"from": source_id, "edits": list(edits)})
        self.events.publish("designs", stage="changed")
        return entry

    def chop(self, source_id: str, edits: Sequence[Dict[str, Any]] = (), starts: Optional[Sequence[float]] = None,
             slices: Optional[int] = None, sensitivity: float = 0.5) -> List[Dict[str, Any]]:
        """
        Cut a source into slices: at given start times (seconds), into equal parts, or at
        detected onsets. Each slice becomes a source of its own.
        """
        audio = edit.apply_edits(self.sources.load(source_id), edits)
        if starts is not None:
            frames = [int(round(float(s) * DEVICE_RATE)) for s in starts]
        elif slices:
            frames = edit.chop_even(audio, int(slices))
        else:
            frames = edit.onsets(audio, sensitivity)
        name = self.sources.info(source_id)["name"]
        pieces = edit.chop(audio, frames)
        if not pieces:
            raise DesignError("no slices: the cut points leave nothing long enough")
        entries = [self.sources.add(piece, f"{name} {index + 1}"[:40], "slice", {"from": source_id})
                   for index, piece in enumerate(pieces)]
        self.events.publish("designs", stage="changed")
        return entries

    def upload_source(self, source_id: str, slot: Optional[int] = None, playmode: str = "oneshot",
                      root: Any = "auto", loop: str = "off", tempo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Upload a source as it is (stereo stays stereo), with the instrument settings of a
        one-layer sample design, which is also saved so the sound can be reworked later.
        """
        info = self.sources.info(source_id)
        design = self.sample_design(source_id, info["name"], playmode, root, loop, tempo)
        audio = self.sources.load(source_id)
        rendered = Rendered(audio=edit.normalise(audio, design["normalise"]), design=design,
                            seconds=audio.shape[1] / DEVICE_RATE)
        return self._upload_rendered(rendered, slot, save=True)

    def sample_design(self, source_id: str, name: str, playmode: str = "oneshot", root: Any = "auto",
                      loop: str = "off", tempo: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """A design that plays a source straight: the starting point for resampling it."""
        info = self.sources.info(source_id)
        layer = copy.deepcopy(default_design()["layers"][0])
        layer.update(engine="sample", pitch=261.63, params={"source": source_id})
        layer["amp"] = {"attack": 0, "hold": 0, "decay": 1000, "sustain": 1, "release": 2, "curve": 0.5}
        instrument = {"playmode": playmode, "root": root, "loop": loop}
        if tempo:
            instrument.update(tempo="bpm", bpm=float(tempo["bpm"]), bars=float(tempo["bars"]))
        return validate({"name": name, "length": min(MAX_SECONDS, max(0.02, info["seconds"])),
                         "stereo": info["channels"] == 2, "normalise": -1, "layers": [layer],
                         "effects": [], "instrument": instrument})

    def upload_slices(self, source_ids: Sequence[str], first_slot: Optional[int] = None) -> Dict[str, Any]:
        """Upload slices (or any sources) to consecutive slots, in the background, like a kit."""
        items = [{"pad": presets.KIT_PADS[i], "role": f"slice {i + 1}", "source": source_id,
                  "design": {"name": self.sources.info(source_id)["name"]}}
                 for i, source_id in enumerate(source_ids[:KIT_SIZE])]
        if not items:
            raise DesignError("no slices to upload")
        return self._start_upload_job("slices", items, first_slot)

    # -- bouncing a pattern ------------------------------------------------------------------

    @staticmethod
    def bounce_plan(bars: float, bpm: float) -> Dict[str, Any]:
        """How long the browser should record while koii studio plays a pattern once."""
        seconds = bars * 4 * 60 / bpm
        if seconds + BOUNCE_TAIL_SECONDS > 60:
            raise DesignError(f"{bars:g} bars at {bpm:g} BPM is {seconds:.0f}s; bounce at most a minute")
        return {"seconds": round(seconds, 4), "record_seconds": round(seconds + BOUNCE_TAIL_SECONDS, 3),
                "bars": bars, "bpm": bpm, "fits_device": seconds <= MAX_SECONDS}

    def save_bounce(self, wav_base64: str, name: str, bars: float, bpm: float, latency: float = 0.0) -> Dict[str, Any]:
        """
        Keep a recorded bounce as a loop: drop the recording's latency from the front,
        cut it to exactly `bars` at `bpm`, and remember the tempo for the upload.
        """
        audio = edit.load_for_device(_decode(wav_base64, "wav"))
        plan = self.bounce_plan(bars, bpm)
        start = self._first_hit(audio, max(0.0, float(latency)))
        if start + plan["seconds"] > audio.shape[1] / DEVICE_RATE:
            raise DesignError(f"the recording is too short for {bars:g} bars at {bpm:g} BPM; record a little longer")
        loop = edit.trim(audio, start, start + plan["seconds"])
        loop = edit.fade(loop, 0.001, 0.003)
        entry = self.sources.add(loop, name, "bounce", {"bpm": bpm, "bars": bars})
        self.events.publish("designs", stage="changed")
        return entry

    @staticmethod
    def _first_hit(audio: np.ndarray, estimate: float) -> float:
        """
        The browser only knows roughly when playback started (MIDI and USB audio both add a
        little delay), so start the loop on the first hit just after that, if there is one.
        """
        low = max(0, int((estimate - BOUNCE_SNAP_BEFORE) * DEVICE_RATE))
        high = min(audio.shape[1], int((estimate + BOUNCE_SNAP_AFTER) * DEVICE_RATE))
        window = audio[:, low:high]
        if window.shape[1] < 512 or float(np.max(np.abs(window))) < 0.01:
            return estimate
        return (low + edit.onsets(window)[0]) / DEVICE_RATE

    def upload_bounce(self, source_id: str, slot: Optional[int] = None) -> Dict[str, Any]:
        info = self.sources.info(source_id)
        if "bpm" not in info:
            raise DesignError(f"source '{source_id}' isn't a bounce (it has no tempo)")
        return self.upload_source(source_id, slot, playmode="oneshot", root="none",
                                  tempo=device_tempo(info["bpm"], info["bars"]))
