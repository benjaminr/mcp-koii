import json
import threading
import time

import pytest

from koii.library import Library, LibraryError
from koii.notation import NotationError, parse_pattern
from koii.player import Player
from koii.sequence import layer
from koii.studio import NotConnected, Studio


class FakePort:
    name = "EP-133"

    def __init__(self):
        self.messages = []
        self.lock = threading.Lock()

    def send(self, msg):
        with self.lock:
            self.messages.append((time.perf_counter(), msg))

    def close(self):
        pass


@pytest.fixture
def port():
    return FakePort()


@pytest.fixture
def studio(tmp_path, port):
    s = Studio(library=Library(tmp_path), open_output=lambda name: port,
               list_outputs=lambda: ["IAC Bus", port.name])
    yield s
    s.disconnect()


def note_ons(port):
    return [m for _, m in port.messages if m.type == "note_on"]


# -- connection ---------------------------------------------------------------

def test_finds_the_ep133_among_other_ports(studio):
    assert "EP-133" in studio.connect()


def test_connect_explains_what_went_wrong(tmp_path):
    s = Studio(library=Library(tmp_path), open_output=lambda n: FakePort(), list_outputs=lambda: ["IAC Bus"])
    with pytest.raises(NotConnected, match="couldn't spot the EP-133"):
        s.connect()
    with pytest.raises(NotConnected, match="no MIDI output matching"):
        s.connect("nope")
    assert "IAC" in s.connect("iac")


def test_midi_system_errors_are_readable(tmp_path):
    def broken():
        raise SystemError("MidiInAlsa::initialize: error creating ALSA sequencer client object.")
    s = Studio(library=Library(tmp_path), list_outputs=broken)
    with pytest.raises(NotConnected, match="couldn't query MIDI ports"):
        s.connect()


def test_notation_errors_come_before_needing_a_device(studio):
    with pytest.raises(NotationError):
        studio.play("kick: x.v.")
    with pytest.raises(NotConnected):
        studio.play("kick: x...")


# -- playback -----------------------------------------------------------------

def test_plays_the_pattern_on_the_connection_channel(studio, port):
    studio.connect(channel=5)
    studio.play("@bpm 300\nkick: x.x.\nsnare: ..x.")
    assert studio.player.wait(5)
    assert [(m.note, m.channel) for m in note_ons(port)] == [(36, 4), (36, 4), (39, 4)]
    assert not studio.player.status


def test_timing_does_not_drift_over_many_steps(studio, port):
    studio.connect()
    studio.play("@bpm 300\nhat: xxxxxxxxxxxxxxxx", repeat=2)  # 32 hits, 50 ms apart
    studio.player.wait(5)
    times = [t for t, m in port.messages if m.type == "note_on"]
    expected = [times[0] + i * 0.05 for i in range(32)]
    assert max(abs(a - b) for a, b in zip(times, expected)) < 0.01


def test_new_material_replaces_a_loop_at_the_end_of_the_pass(studio, port):
    studio.connect()
    studio.play("@bpm 300\nkick: x---", loop=True)
    time.sleep(0.05)
    assert "looping" in studio.player.status
    assert studio.play("@bpm 300\nsnare: x...").startswith("queued")
    time.sleep(0.5)
    notes = [m.note for m in note_ons(port)]
    assert notes[0] == 36 and notes.index(39) > 0
    assert notes[-2:] == [39, 39]  # the queued pattern keeps looping
    assert studio.stop() == "stopped"
    ons = sum(1 for _, m in port.messages if m.type == "note_on")
    offs = sum(1 for _, m in port.messages if m.type == "note_off")
    assert ons == offs  # nothing left hanging
    assert studio.stop() == "nothing was playing"


def test_stopping_mid_note_sends_note_off():
    sent = []
    player = Player(sent.append)
    pattern = parse_pattern("@bpm 30\nkick: x---------------")
    player.play([layer([("p", pattern)])], default_channel=1, loop=False, label="p")
    time.sleep(0.05)
    assert player.stop()
    assert [m.type for m in sent] == ["note_on", "note_off"]


