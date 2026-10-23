"""
MCP server for the Teenage Engineering EP-133 K.O. II.

Tools are thin wrappers around koii.studio.Studio. Errors (bad notation, unknown
names, no device) are raised with messages written to be fixed from directly.
"""

import atexit
import functools
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from mcp.server.fastmcp import FastMCP

from koii import device
from koii.studio import Studio
from koii.visualiser import DEFAULT_PORT, Visualiser, open_in_browser

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

INSTRUCTIONS = """\
Control a Teenage Engineering EP-133 K.O. II over MIDI and make beats and songs with the user.

Pattern notation (full spec: the notation_guide prompt):
  @bpm 96            optional: tempo (default 120), @swing 50-75, @grid 1/16 (default), @map name = target
  kick:  x...x...x...x...      one character = one step (16th note); spaces and | are ignored
  snare: ....x.......x...      x hit, X accent, o ghost, 1-9 level, . rest, - hold previous note
  hat:   x.x.                  a shorter track repeats if it divides the pattern length
  bass:  x..x..x.x-..x...      pitched track: needs a channel target and a notes line
  bass notes: C1 C1 Eb1 G0     each hit takes the next note (cycles); chords: C3+Eb3+G3; C4 = 60
Pitched notes C2-B5 (36-83) also trigger pads by default; keep basslines below C2 unless the user has set
the device's receive channel. check_pattern warns about clashes.
Sounds: kit aliases (kick snare hat oh clap rim ride perc ... see show_kit), pads (A. A0 AEnter A1-A9, B.., C.., D..),
MIDI notes (36), or chN for pitched notes on MIDI channel N.
Songs/arrangements: "intro x2, verse x4, verse+bassline x4, outro" (a+b layers patterns).

Workflow: check_pattern to validate without sound, play to listen (non-blocking; loop=True keeps going and a new
play switches at the end of the current loop), save_pattern / save_song to keep work (persists across restarts),
export_midi for a .mid file. Errors name the line and column; fix them and retry.

Sound design (full guide: the sound_design_guide prompt): designs are JSON (layers of engines → filters and
envelopes → an effects chain → instrument settings for the device). Start from sound_presets / design_sound(preset=...),
change values, listen in the visualiser (design_sound shows it there), vary_sound / morph_sounds to explore, then
upload_design puts it on the device with root note, loop and play mode set. make_kit builds twelve sounds in a style.

Visualiser: a live browser view of the device, patterns, sheet music and everything you do here. open_visualiser
opens it. Without a device, connect(port="simulator") plays sound in the browser instead.
"""

studio = Studio()
visualiser = Visualiser(studio, port=int(os.environ.get("KOII_WEB_PORT", DEFAULT_PORT)))
atexit.register(lambda: studio.disconnect())


@asynccontextmanager
async def lifespan(app: FastMCP) -> AsyncIterator[None]:
    """Run the visualiser alongside the MCP server (set KOII_WEB=off to disable it)."""
    if os.environ.get("KOII_WEB", "on").lower() not in ("0", "off", "false", "no"):
        try:
            visualiser.start()
        except OSError as e:
            logging.getLogger(__name__).warning("visualiser not started: %s", e)
    try:
        yield
    finally:
        visualiser.stop()


server = FastMCP("koii", instructions=INSTRUCTIONS, lifespan=lifespan)


def _brief(value: Any) -> Any:
    """Arguments as the activity feed shows them: a design becomes its name."""
    if isinstance(value, dict):
        return f"design '{value['name']}'" if "name" in value else "{…}"
    if isinstance(value, list) and len(value) > 6:
        return f"[{len(value)} items]"
    return value


def tool(function):
    """Register an MCP tool and show each call in the visualiser's activity feed."""

    @functools.wraps(function)
    def recorded(*args, **kwargs):
        shown = {key: _brief(value) for key, value in kwargs.items()}
        try:
            result = function(*args, **kwargs)
        except Exception as e:
            studio.events.activity("claude", function.__name__, shown, error=str(e))
            raise
        text = result.get("message") or result.get("summary") if isinstance(result, dict) else result
        summary = text.splitlines()[0] if isinstance(text, str) and text else None
        studio.events.activity("claude", function.__name__, shown, result=summary)
        return result

    return server.tool()(recorded)


