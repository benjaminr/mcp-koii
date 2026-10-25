import json
import threading
import time

import mido
import pytest

from koii_studio.library import Library, LibraryError
from koii_studio.notation import NotationError, parse_pattern
from koii_studio.player import Player
from koii_studio.sequence import layer
from koii_studio.studio import NotConnected, Studio


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


class FakeInput:
    def __init__(self, name, callback):
        self.name = name
        self.callback = callback
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def inputs():
    return []


@pytest.fixture
def studio(tmp_path, port, inputs):
    def open_input(name, callback):
        inputs.append(FakeInput(name, callback))
        return inputs[-1]

    s = Studio(library=Library(tmp_path), open_output=lambda name: port,
               list_outputs=lambda: ["IAC Bus", port.name], open_input=open_input)
    yield s
    s.disconnect()


def note_ons(port):
    return [m for _, m in port.messages if m.type == "note_on"]


# -- connection ---------------------------------------------------------------

def test_finds_the_ep133_among_other_ports(studio):
    assert "EP-133" in studio.connect()


def test_connect_explains_what_went_wrong(tmp_path):
    s = Studio(library=Library(tmp_path), open_output=lambda n: FakePort(), list_outputs=lambda: ["IAC Bus"],
               open_input=None)
    with pytest.raises(NotConnected, match="couldn't spot the EP-133"):
        s.connect()
    with pytest.raises(NotConnected, match="no MIDI output matching"):
        s.connect("nope")
    assert "IAC" in s.connect("iac")


def test_midi_system_errors_are_readable(tmp_path):
    def broken():
        raise SystemError("MidiInAlsa::initialize: error creating ALSA sequencer client object.")
    s = Studio(library=Library(tmp_path), list_outputs=broken, open_input=None)
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


def test_play_summary_counts_repeats(studio):
    studio.connect()
    studio.save_pattern("v", "@bpm 120\nkick: x...x...x...x...")
    out = studio.play("v", repeat=2)
    studio.stop()
    assert "v ×2" in out and "total 4.0s" in out
    out = studio.play("kick: x...x...x...x...", repeat=3)
    studio.stop()
    assert "pattern ×3" in out and "total 6.0s" in out


def test_pads_pressed_on_the_device_are_reported(studio, inputs):
    studio.connect()
    events = studio.events.subscribe()
    (device_input,) = inputs
    assert device_input.name == "EP-133"
    device_input.callback(mido.Message("note_on", note=37, velocity=100))
    device_input.callback(mido.Message("clock"))
    event = events.get(timeout=1)
    assert (event["type"], event["note"], event["on"]) == ("device_note", 37, True)
    assert events.empty()
    studio.disconnect()
    assert device_input.closed


def test_simulator_connection_needs_no_hardware(tmp_path):
    s = Studio(library=Library(tmp_path), list_outputs=lambda: [], open_input=None)
    assert "simulator" in s.connect("simulator")
    assert s.connection_state()["simulated"]
    s.play("@bpm 300\nkick: x...")
    assert s.player.wait(5)


def test_playback_reports_notes_and_passes(studio):
    studio.connect()
    events = studio.events.subscribe()
    studio.save_pattern("v", "@bpm 300\nkick: x.x.")
    studio.play("v x2")
    studio.player.wait(5)
    seen = []
    while not events.empty():
        seen.append(events.get())
    passes = [e for e in seen if e["type"] == "pass"]
    assert len(passes) == 1
    info = passes[0]["info"]
    assert info["order"] == [0, 0] and info["sections"][0]["patterns"][0]["name"] == "v"
    assert sum(1 for e in seen if e["type"] == "note" and e["on"]) == 4
    assert seen[-1]["type"] == "stopped"


def test_playing_now_switches_straight_away_instead_of_waiting_for_the_loop(studio, port):
    studio.connect()
    studio.play("@bpm 30\nkick: x---", loop=True)    # one pass lasts 8 s
    time.sleep(0.05)
    reply = studio.play("@bpm 300\nsnare: x...", loop=True, now=True)
    assert not reply.startswith("queued")
    time.sleep(0.3)
    assert 39 in [m.note for m in note_ons(port)]   # the snare started long before the kick's pass would end
    assert "looping" in studio.player.status
    studio.stop()
    ons = sum(1 for _, m in port.messages if m.type == "note_on")
    offs = sum(1 for _, m in port.messages if m.type == "note_off")
    assert ons == offs  # the held kick was released when it was cut off


def test_audition_does_not_interrupt_a_loop(studio, port):
    studio.connect()
    studio.play("@bpm 300\nkick: x...", loop=True)
    studio.audition("snare")
    time.sleep(0.3)
    assert "looping" in studio.player.status
    assert 39 in [m.note for m in note_ons(port)]


def test_a_page_opened_mid_loop_can_see_the_current_pass(studio):
    studio.connect()
    assert studio.events.current_pass() is None
    studio.play("@bpm 300\nkick: x...", loop=True)
    time.sleep(0.1)
    assert studio.events.current_pass()["loop"] is True
    studio.stop()
    assert studio.events.current_pass() is None


def test_musicxml_export_for_text_and_saved_patterns(studio, tmp_path):
    studio.save_pattern("groove", "kick: x...x...\nsnare: ....x...")
    out = studio.export_musicxml("groove")
    path = tmp_path / "exports" / "groove.musicxml"
    assert path.exists() and "MuseScore" in out
    assert "<score-partwise" in path.read_text() and "<work-title>groove</work-title>" in path.read_text()
    xml, name = studio.musicxml("kick: x...")
    assert name == "pattern" and "<unpitched>" in xml
    with pytest.raises(LibraryError, match="one pattern at a time"):
        studio.musicxml("groove x2")


def test_check_includes_the_score_and_voice_warnings(studio):
    result = studio.check_pattern("kick: x...")
    assert result["score"]["staves"][0]["bars"][0][0]["value"] == "quarter"
    crowded = "@map k = ch3\nk: x...\nk notes: " + "+".join(f"C{o}" for o in range(1, 5)) + "+" + "+".join(
        f"E{o}" for o in range(1, 5)) + "+" + "+".join(f"G{o}" for o in range(1, 6))
    assert any("at most 16 mono or 12 stereo voices" in w for w in studio.check_pattern(crowded)["warnings"])
