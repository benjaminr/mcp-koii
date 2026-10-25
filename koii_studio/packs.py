"""
Sample packs: a demo or kit you can put on the EP-133 in one go, and take off again to
free the space.

A pack is a folder in ~/.koii-studio/packs/<name>/ with a pack.json and its audio:

    {"format": 1, "name": "space-and-jazz", "title": "…", "description": "…",
     "credits": [{"what": "…", "source": "https://…", "licence": "Public domain"}],
     "samples": [{"id": "moon-choose", "file": "samples/moon-choose.wav", "name": "moon choose",
                  "settings": {"sound.playmode": "oneshot", "envelope.release": 255}}],
     "pads": {"B.": {"sample": "moon-choose"}, "A.": {"sound": 24}, "D1": {"design": "clean keys", "channel": 3}},
     "patterns": {"ms-pad": "…notation…"}, "songs": {"moonshot": "ms-pad x2, …"}}

A pad takes its sound from one of the pack's samples, a factory slot ("sound"), or one of
koii studio's sound designs ("design", rendered and uploaded if it isn't on the device yet), plus
any pad setting (channel, mode, level, attack, release, pan).

Installing uploads the samples to empty slots (reusing ones already there from this pack),
fills the pads of one project, and saves the patterns and songs. Removing deletes the pack's
uploads and empties the pads that played them; its patterns and songs stay in the library.
Which slots and project a pack used is kept in ~/.koii-studio/packs-installed.json.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from koii_studio.events import EventBus
from koii_studio.files import DEVICE_SAMPLE_RATE
from koii_studio.pads import PadEditor, parse_pad
from koii_studio.samples import DeviceLibrary, UploadRefused
from koii_studio.synth.edit import load_for_device, read_wav_bytes, to_pcm

logger = logging.getLogger(__name__)

PACK_FORMAT = 1
PAD_SETTINGS = ("channel", "mode", "level", "attack", "release", "pan")


class PackError(ValueError):
    """A pack that can't be read, installed or removed as asked."""


@dataclass
class Pack:
    folder: Path
    manifest: Dict[str, Any]

    @property
    def name(self) -> str:
        return self.manifest["name"]

    def sample_path(self, sample: Dict[str, Any]) -> Path:
        path = (self.folder / sample["file"]).resolve()
        if self.folder.resolve() not in path.parents:
            raise PackError(f"{self.name}: sample {sample['id']} points outside the pack")
        return path

    def sample_bytes(self) -> int:
        """Roughly what the pack's samples take on the device (16-bit mono or stereo)."""
        return sum(_device_bytes(self.sample_path(sample)) for sample in self.manifest.get("samples", []))


_sizes: Dict[tuple, int] = {}


def _device_bytes(path: Path) -> int:
    """A WAV's size once on the device, remembered per file (by size and time) so listings don't decode it again."""
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in _sizes:
        audio, rate = read_wav_bytes(path.read_bytes())
        _sizes[key] = int(audio.shape[1] * DEVICE_SAMPLE_RATE / rate) * 2 * min(audio.shape[0], 2)
    return _sizes[key]