# -- device -----------------------------------------------------------------

@tool
def open_visualiser(open_browser: bool = True) -> str:
    """
    Open the live visualiser in the browser: a KO II simulator, step grid, sheet music, loop editor,
    library and a feed of what you're doing. Returns its URL.
    """
    url = visualiser.url or visualiser.start()
    if open_browser:
        open_in_browser(url)
    return f"visualiser at {url}"


@tool
def list_midi_ports() -> list[str]:
    """List MIDI output ports on this computer."""
    return studio.list_ports()


@tool
def connect(port: Optional[str] = None, channel: int = 1) -> str:
    """
    Connect to the EP-133 (auto-detected) or to a named MIDI output port.

    Args:
        port: Full or partial port name. Omit to find the EP-133 automatically. "simulator" plays in the
            visualiser instead, for trying things without a device.
        channel: MIDI channel (1-16) for pad hits. The EP-133 receives on all channels by default.
    """
    return studio.connect(port, channel)


@tool
def disconnect() -> str:
    """Stop playback and close the MIDI connection."""
    return studio.disconnect()


@tool
def status() -> str:
    """Connection, what's playing, and what's saved."""
    port = getattr(studio.port, "name", None)
    lines = [
        f"device: {port + f' (channel {studio.channel})' if port else 'not connected'}",
        f"playing: {studio.player.status or 'nothing'}",
        f"library: {len(studio.library.patterns)} patterns, {len(studio.library.songs)} songs ({studio.library.path})",
        f"visualiser: {visualiser.url or 'not running'}",
        f"backups: {studio.samples.backup_status_text()}",
    ]
    return "\n".join(lines)


# -- making music -----------------------------------------------------------

@tool
def check_pattern(text: str) -> str:
    """
    Validate pattern text without playing it. Returns a normalised view (sounds, pads, MIDI notes,
    steps grouped by beat) or every error with its line and column. Works without a device.
    """
    return studio.check(text)


@tool
def play(what: str, repeat: int = 1, loop: bool = False, bpm: Optional[int] = None) -> str:
    """
    Play something on the EP-133. Returns immediately; playback continues in the background.

    Args:
        what: Pattern text (e.g. "kick: x...x...x...x...\\nsnare: ....x.......x..."), a saved pattern or song
            name, layered patterns ("drums+bass"), or an arrangement ("intro x2, verse x4, chorus x4").
        repeat: Play it this many times.
        loop: Keep looping until stop(). While something loops, calling play again switches to the new
            material at the end of the current pass and keeps looping, so you can iterate seamlessly.
        bpm: Override the tempo.
    """
    return studio.play(what, repeat, loop, bpm)


@tool
def stop() -> str:
    """Stop playback immediately."""
    return studio.stop()


@tool
def audition(sound: str, velocity: int = 100, note: Optional[str] = None) -> str:
    """
    Play a single hit to hear what a sound name or pad is (e.g. "kick", "A7", "36").
    For a pitched target (chN or an alias to one) pass `note`, e.g. "C1" (default; notes C2 and up also trigger pads).
    """
    return studio.audition(sound, velocity, note)


# -- library ----------------------------------------------------------------

@tool
def save_pattern(name: str, text: str) -> str:
    """Validate and save a pattern under a name (overwrites). Saved work persists across restarts."""
    return studio.save_pattern(name, text)


@tool
def save_song(name: str, arrangement: str, bpm: Optional[int] = None) -> str:
    """
    Save an arrangement of saved patterns as a song, e.g. "intro x2, verse x4, verse+bass x4, chorus x8, outro".
    `name xN` repeats, `a+b` layers patterns, sections are separated by commas or new lines.
    bpm overrides every section's tempo.
    """
    return studio.save_song(name, arrangement, bpm)


@tool
def show(name: str) -> str:
    """Show a saved pattern's text and normalised view, or a song's arrangement and timings."""
    return studio.show(name)