# -- library ------------------------------------------------------------------

def test_saved_work_survives_a_restart(studio, tmp_path):
    out = studio.save_pattern("verse", "@bpm 90\nkick: x...x...\nhat: x.")
    assert out.startswith("saved pattern 'verse'") and "90 BPM" in out
    assert studio.save_pattern("Verse", "kick: x...").startswith("updated")
    studio.save_pattern("verse", "@bpm 90\nkick: x...x...")
    studio.save_pattern("fill", "snare: xxxx")
    assert "verse ×4" in studio.save_song("song", "verse x4, fill")
    assert "pattern  verse" in studio.list_library() and "song     song" in studio.list_library()
    assert "kick: x...x..." in studio.show("VERSE")

    reloaded = Library(tmp_path)
    assert set(reloaded.patterns) == {"verse", "fill"} and "song" in reloaded.songs
    assert json.loads((tmp_path / "library.json").read_text())["version"] == 1

    assert studio.delete("fill") == "deleted pattern 'fill'"
    with pytest.raises(NotationError, match="no pattern named 'fill'"):
        studio.show("song")


def test_names_are_unique_across_patterns_and_songs(studio):
    studio.save_pattern("a", "kick: x...")
    studio.save_song("s", "a x2")
    with pytest.raises(LibraryError, match="already a pattern"):
        studio.save_song("a", "a")
    with pytest.raises(LibraryError, match="already a song"):
        studio.save_pattern("s", "kick: x...")
    with pytest.raises(LibraryError, match="looks like a pad"):
        studio.save_pattern("A1", "kick: x...")


def test_invalid_patterns_and_songs_are_not_saved(studio):
    with pytest.raises(NotationError):
        studio.save_pattern("bad", "kick: xv")
    with pytest.raises(NotationError, match="no pattern named 'ghost'"):
        studio.save_song("s", "ghost x2")
    assert studio.library.names() == []


def test_plays_saved_layers_and_arrangements(studio, port):
    studio.connect()
    studio.save_pattern("d", "@bpm 300\nkick: x...")
    studio.save_pattern("b", "@bpm 300\n@map bass = ch2\nbass: ..x.\nbass notes: C2")
    assert "d+b ×2" in studio.play("d+b x2")
    studio.player.wait(5)
    assert [(m.note, m.channel) for m in note_ons(port)] == [(36, 0), (36, 1), (36, 0), (36, 1)]


def test_aliases_can_be_added_overridden_and_reverted(studio):
    assert studio.set_alias("Cowbell", "a9") == "'cowbell' now plays A9"
    assert "cowbell" in studio.show_kit()
    studio.set_alias("bass", "ch2")
    p = studio.library.parse("cowbell: x...\nbass: x...\nbass notes: C2")
    assert p.tracks[0].target.label == "A9" and p.tracks[1].target.channel == 2
    assert "back to the built-in B." in studio.remove_alias("bass")
    with pytest.raises(LibraryError, match="isn't a pad"):
        studio.set_alias("x", "Z9")
    with pytest.raises(LibraryError, match="built in"):
        studio.remove_alias("kick")


def test_audition_plays_one_hit(studio, port):
    studio.connect()
    assert studio.audition("rim") == "played rim → A3 (note 41)"
    studio.player.wait(5)
    studio.set_alias("lead", "ch4")
    assert studio.audition("lead", note="A3") == "played lead → ch4 at A3"
    studio.player.wait(5)
    assert [(m.note, m.channel) for m in note_ons(port)] == [(41, 0), (57, 3)]


def test_export_writes_a_midi_file(studio, tmp_path):
    studio.save_pattern("v", "kick: x...x...x...x...")
    out = studio.export_midi("v x2", filename="my song")
    assert (tmp_path / "exports" / "my song.mid").exists() and "4.0s" in out
