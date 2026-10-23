"""
Robustness: the parser never fails in an unexpected way, compiled timing is
well-formed, and the browser editor round-trips patterns without changing them.
"""

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from koii.notation import NotationError, parse_arrangement, parse_pattern, pattern_to_dict
from koii.sequence import NOTE_OFF, NOTE_ON, compile_pattern

from patterns import random_pattern_text

ROUNDTRIP = Path(__file__).parent / "roundtrip.mjs"
PATTERN_ALPHABET = st.sampled_from(list("xXo123456789.-| :#@\nabkicnhtsd0ACBDE") + ["kick", "snare", "hat", "@bpm ", "@map ", " = ", "ch2", "notes", "C1", "Eb2", "+"])


@settings(max_examples=500, deadline=None)
@given(st.lists(PATTERN_ALPHABET, max_size=60).map("".join))
def test_parser_only_ever_raises_notation_errors(text):
    try:
        parse_pattern(text)
    except NotationError as error:
        assert error.issues and all(issue.message for issue in error.issues)


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=80))
def test_arbitrary_unicode_is_handled(text):
    for parse in (parse_pattern, parse_arrangement):
        try:
            parse(text)
        except NotationError:
            pass


@settings(max_examples=300, deadline=None)
@given(st.randoms(use_true_random=False))
def test_compiled_events_are_well_formed(rng):
    pattern = parse_pattern(random_pattern_text(rng, swing=True))
    events = compile_pattern(pattern)
    assert events == sorted(events, key=lambda e: (e.beat, e.kind, e.note))
    sounding = {}
    for event in events:
        key = (event.channel, event.note)
        assert 0 <= event.beat <= pattern.length_beats
        if event.kind == NOTE_ON:
            assert 1 <= event.velocity <= 127
            sounding[key] = sounding.get(key, 0) + 1
        else:
            assert sounding.get(key, 0) > 0, "a note-off without a matching note-on"
            sounding[key] -= 1
    assert not any(sounding.values()), "every note is released by the end of the pattern"


def compiled(pattern):
    return [(e.beat, e.kind, e.note, e.velocity, e.channel) for e in compile_pattern(pattern)]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to run the browser code")
def test_browser_editor_round_trips_patterns_exactly():
    texts = [random_pattern_text(random.Random(seed), swing=seed % 2 == 0) for seed in range(250)]
    originals = [parse_pattern(text) for text in texts]
    result = subprocess.run(["node", str(ROUNDTRIP)], input=json.dumps([pattern_to_dict(p) for p in originals]),
                            capture_output=True, text=True, check=True, timeout=60)
    for seed, (original, text) in enumerate(zip(originals, json.loads(result.stdout))):
        again = parse_pattern(text)
        assert (again.bpm, again.swing, again.grid, again.length) == \
               (original.bpm, original.swing, original.grid, original.length), f"seed {seed}"
        assert compiled(again) == compiled(original), f"seed {seed}: the editor changed what plays\n{text}"