@tool
def list_library() -> str:
    """List saved patterns and songs."""
    return studio.list_library()


@tool
def delete(name: str) -> str:
    """Delete a saved pattern or song."""
    return studio.delete(name)


@tool
def export_midi(what: str, filename: Optional[str] = None, bpm: Optional[int] = None) -> str:
    """
    Write a Standard MIDI File (.mid) of a pattern, saved name, layer or arrangement, for use in a DAW.
    Files go to the exports folder next to the library. Works without a device.
    """
    return studio.export_midi(what, filename, bpm)


@tool
def export_musicxml(what: str, filename: Optional[str] = None) -> str:
    """
    Write sheet music (MusicXML) for pattern text or a saved pattern: a drum staff plus a staff per
    pitched track, with rests, ties and triplets. Opens in MuseScore, Dorico, Sibelius and Finale.
    """
    return studio.export_musicxml(what, filename)


# -- the device's sample library ----------------------------------------------

@tool
def list_device_sounds(search: Optional[str] = None) -> str:
    """
    List the samples stored on the EP-133 (slots 1–999): name, length, root note, play mode.
    Read-only. Uses the device's private file protocol; don't run TE's EP Sample Tool at the same time.
    """
    return studio.samples.summary(search)


@tool
def play_sample(slot: int) -> str:
    """Audition a sample slot on the EP-133 itself (raw sample, no trim or envelope)."""
    return studio.samples.audition(slot)


@tool
def upload_sample(path: str, slot: Optional[int] = None, name: Optional[str] = None, keep_stereo: bool = False) -> str:
    """
    Upload a WAV file to the EP-133, converted to its format (46,875 Hz, 16-bit). Uses an empty slot
    (the first free one from 600 if none is given). Refuses unless a complete backup exists, and never
    overwrites a sound koii didn't upload. The result is checked against the device's own checksum.
    """
    return studio.samples.upload_file(path, slot, name, keep_stereo)["message"]


@tool
def delete_upload(slot: int) -> str:
    """Delete a sound koii uploaded (only its own uploads, and only if unchanged since)."""
    return studio.designer.delete_upload(slot)


@tool
def backup_device() -> str:
    """
    Back up every sample (as WAV, checked against the device's checksums) and every project
    to ~/.koii/backups. Read-only on the device. Runs in the background; unchanged samples
    are copied from the previous backup. Progress shows in status() and the visualiser.
    """
    return studio.samples.start_backup()


@tool
def cancel_backup() -> str:
    """Stop a running backup after the current sample (an incomplete backup isn't used later)."""
    return studio.samples.cancel_backup()


# -- sound design -------------------------------------------------------------

DesignInput = Union[Dict[str, Any], str]


def _design(design: Optional[DesignInput], preset: Optional[str] = None) -> Dict[str, Any]:
    """A design given as JSON, the name of a saved design, or a preset name."""
    if preset:
        return studio.designer.preset(preset)
    if isinstance(design, str):
        return studio.designer.designs.get(design)
    if design is None:
        raise ValueError("give a design (JSON), the name of a saved design, or preset=...")
    return design


@tool
def sound_presets() -> dict:
    """Preset names by category (drums, instruments, fx) and the kit styles, as starting points for design_sound."""
    designer_schema = studio.designer.schema()
    return {"presets": designer_schema["presets"], "kit_styles": designer_schema["kit_styles"]}


@tool
def sound_design_schema() -> dict:
    """Every engine, effect and setting a design can use, with ranges, units and defaults."""
    return studio.designer.schema()


@tool
def design_sound(design: Optional[DesignInput] = None, preset: Optional[str] = None, show: bool = True) -> dict:
    """
    Render a sound design and describe it: pitch, loudness, brightness, envelope, how it'll be set up
    on the device (root, loop, play mode) and the closest sounds already on the device. Returns the
    complete design (defaults filled in) to edit and pass back. show=True opens it in the visualiser's
    designer so the user can hear it and tweak it.
    """
    chosen = _design(design, preset)
    summary = studio.designer.describe(chosen)
    checked = studio.designer.show(chosen) if show else studio.designer.preview(chosen, similar=False)["design"]
    return {"summary": summary, "design": checked}


