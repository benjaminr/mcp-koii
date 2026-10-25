"""
The sheet music must say exactly what playback does: same onsets, same pitches,
every bar exactly four beats, valid MusicXML (checked independently by music21).
"""

import random
from collections import defaultdict
from fractions import Fraction

import pytest
from hypothesis import given, settings, strategies as st

from koii_studio.notation import GRIDS, NotationError, parse_pattern
from koii_studio.score import build_score, score_to_dict, score_to_musicxml, spell
from koii_studio.sequence import NOTE_ON, compile_pattern

from patterns import random_pattern_text

music21 = pytest.importorskip("music21")


def rhythm(text):
    """Each bar of the first staff as 'value[dots][3][~]' strings, r for rests."""
    staff = build_score(parse_pattern(text)).staves[0]
    return [[("r" if i.is_rest else "n") + i.value + "." * i.dots + ("3" if i.tuplet else "") + ("~" if i.tie_start else "")
             for i in bar] for bar in staff.bars]


# -- spelling ---------------------------------------------------------------------

@pytest.mark.parametrize("beats, triplet, expected", [
    (Fraction(1), False, [("quarter", 0)]),
    (Fraction(3, 4), False, [("eighth", 1)]),
    (Fraction(7, 8), False, [("eighth", 2)]),
    (Fraction(5, 8), False, [("eighth", 0), ("32nd", 0)]),
    (Fraction(3), False, [("half", 1)]),
    (Fraction(1, 3), True, [("eighth", 0)]),
    (Fraction(2, 3), True, [("quarter", 0)]),
    (Fraction(1, 6), True, [("16th", 0)]),
    (Fraction(5, 6), True, [("quarter", 0), ("16th", 0)]),
])
def test_durations_are_written_as_standard_note_values(beats, triplet, expected):
    assert spell(beats, triplet) == expected


# -- known rhythms ------------------------------------------------------------------

def test_four_on_the_floor_is_four_quarter_notes():
    assert rhythm("kick: x...x...x...x...") == [["nquarter"] * 4]


def test_offbeat_sixteenths_get_leading_rests():
    # A half rest only starts on beat 1 or 3, so beat 2 gets its own quarter rest.
    assert rhythm("hat: .x..") == [["r16th", "neighth.", "rquarter", "rhalf"]]


def test_dotted_eighth_and_sixteenth():
    assert rhythm("kick: x..x") == [["neighth.", "n16th", "rquarter", "rhalf"]]


def test_empty_bars_and_half_bars_use_long_rests():
    assert rhythm("kick: x...........................|....") == [["nquarter", "rquarter", "rhalf"], ["rwhole"]]


def test_swung_triplets():
    assert rhythm("@grid 1/8t\nride: x..|x.x|x..|x.x") == [["nquarter", "nquarter3", "neighth3"] * 2]


def test_held_bass_notes_tie_across_beats_and_bars():
    text = "@map b = ch2\nb: x---|----|----|..x-\nb: ----|....|....|....\nb notes: C1 G0"
    # C1 held for three beats, two steps' rest, then G0 held across the bar line.
    assert rhythm(text) == [["nquarter~", "nquarter~", "nquarter", "reighth", "neighth~"],
                            ["nquarter", "rquarter", "rhalf"]]


def test_drum_hits_never_tie():
    items = [i for bar in build_score(parse_pattern("kick: x-------")).staves[0].bars for i in bar]
    assert not any(i.tie_start or i.tie_stop for i in items)


def test_swing_is_a_performance_detail_not_written():
    assert rhythm("@swing 66\nhat: x.x.x.x.x.x.x.x.") == rhythm("hat: x.x.x.x.x.x.x.x.")


def test_drums_and_each_pitched_track_get_their_own_staves():
    score = build_score(parse_pattern("@map b = ch2\n@map k = ch3\nkick: x...\nb: x...\nb notes: C1\nk: x...\nk notes: C5"))
    assert [(s.kind, s.clef) for s in score.staves] == [("drums", "percussion"), ("pitched", "bass"), ("pitched", "treble")]
    assert score.staves[1].octave_shift >= 1 and score.staves[2].octave_shift == 0