def read_pack(folder: Path) -> Pack:
    try:
        manifest = json.loads((folder / "pack.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise PackError(f"{folder.name} has no readable pack.json ({error})") from error
    if manifest.get("format") != PACK_FORMAT:
        raise PackError(f"{folder.name}: pack format {manifest.get('format')!r}, koii studio reads format {PACK_FORMAT}")
    ids = {sample["id"] for sample in manifest.get("samples", [])}
    for pad, source in manifest.get("pads", {}).items():
        parse_pad(pad)
        kinds = [key for key in ("sample", "sound", "design") if key in source]
        if len(kinds) > 1:
            raise PackError(f"{folder.name}: pad {pad} names more than one sound")
        if "sample" in source and source["sample"] not in ids:
            raise PackError(f"{folder.name}: pad {pad} uses sample '{source['sample']}', which isn't in the pack")
        unknown = set(source) - {"sample", "sound", "design", *PAD_SETTINGS}
        if unknown:
            raise PackError(f"{folder.name}: pad {pad} has unknown settings {sorted(unknown)}")
    return Pack(folder, manifest)


class PackStore:
    def __init__(self, events: EventBus, home: Path, samples: DeviceLibrary, pads: PadEditor,
                 save_pattern: Callable[[str, str], Any], save_song: Callable[[str, str], Any],
                 upload_design: Callable[[str], int]):
        """upload_design(name) puts one of koii studio's designs on the device and returns its slot."""
        self.events = events
        self.folder = home / "packs"
        self.state_path = home / "packs-installed.json"
        self.samples = samples
        self.pads = pads
        self.save_pattern = save_pattern
        self.save_song = save_song
        self.upload_design = upload_design
        self._job: Optional[threading.Thread] = None
        self._status: Dict[str, Any] = {"running": False}

    # -- reading ----------------------------------------------------------------------

    def packs(self) -> List[Pack]:
        if not self.folder.exists():
            return []
        found = []
        for folder in sorted(p for p in self.folder.iterdir() if (p / "pack.json").exists()):
            try:
                found.append(read_pack(folder))
            except PackError as error:
                logger.warning("skipping a pack: %s", error)
        return found

    def get(self, name: str) -> Pack:
        for pack in self.packs():
            if pack.name == name:
                return pack
        raise PackError(f"no pack called '{name}'; packs: {', '.join(p.name for p in self.packs()) or 'none'}")

    def list(self) -> List[Dict[str, Any]]:
        state = self._state()
        listed = []
        for pack in self.packs():
            installed = state.get(pack.name)
            manifest = pack.manifest
            listed.append({
                "name": pack.name, "title": manifest.get("title", pack.name), "description": manifest.get("description", ""),
                "credits": manifest.get("credits", []), "samples": len(manifest.get("samples", [])),
                "bytes": pack.sample_bytes(), "songs": sorted(manifest.get("songs", {})),
                "patterns": len(manifest.get("patterns", {})),
                "installed": {"project": installed["project"], "slots": sorted(installed["slots"].values())} if installed else None,
            })
        return listed

    def status(self) -> Dict[str, Any]:
        return dict(self._status)

    # -- installing -------------------------------------------------------------------

    def start_install(self, name: str, project: int) -> Dict[str, Any]:
        """Install in the background; progress arrives as 'pack' events and in status()."""
        pack = self.get(name)
        return self._start(pack, "starting", f"installing '{pack.manifest.get('title', name)}' into project {project}…",
                           self.install, project)

    def start_remove(self, name: str) -> Dict[str, Any]:
        pack = self.get(name)
        return self._start(pack, "removing", f"removing '{name}'…", self.remove)

    def _start(self, pack: Pack, stage: str, message: str, work: Callable, *args) -> Dict[str, Any]:
        if self._job and self._job.is_alive():
            raise PackError(f"already busy with {self._status.get('pack')}; wait for it to finish")
        self._status = {"running": True, "pack": pack.name, "stage": stage, "done": 0, "total": 0, "error": None}
        self._job = threading.Thread(target=self._run, args=(work, pack, *args), name="koii-studio-pack", daemon=True)
        self._job.start()
        return {"message": message, **self.status()}

    def _run(self, work: Callable, *args) -> None:
        try:
            result = work(*args)
            self._status.update(running=False, stage="done", message=result["message"])
        except Exception as error:  # report anything; the device and files are left as they are
            logger.exception("pack job failed")
            self._status.update(running=False, stage="failed", error=str(error))
        self.events.publish("pack", **self._status)

    def _progress(self, stage: str, done: int, total: int, detail: str = "") -> None:
        self._status.update(stage=stage, done=done, total=total, detail=detail)
        self.events.publish("pack", **self._status)

    def install(self, pack: Pack, project: int) -> Dict[str, Any]:
        manifest = pack.manifest
        state = self._state()
        record = state.get(pack.name) or {"project": project, "slots": {}, "designs": {}}
        record["designs"] = {}   # upload_design checks the device itself
        samples = manifest.get("samples", [])
        pads = manifest.get("pads", {})
        steps = len(samples) + len(pads) + 1

        # 1. the pack's samples: keep ones already on the device, upload the rest. One listing up
        # front answers both "is it still ours?" and "which slots are free?" for every sample.
        listing = self.samples.sounds(refresh=True)
        used = {s.slot for s in listing}
        for index, sample in enumerate(samples):
            self._progress("uploading", index, steps, sample["name"])
            slot = record["slots"].get(sample["id"])
            if slot and self.samples.is_ours(slot, listing):
                continue
            audio = load_for_device(pack.sample_path(sample).read_bytes())
            slot = self.samples.suggest_slot(also_taken=used)
            self.samples.upload(slot, to_pcm(audio), sample["name"], audio.shape[0], sample.get("settings"))
            used.add(slot)
            record["slots"][sample["id"]] = slot
            state[pack.name] = record
            self._save_state(state)   # after every upload, so an interrupted install can carry on

        # 2. the project, then its pads
        self.pads.open_project(project)
        record["project"] = project
        for index, (pad, source) in enumerate(pads.items(), start=len(samples)):
            self._progress("pads", index, steps, pad)
            settings = {key: source[key] for key in PAD_SETTINGS if key in source}
            if "sample" in source:
                settings["sound"] = record["slots"][source["sample"]]
            elif "sound" in source:
                settings["sound"] = source["sound"]
            elif "design" in source:
                if source["design"] not in record["designs"]:   # each design once per install, however many pads use it
                    record["designs"][source["design"]] = self.upload_design(source["design"])
                settings["sound"] = record["designs"][source["design"]]
            self.pads.set(pad, **settings)

        # 3. patterns and songs
        self._progress("library", steps - 1, steps)
        for name, text in manifest.get("patterns", {}).items():
            self.save_pattern(name, text)
        for name, arrangement in manifest.get("songs", {}).items():
            self.save_song(name, arrangement)

        record["installed"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        state[pack.name] = record
        self._save_state(state)
        self.events.publish("samples", stage="changed")
        songs = ", ".join(sorted(manifest.get("songs", {}))) or "none"
        return {"message": f"'{manifest.get('title', pack.name)}' is in project {project}: "
                           f"{len(samples)} samples, {len(pads)} pads; songs: {songs}"}

    def remove(self, pack: Pack) -> Dict[str, Any]:
        """Delete the pack's samples from the device and empty the pads that played them."""
        state = self._state()
        record = state.get(pack.name)
        if not record:
            raise PackError(f"'{pack.name}' isn't installed")
        slots = dict(record["slots"])
        self.pads.open_project(record["project"])
        pads = [pad for pad, source in pack.manifest.get("pads", {}).items() if "sample" in source]
        total = len(pads) + len(slots)
        for index, pad in enumerate(pads):
            self._progress("emptying pads", index, total, pad)
            self.pads.set(pad, sound=0)
        deleted = 0
        for index, (sample, slot) in enumerate(slots.items(), start=len(pads)):
            self._progress("deleting", index, total, sample)
            try:
                self.samples.delete_upload(slot)
                deleted += 1
            except UploadRefused as error:   # already gone, or changed on the device: leave it
                logger.info("not deleting slot %s: %s", slot, error)
        del state[pack.name]
        self._save_state(state)
        self.events.publish("samples", stage="changed")
        return {"message": f"removed '{pack.name}': {deleted} samples deleted, {len(pads)} pads emptied in project "
                           f"{record['project']}; its songs stay in the library"}

    # -- state ------------------------------------------------------------------------

    def _state(self) -> Dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=1))