@tool
def vary_sound(design: DesignInput, amount: float = 0.3, locks: Optional[List[str]] = None, count: int = 4,
               seed: Optional[int] = None) -> dict:
    """
    Variations of a design. amount: 0.1 subtle, 0.3 related, 0.7 wild. locks keep parts fixed, as dotted
    paths with * wildcards: "layers.0", "layers.*.amp", "effects", "layers.1.params.wave". Length stays
    fixed unless "!length" is in locks. The first variation opens in the visualiser.
    """
    variations = studio.designer.vary(_design(design), amount, locks or [], count, seed)
    studio.designer.show(variations[0])
    return {"variations": [{"summary": studio.designer.describe(v).splitlines()[0], "design": v} for v in variations]}


@tool
def morph_sounds(a: DesignInput, b: DesignInput, t: float = 0.5) -> dict:
    """A design part way between two (t = 0 is a, 1 is b). Matching layers blend; others crossfade."""
    morphed = studio.designer.morph(_design(a), _design(b), t)
    studio.designer.show(morphed)
    return {"summary": studio.designer.describe(morphed), "design": morphed}


@tool
def save_design(design: Dict[str, Any], name: Optional[str] = None) -> str:
    """Keep a design in the library (~/.koii/designs.json) under its name, or the name given."""
    return f"saved design '{studio.designer.save(design, name)}'"


@tool
def list_designs() -> dict:
    """Saved designs (with the device slots they're uploaded to) and the recorded or loaded sources."""
    return studio.designer.library()


@tool
def upload_design(design: DesignInput, slot: Optional[int] = None) -> str:
    """
    Render a design and upload it to the EP-133 with instrument settings: the detected root note and
    fine tune, a seamless crossfaded loop if instrument.loop is "auto", play mode, envelope, level and
    tempo. Same rules as upload_sample (backup first, empty or koii's own slots only, checksum verified).
    The design is saved and linked to the slot. Uploading takes about a second per 5 KB.
    """
    return studio.designer.upload(_design(design), slot)["message"]


@tool
def change_sound_settings(slot: int, playmode: Optional[str] = None, attack: Optional[int] = None,
                          release: Optional[int] = None, amplitude: Optional[int] = None,
                          bpm: Optional[float] = None, bars: Optional[float] = None) -> str:
    """
    Change one of koii's uploads in place (no re-upload): playmode oneshot/key/legato, the device's
    attack and release (0–255), amplitude (0–100), or tempo sync (bpm and bars; bpm=0 turns it off).
    """
    instrument: Dict[str, Any] = {key: value for key, value in
                                  {"playmode": playmode, "attack": attack, "release": release,
                                   "amplitude": amplitude}.items() if value is not None}
    if bpm is not None:
        instrument.update({"tempo": "off"} if bpm == 0 else {"tempo": "bpm", "bpm": bpm, "bars": bars or 1})
    if not instrument:
        raise ValueError("nothing to change: give playmode, attack, release, amplitude or bpm")
    stored = studio.designer.change_settings(slot, instrument)
    shown = {key: stored.get(key) for key in ("sound.playmode", "envelope.attack", "envelope.release",
                                              "sound.amplitude", "time.mode", "sound.bpm", "sound.bars")}
    return f"slot {slot} now: " + ", ".join(f"{key} {value}" for key, value in shown.items())


@tool
def make_kit(style: str = "808", upload: bool = False, first_slot: Optional[int] = None) -> dict:
    """
    Twelve designs in a style (808, 909, lofi, acoustic, industrial, glitch), in group A pad order.
    upload=True puts them in twelve consecutive empty slots in the background (a couple of minutes;
    progress in kit_status and the visualiser) and returns which pad gets which slot.
    """
    kit = studio.designer.kit(style)
    if not upload:
        return {"kit": [{"pad": item["pad"], "role": item["role"], "name": item["design"]["name"]} for item in kit],
                "designs": [item["design"] for item in kit]}
    started = studio.designer.start_kit_upload(style, first_slot)
    return {"message": started["message"], "first_slot": started["first"]}


