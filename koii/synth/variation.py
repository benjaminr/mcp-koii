"""
Ways to explore around a design: nudge it at random, morph between two, or
breed a handful of variations to pick from.

Every move happens in each parameter's own scale (logarithmic for frequencies
and times), so "a little more" means the same thing for a cutoff and a level.
Locks keep parts of a design fixed; they are dotted paths where "*" matches
any index or key, and a path locks everything beneath it:

    "length"                 the sample length
    "layers.0"               the whole first layer
    "layers.*.amp"           every layer's amplitude envelope
    "effects.*.mix"          every effect's wet/dry mix
"""

import copy
import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from koii.synth.schema import (MAX_LAYERS, DesignError, Spec, get_path, numeric_specs, set_path,
                               validate)

Path = Tuple[Union[str, int], ...]

# Top-level settings that change the sample rather than the sound; only varied when unlocked explicitly.
ALWAYS_LOCKED = ("length", "normalise")

# Some ranges are huge (pitch spans 20 Hz–8 kHz), so a full-strength move would change the note or
# balance rather than the character. These move by a fraction of `amount`.
MOVE_WEIGHTS = {"pitch": 0.15, "level": 0.5}


# -- the normalised scale ---------------------------------------------------------------------

def _to_unit(spec: Spec, value: float) -> float:
    """Where a value sits in its range, 0–1, on the spec's own scale."""
    if spec.scale == "log" and spec.low > 0:
        return math.log(value / spec.low) / math.log(spec.high / spec.low)
    return (value - spec.low) / (spec.high - spec.low)


def _from_unit(spec: Spec, position: float) -> float:
    position = min(1.0, max(0.0, position))
    if spec.scale == "log" and spec.low > 0:
        value = spec.low * (spec.high / spec.low) ** position
    else:
        value = spec.low + position * (spec.high - spec.low)
    value = round(value, spec.decimals)
    return min(spec.high, max(spec.low, value))


# -- locks ------------------------------------------------------------------------------------

def _parse_lock(lock: str) -> Tuple[str, ...]:
    return tuple(part for part in lock.strip().split(".") if part)


def is_locked(path: Path, locks: Sequence[str]) -> bool:
    """True when a lock covers this path (the lock is the path itself or one of its parents)."""
    as_text = tuple(str(part) for part in path)
    for lock in locks:
        pattern = _parse_lock(lock)
        if len(pattern) > len(as_text):
            continue
        if all(want in ("*", have) for want, have in zip(pattern, as_text)):
            return True
    return False


def _unlocked(design: Dict[str, Any], locks: Sequence[str], choices: bool) -> List[Tuple[Path, Spec]]:
    unlocked_on_request = {lock[1:] for lock in locks if lock.startswith("!")}
    every_lock = [lock for lock in locks if not lock.startswith("!")]
    every_lock += [lock for lock in ALWAYS_LOCKED if lock not in unlocked_on_request]
    return [(path, spec) for path, spec in numeric_specs(design, choices=choices) if not is_locked(path, every_lock)]


# -- randomise ----------------------------------------------------------------------------------

def randomise(design: Dict[str, Any], amount: float = 0.3, locks: Sequence[str] = (),
              seed: Optional[int] = None, choices: bool = True) -> Dict[str, Any]:
    """
    A variation of a design. amount 0 changes nothing, 0.3 is a family resemblance,
    1 is anything goes. Each unlocked number moves by up to `amount` of its range;
    each unlocked choice (waveform, material) flips with probability amount / 3.

    Length and normalise stay put unless unlocked with "!length" / "!normalise".
    """
    if not 0 <= amount <= 1:
        raise DesignError(f"amount must be 0–1 (got {amount})")
    varied = validate(design)
    rng = random.Random(seed)
    for path, spec in _unlocked(varied, locks, choices):
        current = get_path(varied, path)
        if spec.scale == "choice":
            if rng.random() < amount / 3:
                set_path(varied, path, rng.choice([c for c in spec.choices if c != current] or [current]))
            continue
        reach = amount * MOVE_WEIGHTS.get(spec.name, 1.0)
        position = _to_unit(spec, current) + rng.uniform(-reach, reach)
        set_path(varied, path, _from_unit(spec, position))
    return validate(varied)


def evolve(design: Dict[str, Any], count: int = 6, amount: float = 0.25, locks: Sequence[str] = (),
           seed: Optional[int] = None) -> List[Dict[str, Any]]:
    """`count` different variations of a design, named "<name> 1", "<name> 2" and so on."""
    if not 1 <= count <= 16:
        raise DesignError(f"count must be 1–16 (got {count})")
    rng = random.Random(seed)
    variations = []
    for number in range(1, count + 1):
        child = randomise(design, amount, locks, seed=rng.randrange(2 ** 31))
        child["name"] = f"{design.get('name', 'sound')} {number}"[:40]
        variations.append(child)
    return variations


