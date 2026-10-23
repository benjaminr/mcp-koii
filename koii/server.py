"""
MCP server for the Teenage Engineering EP-133 K.O. II.

Tools are thin wrappers around koii.studio.Studio. Errors (bad notation, unknown
names, no device) are raised with messages written to be fixed from directly.
"""

import atexit
import logging
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from koii import device
from koii.studio import Studio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

INSTRUCTIONS = """\
Control a Teenage Engineering EP-133 K.O. II over MIDI and make beats and songs with the user.

Pattern notation (full spec: the notation_guide prompt):
  @bpm 96            optional: tempo (default 120), @swing 50-75, @grid 1/16 (default), @map name = target
  kick:  x...x...x...x...      one character = one step (16th note); spaces and | are ignored
  snare: ....x.......x...      x hit, X accent, o ghost, 1-9 level, . rest, - hold previous note
  hat:   x.x.                  a shorter track repeats if it divides the pattern length
  bass:  x..x..x.x-..x...      pitched track: needs a channel target and a notes line
  bass notes: C2 C2 Eb2 G1     each hit takes the next note (cycles); chords: C3+Eb3+G3; C4 = 60
Sounds: kit aliases (kick snare hat oh clap rim ride perc ... see show_kit), pads (A. A0 AEnter A1-A9, B.., C.., D..),
MIDI notes (36), or chN for pitched notes on MIDI channel N.
Songs/arrangements: "intro x2, verse x4, verse+bassline x4, outro" (a+b layers patterns).

Workflow: check_pattern to validate without sound, play to listen (non-blocking; loop=True keeps going and a new
play switches at the end of the current loop), save_pattern / save_song to keep work (persists across restarts),
export_midi for a .mid file. Errors name the line and column; fix them and retry.
"""

server = FastMCP("koii", instructions=INSTRUCTIONS)
studio = Studio()
atexit.register(lambda: studio.disconnect())


# -- device -----------------------------------------------------------------

@server.tool()
def list_midi_ports() -> list[str]:
    """List MIDI output ports on this computer."""
    return studio.list_ports()


@server.tool()
def connect(port: Optional[str] = None, channel: int = 1) -> str:
    """
    Connect to the EP-133 (auto-detected) or to a named MIDI output port.

    Args:
        port: Full or partial port name. Omit to find the EP-133 automatically.
        channel: MIDI channel (1-16) for pad hits. The EP-133 receives on all channels by default.
    """
    return studio.connect(port, channel)


@server.tool()
def disconnect() -> str:
    """Stop playback and close the MIDI connection."""
    return studio.disconnect()


@server.tool()
def status() -> str:
    """Connection, what's playing, and what's saved."""
    port = getattr(studio.port, "name", None)
    lines = [
        f"device: {port + f' (channel {studio.channel})' if port else 'not connected'}",
        f"playing: {studio.player.status or 'nothing'}",
        f"library: {len(studio.library.patterns)} patterns, {len(studio.library.songs)} songs ({studio.library.path})",
    ]
    return "\n".join(lines)


# -- making music -----------------------------------------------------------

@server.tool()
def check_pattern(text: str) -> str:
    """
    Validate pattern text without playing it. Returns a normalised view (sounds, pads, MIDI notes,
    steps grouped by beat) or every error with its line and column. Works without a device.
    """
    return studio.check(text)


@server.tool()
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


@server.tool()
def stop() -> str:
    """Stop playback immediately."""
    return studio.stop()


@server.tool()
def audition(sound: str, velocity: int = 100, note: Optional[str] = None) -> str:
    """
    Play a single hit to hear what a sound name or pad is (e.g. "kick", "A7", "36").
    For a pitched target (chN or an alias to one) pass `note`, e.g. "C2".
    """
    return studio.audition(sound, velocity, note)


# -- library ----------------------------------------------------------------

@server.tool()
def save_pattern(name: str, text: str) -> str:
    """Validate and save a pattern under a name (overwrites). Saved work persists across restarts."""
    return studio.save_pattern(name, text)


@server.tool()
def save_song(name: str, arrangement: str, bpm: Optional[int] = None) -> str:
    """
    Save an arrangement of saved patterns as a song, e.g. "intro x2, verse x4, verse+bass x4, chorus x8, outro".
    `name xN` repeats, `a+b` layers patterns, sections are separated by commas or new lines.
    bpm overrides every section's tempo.
    """
    return studio.save_song(name, arrangement, bpm)


@server.tool()
def show(name: str) -> str:
    """Show a saved pattern's text and normalised view, or a song's arrangement and timings."""
    return studio.show(name)


@server.tool()
def list_library() -> str:
    """List saved patterns and songs."""
    return studio.list_library()


@server.tool()
def delete(name: str) -> str:
    """Delete a saved pattern or song."""
    return studio.delete(name)


@server.tool()
def export_midi(what: str, filename: Optional[str] = None, bpm: Optional[int] = None) -> str:
    """
    Write a Standard MIDI File (.mid) of a pattern, saved name, layer or arrangement, for use in a DAW.
    Files go to the exports folder next to the library. Works without a device.
    """
    return studio.export_midi(what, filename, bpm)


# -- kit --------------------------------------------------------------------

@server.tool()
def show_kit() -> str:
    """Every pad with its MIDI note, factory Project 1 sound, and the aliases that point at it."""
    return studio.show_kit()


@server.tool()
def set_alias(name: str, target: str) -> str:
    """
    Name a sound so patterns can use it, e.g. set_alias("cowbell", "A7") or set_alias("bass", "ch2")
    for a pitched bass on MIDI channel 2. Overrides built-in aliases. Persists.
    """
    return studio.set_alias(name, target)


@server.tool()
def remove_alias(name: str) -> str:
    """Remove an alias you set (built-in aliases revert to their default)."""
    return studio.remove_alias(name)


@server.tool()
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
