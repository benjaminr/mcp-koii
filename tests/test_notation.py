import pytest

from koii.notation import (
    HOLD, NotationError, looks_like_pattern, note_name, parse_arrangement, parse_note, parse_pattern,
    parse_target, render_pattern, strip_comment,
)


def errors(text):
    with pytest.raises(NotationError) as exc:
        parse_pattern(text)
    return [str(i) for i in exc.value.issues]


def test_basic_pattern_maps_kit_names_to_pads():
    p = parse_pattern("kick: x...x...x...x...\nsnare: ....x.......x...")
    assert p.length == 16 and p.bpm == 120 and p.swing == 50 and p.grid == "1/16"
    kick, snare = p.tracks
    assert kick.target.note == 36 and kick.target.label == "A."
    assert kick.steps[:5] == [100, None, None, None, 100]
    assert snare.target.label == "A1"


def test_every_step_character_and_separator():
    (t,) = parse_pattern("A5: xXo1 9x-. |x--.").tracks
    assert t.steps == [100, 127, 50, 14, 127, 100, HOLD, None, 100, HOLD, HOLD, None]


def test_digit_levels_span_the_velocity_range():
    (t,) = parse_pattern("hat: 123456789").tracks
    assert t.steps == [14, 28, 42, 56, 71, 85, 99, 113, 127]


def test_unknown_step_reports_its_column():
    assert errors("kick: x.v.") == ["line 1, col 9: unknown step 'v'. Steps are x X o 1-9 (hits), . (rest), "
                                    "- (hold); spaces and | are ignored"]


def test_zero_is_rejected_rather_than_silently_treated_as_a_rest():
    assert "use '.' for a rest" in errors("kick: x0x0")[0]


def test_hold_must_follow_a_hit():
    assert "'-' (hold) must follow a hit" in errors("kick: -x..")[0]
    assert "'-' (hold) must follow a hit" in errors("kick: x.-.")[0]


def test_repeating_a_track_name_continues_the_track():
    p = parse_pattern("kick: x...\nhat: x.x.x.x.\nKICK: ..x.")
    assert [t.name for t in p.tracks] == ["kick", "hat"]
    assert p.tracks[0].steps == [100, None, None, None, None, None, 100, None]


def test_shorter_tracks_repeat_when_they_divide_the_pattern():
    assert parse_pattern("kick: x...x...x...x...\nhat: x.").length == 16


def test_length_mismatch_names_the_longest_track_and_flags_partial_beats():
    msgs = errors("kick: x...x...x...x..\nhat: x.x.")
    assert any("'hat' has 4 steps, which doesn't divide the longest track 'kick' (15 steps)" in m for m in msgs)
    assert any("'kick' is 15 steps, not a whole number of beats" in m for m in msgs)


def test_old_comment_style_gets_a_targeted_hint():
    assert errors("x...x...  # kick") == ["line 1: missing track name. Put the sound first: 'kick: x...x...'"]


def test_directives_and_their_validation():
    p = parse_pattern("@bpm 92\n@swing 58\n@grid 1/8t\nkick: x..")
    assert (p.bpm, p.swing, p.grid) == (92, 58, "1/8t")
    assert "@bpm needs" in errors("@bpm fast\nkick: x")[0]
    assert "@swing needs" in errors("@swing 90\nkick: x")[0]
    assert "@grid must be" in errors("@grid 1/5\nkick: x")[0]
    assert "unknown directive '@tempo'" in errors("@tempo 90\nkick: x")[0]


def test_map_applies_regardless_of_position():
    p = parse_pattern("thing: x...\n@map thing = B3")
    assert p.tracks[0].target.label == "B3" and p.tracks[0].target.note == 53


def test_unknown_sound_is_an_error():
    assert "unknown sound 'cowbell'" in errors("cowbell: x...")[0]


def test_custom_aliases_override_defaults():
    p = parse_pattern("kick: x...\ncowbell: x...", aliases={"kick": "D1", "cowbell": "A9"})
    assert [t.target.label for t in p.tracks] == ["D1", "A9"]


