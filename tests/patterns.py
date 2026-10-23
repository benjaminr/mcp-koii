"""Random valid patterns, for property tests (shared by several test files)."""

import random

from koii.notation import GRIDS

DRUM_NAMES = ["kick", "snare", "hat", "oh", "clap", "rim", "ride", "perc", "A7", "B3", "40"]
STEP_SYMBOLS = list("xxxXo159") + ["."] * 8 + ["-"] * 3
NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def random_pattern_text(rng: random.Random, pitched: bool = True, swing: bool = False) -> str:
    grid = rng.choice(list(GRIDS))
    beat = GRIDS[grid][1]
    bars = rng.choice([1, 1, 2])
    length = bars * 4 * beat
    lines = [f"@bpm {rng.randint(60, 180)}", f"@grid {grid}"]
    if swing:
        lines.append(f"@swing {rng.randint(50, 70)}")

    def steps(count):
        symbols = []
        for _ in range(count):
            symbol = rng.choice(STEP_SYMBOLS)
            if symbol == "-" and (not symbols or symbols[-1] == "."):
                symbol = "."
            symbols.append(symbol)
        return "".join(symbols)

    for name in rng.sample(DRUM_NAMES, rng.randint(1, 4)):
        own = length if rng.random() < 0.7 else length // rng.choice([d for d in (2, 4) if length % d == 0] or [1])
        lines.append(f"{name}: {steps(own)}")
    if pitched and rng.random() < 0.7:
        lines.append("@map bass = ch2")
        lines.append(f"bass: {steps(length)}")
        notes = []
        for _ in range(rng.randint(1, 5)):
            chord = [f"{rng.choice(NOTE_NAMES)}{rng.randint(0, 5)}" for _ in range(rng.choice([1, 1, 1, 2]))]
            notes.append("+".join(chord))
        lines.append(f"bass notes: {' '.join(notes)}")
    return "\n".join(lines) + "\n"
