from fractions import Fraction

import mido
import pytest

from koii_studio.notation import NotationError, parse_pattern
from koii_studio.sequence import NOTE_OFF, NOTE_ON, compile_pattern, expand, layer, timeline, to_midi_file


def note_ons(events):
    return [(e.beat, e.note, e.velocity, e.channel) for e in events if e.kind == NOTE_ON]


def test_hits_last_one_step_and_holds_extend_them():
    events = compile_pattern(parse_pattern("kick: x.x--..."))
    assert note_ons(events) == [(Fraction(0), 36, 100, None), (Fraction(1, 2), 36, 100, None)]
    offs = [e.beat for e in events if e.kind == NOTE_OFF]
    assert offs == [Fraction(1, 4), Fraction(5, 4)]


def test_note_off_is_sent_before_a_retrigger_at_the_same_time():
    events = compile_pattern(parse_pattern("kick: xx"))
    assert [e.kind for e in events if e.beat == Fraction(1, 4)] == [NOTE_OFF, NOTE_ON]


def test_swing_delays_every_second_step():
    events = compile_pattern(parse_pattern("@swing 66\nhat: xxxx"))
    starts = [e.beat for e in events if e.kind == NOTE_ON]
    step = Fraction(1, 4)
    assert starts == [0, step + step * Fraction(16, 50), 2 * step, 3 * step + step * Fraction(16, 50)]


def test_grid_sets_the_step_length():
    events = compile_pattern(parse_pattern("@grid 1/8t\nhat: xxx"))
    assert [e.beat for e in events if e.kind == NOTE_ON] == [0, Fraction(1, 3), Fraction(2, 3)]


def test_pitched_notes_cycle_and_chords_sound_together():
    p = parse_pattern("@map b = ch2\nb: x.x.x.\nb notes: C2 G1+D2")
    assert note_ons(compile_pattern(p)) == [
        (0, 36, 100, 2), (Fraction(1, 2), 31, 100, 2), (Fraction(1, 2), 38, 100, 2), (1, 36, 100, 2)]


def test_notes_continue_across_repeats_of_a_short_track():
    p = parse_pattern("@map b = ch2\nkick: x...x...\nb: x...\nb notes: C2 D2")
    assert [n for _, n, _, ch in note_ons(compile_pattern(p)) if ch == 2] == [36, 38]


def test_layering_requires_patterns_to_fit_evenly():
    four = parse_pattern("kick: x...x...x...x...")
    three = parse_pattern("hat: x.x.x.x.x.x.")
    with pytest.raises(NotationError, match="doesn't divide"):
        layer([("a", four), ("b", three)])
    section = layer([("a", four), ("b", parse_pattern("hat: x.x.x.x."))])
    assert section.length_beats == 4 and section.label == "a+b"
    assert len([e for e in section.events if e.kind == NOTE_ON and e.note == 43]) == 8


def test_songs_expand_in_place_and_tempo_overrides_apply():
    patterns = {"v": parse_pattern("@bpm 90\nkick: x..."), "c": parse_pattern("@bpm 100\nsnare: x...")}
    songs = {"song": ("v x2, c", None), "fast": ("v", 140)}
    sections = expand("song, fast x2", patterns.get, songs.get)
    assert [(s.label, s.bpm) for s in sections] == [("v", 90), ("v", 90), ("c", 100), ("v", 140), ("v", 140)]
    assert [s.bpm for s in expand("song", patterns.get, songs.get, bpm=120)] == [120, 120, 120]
    with pytest.raises(NotationError, match="no pattern named 'nope'"):
        expand("v, nope", patterns.get, songs.get)


def test_timeline_converts_to_seconds_and_routes_channels():
    p = parse_pattern("@bpm 120\n@map b = ch3\nkick: x.\nb: .x\nb notes: C3")
    events, duration = timeline([layer([("p", p)])], default_channel=10)
    assert duration == pytest.approx(0.25)
    assert [(round(t, 4), m.type, m.channel) for t, m in events] == [
        (0.0, "note_on", 9), (0.125, "note_off", 9), (0.125, "note_on", 2), (0.25, "note_off", 2)]


def test_midi_file_round_trip_keeps_tempo_changes(tmp_path):
    a = layer([("a", parse_pattern("@bpm 100\nkick: x...x...x...x..."))])
    b = layer([("b", parse_pattern("@bpm 150\nkick: x...x...x...x..."))])
    path = tmp_path / "out.mid"
    to_midi_file([a, a, b], default_channel=1).save(str(path))
    mid = mido.MidiFile(str(path))
    assert mid.length == pytest.approx(2 * 2.4 + 1.6, abs=0.01)
    assert [m.tempo for m in mid.tracks[0] if m.type == "set_tempo"] == [mido.bpm2tempo(100), mido.bpm2tempo(150)]
    assert sum(1 for m in mid.tracks[0] if m.type == "note_on") == 12