# -- morph --------------------------------------------------------------------------------------

def _blend_specs(a: Dict[str, Any], b: Dict[str, Any], t: float, result: Dict[str, Any],
                 prefix_a: Path, prefix_b: Path, prefix_out: Path, specs: List[Tuple[Path, Spec]]) -> None:
    """Blend every spec under prefix_a in `a` with the same place under prefix_b in `b`."""
    for path, spec in specs:
        if path[:len(prefix_a)] != prefix_a:
            continue
        rest = path[len(prefix_a):]
        value_a = get_path(a, path)
        value_b = get_path(b, prefix_b + rest)
        if spec.scale == "choice":
            blended = value_a if t < 0.5 else value_b
        else:
            blended = _from_unit(spec, (1 - t) * _to_unit(spec, value_a) + t * _to_unit(spec, value_b))
        set_path(result, prefix_out + rest, blended)


def _matching(item_a: Dict[str, Any], item_b: Dict[str, Any], key: str) -> bool:
    if item_a[key] != item_b[key]:
        return False
    if key == "engine" and item_a[key] == "sample":
        return item_a["params"]["source"] == item_b["params"]["source"] and len(item_a["lfos"]) == len(item_b["lfos"])
    if key == "engine":
        return len(item_a["lfos"]) == len(item_b["lfos"])
    return True


def morph(a: Dict[str, Any], b: Dict[str, Any], t: float) -> Dict[str, Any]:
    """
    A design part way from a (t = 0) to b (t = 1).

    Layers in the same place with the same engine blend parameter by parameter.
    Layers that don't match fade: a's fades out as t rises and b's fades in.
    Effects in the same place and of the same type blend; otherwise a's effect
    is used below t = 0.5 and b's from there on.
    """
    if not 0 <= t <= 1:
        raise DesignError(f"t must be 0–1 (got {t})")
    a, b = validate(a), validate(b)
    specs_a = numeric_specs(a, choices=True)
    result = copy.deepcopy(a)
    result["name"] = a["name"] if t < 0.5 else b["name"]
    for top in ("length", "normalise"):
        _blend_specs(a, b, t, result, (top,), (top,), (top,), specs_a)
    for key in ("stereo", "instrument"):
        result[key] = copy.deepcopy(a[key] if t < 0.5 else b[key])

    layers: List[Dict[str, Any]] = []
    fading: List[Dict[str, Any]] = []
    for i in range(max(len(a["layers"]), len(b["layers"]))):
        layer_a = a["layers"][i] if i < len(a["layers"]) else None
        layer_b = b["layers"][i] if i < len(b["layers"]) else None
        if layer_a and layer_b and _matching(layer_a, layer_b, "engine"):
            blended = copy.deepcopy(layer_a)
            holder = {"layers": [blended]}
            _blend_specs(a, b, t, holder, ("layers", i), ("layers", i), ("layers", 0), specs_a)
            if t >= 0.5:
                blended["filter"]["type"] = layer_b["filter"]["type"]
                for lfo, lfo_b in zip(blended["lfos"], layer_b["lfos"]):
                    lfo["target"], lfo["shape"] = lfo_b["target"], lfo_b["shape"]
            layers.append(blended)
            continue
        for source, weight in ((layer_a, 1 - t), (layer_b, t)):
            if source and weight > 0:
                faded = copy.deepcopy(source)
                faded["level"] = round(faded["level"] * weight, 3)
                fading.append(faded)
    # Matched layers first; faders are dropped quietest first if the total would pass the limit.
    fading.sort(key=lambda layer: layer["level"], reverse=True)
    result["layers"] = (layers + fading)[:MAX_LAYERS] or copy.deepcopy(a["layers"][:1])

    effects: List[Dict[str, Any]] = []
    for i in range(max(len(a["effects"]), len(b["effects"]))):
        effect_a = a["effects"][i] if i < len(a["effects"]) else None
        effect_b = b["effects"][i] if i < len(b["effects"]) else None
        if effect_a and effect_b and _matching(effect_a, effect_b, "type"):
            holder = {"effects": [copy.deepcopy(effect_a)]}
            _blend_specs(a, b, t, holder, ("effects", i), ("effects", i), ("effects", 0), specs_a)
            effects.append(holder["effects"][0])
        else:
            chosen = effect_a if t < 0.5 else effect_b
            if chosen:
                effects.append(copy.deepcopy(chosen))
    result["effects"] = effects
    return validate(result)