def test_pad_labels_and_midi_notes_as_track_names():
    p = parse_pattern("A.: x\nb0: x\nCEnter: x\nAFX: x\nD9: x\n60: x")
    assert [t.target.note for t in p.tracks] == [36, 49, 62, 38, 83, 60]


def test_pitched_track_with_chords():
    p = parse_pattern("@map bass = ch2\nbass: x.x-x...\nbass notes: C2 Eb2 G1+D2")
    (bass,) = p.tracks
    assert bass.target.pitched and bass.target.channel == 2
    assert bass.notes == [(36,), (39,), (31, 38)]


def test_channel_can_be_used_directly_as_a_track_name():
    (t,) = parse_pattern("ch3: x...\nch3 notes: A3").tracks
    assert t.target.channel == 3 and t.notes == [(57,)]


def test_pitched_tracks_need_notes_and_pads_cannot_have_them():
    assert "needs a 'bass notes: ...' line" in errors("@map bass = ch2\nbass: x...")[0]
    assert "has a fixed pitch" in errors("bass: x...\nbass notes: C2")[0]
    assert "has no 'lead:' rhythm line" in errors("kick: x...\nlead notes: C4")[0]


def test_bad_note_names_report_their_column():
    msg = errors("@map b = ch2\nb: x...\nb notes: C2 H2 C#9")[0]
    assert "line 3, col 13: 'H2' isn't a note" in msg


def test_all_errors_are_reported_at_once():
    assert len(errors("kick: x.v.\n@bpm 9999\nwhat: x...\n")) == 3


def test_comments_do_not_swallow_sharps():
    assert strip_comment("kick: x... # four on the floor") == "kick: x... "
    assert strip_comment("bass notes: C#2 F#2") == "bass notes: C#2 F#2"
    p = parse_pattern("# title\n@map b = ch2 # comment\nb: x.x.\nb notes: C#2 F#2  # sharp")
    assert p.tracks[0].notes == [(37,), (42,)]


def test_note_names_and_targets():
    assert parse_note("C4") == 60 and parse_note("A4") == 69 and parse_note("Bb1") == 34
    assert parse_note("C-1") == 0 and parse_note("G9") == 127 and parse_note("G#9") is None
    assert parse_note("48") == 48 and parse_note("128") is None
    assert note_name(60) == "C4" and note_name(37) == "C#2"
    assert parse_target("ch16").channel == 16 and parse_target("ch17") is None
    assert parse_target("hello") is None


def test_render_shows_header_pads_and_beat_groups():
    text = render_pattern(parse_pattern("@bpm 90\n@swing 60\nkick: x...x...x...x...\nhat: x."))
    assert "16 steps of 1/16 (1 bar) · 90 BPM · swing 60%" in text
    assert "kick  A. (36)" in text and "x...|x...|x...|x..." in text and "×8" in text


def test_arrangements():
    sections = parse_arrangement("intro x2, verse+bass x4\nchorus ×3, outro")
    assert [(s.names, s.repeat) for s in sections] == [
        (["intro"], 2), (["verse", "bass"], 4), (["chorus"], 3), (["outro"], 1)]
    with pytest.raises(NotationError):
        parse_arrangement("intro x2 x3")
    assert looks_like_pattern("kick: x...") and not looks_like_pattern("verse x4, chorus")


def test_render_shows_steps_as_written():
    text = render_pattern(parse_pattern("hat: 1.2.3.4.5.6.7.8.9...X..."))
    assert "1.2.|3.4.|5.6.|7.8.|9...|X..." in text


def test_warns_when_pitched_notes_would_also_trigger_pads():
    clean = parse_pattern("@map bass = ch2\nbass: x.x.\nbass notes: C1 G1")
    assert clean.warnings == []
    clash = parse_pattern("@map bass = ch2\nbass: x.x.x.\nbass notes: C1 C3 D3")
    assert len(clash.warnings) == 1
    assert "C3 (B.), D3 (BEnter)" in clash.warnings[0]
    assert "warning: 'bass' notes C3 (B.)" in render_pattern(clash)