@tool
def kit_status() -> dict:
    """Progress of a kit or slice upload started by make_kit or the visualiser."""
    return studio.designer.kit_status()


@tool
def chop_source(source: str, slices: Optional[int] = None, starts: Optional[List[float]] = None,
                sensitivity: float = 0.5, upload: bool = False, first_slot: Optional[int] = None) -> dict:
    """
    Cut a recorded or loaded source (see list_designs) into slices: equal parts (slices=8), at given times
    in seconds (starts=[...]), or at detected hits (neither; sensitivity 0–1). upload=True puts up to
    twelve slices in consecutive empty slots, in the background.
    """
    pieces = studio.designer.chop(source, [], starts, slices, sensitivity)
    result: Dict[str, Any] = {"slices": [{"id": p["id"], "name": p["name"], "seconds": p["seconds"]} for p in pieces]}
    if upload:
        result["upload"] = studio.designer.upload_slices([p["id"] for p in pieces], first_slot)["message"]
    return result


# -- kit --------------------------------------------------------------------

@tool
def show_kit() -> str:
    """Every pad with its MIDI note, factory Project 1 sound, and the aliases that point at it."""
    return studio.show_kit()


@tool
def set_alias(name: str, target: str) -> str:
    """
    Name a sound so patterns can use it, e.g. set_alias("cowbell", "A7") or set_alias("bass", "ch2")
    for a pitched bass on MIDI channel 2. Overrides built-in aliases. Persists.
    """
    return studio.set_alias(name, target)


@tool
def remove_alias(name: str) -> str:
    """Remove an alias you set (built-in aliases revert to their default)."""
    return studio.remove_alias(name)


@tool
def list_factory_sounds(category: Optional[str] = None) -> dict:
    """
    The EP-133 factory sound list (community-transcribed from the device; not an official TE list).
    Omit category to list categories.
    """
    if category is None:
        return {name: len(sounds) for name, sounds in device.FACTORY_SOUNDS.items()}
    for name, sounds in device.FACTORY_SOUNDS.items():
        if name.lower() == category.lower():
            return sounds
    raise ValueError(f"unknown category '{category}'. Categories: {', '.join(device.FACTORY_SOUNDS)}")


# -- prompts ----------------------------------------------------------------

def _read_doc(name: str) -> str:
    path = Path(__file__).resolve().parent.parent / name
    return path.read_text() if path.exists() else f"({name} not found next to the package)"


@server.prompt()
def notation_guide() -> str:
    """The full KOII pattern notation spec."""
    return _read_doc("NOTATION.md")


@server.prompt()
def device_guide() -> str:
    """EP-133 MIDI facts, setup for pitched tracks, and troubleshooting."""
    return _read_doc("DEVICE.md")


@server.prompt()
def sound_design_guide() -> str:
    """How designs work: engines, modulation, effects, instrument settings, variation and recipes."""
    return _read_doc("SOUND_DESIGN.md")


@server.prompt()
def design_a_sound(idea: str = "a warm, dusty electric piano") -> str:
    """Start a sound design session."""
    return (
        f"Let's design {idea} for my EP-133. Read the sound_design_guide, start from the closest preset with "
        "design_sound, and tell me what you hear in the analysis. Change one or two things at a time, show each "
        "version in the visualiser so I can listen, and offer vary_sound when we want ideas. When I'm happy, "
        "upload it with upload_design and tell me which slot and how to put it on a pad."
    )


@server.prompt()
def make_a_beat(style: str = "boom bap", bpm: int = 90) -> str:
    """Start a collaborative beat-making session."""
    return (
        f"Let's make a {style} beat at around {bpm} BPM on my EP-133. Connect to it, check the kit, then write "
        "a one-bar drum pattern, check it, and play it on loop. Keep the loop running while we iterate: "
        "propose one change at a time, play it (it'll switch at the end of the loop), and save versions we like. "
        "When we have a few parts, arrange them into a song."
    )


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