def test_score_serialises_for_the_browser():
    data = score_to_dict(build_score(parse_pattern("kick: x..X")))
    first = data["staves"][0]["bars"][0][0]
    assert first["value"] == "eighth" and first["dots"] == 1 and first["heads"][0]["position"] == 1


# -- properties over random patterns -------------------------------------------------------

def written_onsets(score):
    """(beat, frozenset of MIDI notes or None for drums) per staff kind, ignoring tied continuations."""
    drums, pitched = set(), defaultdict(set)
    for staff in score.staves:
        for bar in staff.bars:
            for item in bar:
                if item.is_rest or item.tie_stop:
                    continue
                if staff.kind == "drums":
                    drums.add(item.start)
                else:
                    pitched[item.start].update(h.midi for h in item.heads)
    return drums, pitched


def played_onsets(pattern):
    drums, pitched = set(), defaultdict(set)
    for event in compile_pattern(pattern):
        if event.kind != NOTE_ON:
            continue
        if event.channel is None:
            drums.add(event.beat)
        else:
            pitched[event.beat].add(event.note)
    return drums, pitched


@settings(max_examples=300, deadline=None)
@given(st.randoms(use_true_random=False))
def test_written_score_matches_what_plays(rng):
    pattern = parse_pattern(random_pattern_text(rng))
    score = build_score(pattern)
    written_drums, written_pitched = written_onsets(score)
    played_drums, played_pitched = played_onsets(pattern)
    assert written_drums == played_drums
    assert dict(written_pitched) == dict(played_pitched)

    for staff in score.staves:
        steps_per_bar = 4 * GRIDS[pattern.grid][1]
        assert len(staff.bars) == -(-pattern.length // steps_per_bar)
        for number, bar in enumerate(staff.bars):
            assert sum(i.length for i in bar) == 4, f"bar {number + 1} of {staff.name} isn't 4 beats"
            cursor = Fraction(number * 4)
            for item in bar:
                assert item.start == cursor, "items must follow each other with no gaps or overlaps"
                cursor += item.length
        flat = [i for bar in staff.bars for i in bar]
        for current, following in zip(flat, flat[1:]):
            if current.tie_start:
                assert following.tie_stop and [h.midi for h in following.heads] == [h.midi for h in current.heads]


@settings(max_examples=40, deadline=None)
@given(st.randoms(use_true_random=False))
def test_music21_reads_the_musicxml_the_same_way(rng):
    pattern = parse_pattern(random_pattern_text(rng))
    score = build_score(pattern)
    parsed = music21.converter.parse(score_to_musicxml(score), format="musicxml")
    assert len(parsed.parts) == len(score.staves)
    for part, staff in zip(parsed.parts, score.staves):
        measures = list(part.getElementsByClass("Measure"))
        assert [m.duration.quarterLength for m in measures] == [4.0] * len(staff.bars)
        theirs = sorted(
            float(m.offset + n.offset) for m in measures for n in m.notes
            if not (n.tie and n.tie.type in ("stop", "continue"))
        )
        ours = sorted(float(i.start) for bar in staff.bars for i in bar if not i.is_rest and not i.tie_stop)
        assert theirs == pytest.approx(ours)
        if staff.kind == "pitched":
            their_pitches = sorted(p.midi for m in measures for n in m.notes for p in n.pitches)
            our_pitches = sorted(h.midi for bar in staff.bars for i in bar for h in i.heads)
            assert their_pitches == our_pitches


def test_random_text_is_always_valid():
    for seed in range(200):
        try:
            parse_pattern(random_pattern_text(random.Random(seed)))
        except NotationError as error:  # pragma: no cover - a failure here is a bug in the generator
            pytest.fail(f"seed {seed}: {error}")
