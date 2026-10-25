"""
Starting points for the sound designer, and the kit generator.

Presets are ordinary designs. Kits are twelve designs in one style, in the
order of the EP-133's group A pads (and koii studio's built-in kit names).
"""

import copy
from typing import Any, Dict, List

from koii_studio.synth.schema import default_effect, default_layer

def layer(engine: str, **settings: Any) -> Dict[str, Any]:
    """A layer with defaults, overridden by keyword settings (nested dicts merge)."""
    built = default_layer(engine)
    for key, value in settings.items():
        if isinstance(value, dict) and isinstance(built.get(key), dict):
            built[key] = {**built[key], **value}
        else:
            built[key] = value
    return built


def effect(kind: str, **settings: Any) -> Dict[str, Any]:
    return {**default_effect(kind), **settings}


def design(name: str, length: float, layers: List[Dict], effects: List[Dict] = (), stereo: bool = False,
           playmode: str = "oneshot", root: Any = "none", loop: str = "off", release: int = 255,
           category: str = "drums", notes: str = "") -> Dict[str, Any]:
    return {
        "name": name, "length": length, "stereo": stereo, "normalise": -1.0, "notes": notes,
        "layers": list(layers), "effects": list(effects),
        "instrument": {"playmode": playmode, "root": root, "loop": loop, "attack": 0, "release": release,
                       "amplitude": 100, "tempo": "off", "bpm": 120, "bars": 1},
        "_category": category,
    }


def _env(attack=1, hold=0, decay=300, sustain=0.0, release=40, curve=0.6):
    return {"attack": attack, "hold": hold, "decay": decay, "sustain": sustain, "release": release, "curve": curve}


# -- drums --------------------------------------------------------------------------------------

def kick(name="kick", pitch=48, drop=24, drop_time=45, decay=260, click=0.35, drive=0.25, style_fx=()):
    return design(name, 0.6, [
        layer("analog", pitch=pitch, params={"wave": "sine"}, pitch_env={"amount": drop, "time": drop_time},
              amp=_env(decay=decay, curve=0.5)),
        layer("noise", level=click, params={"colour": "white"}, amp=_env(decay=6, curve=0.9),
              filter={"type": "highpass", "cutoff": 3000, "end": 3000}),
    ], [effect("drive", amount=drive, mode="tanh"), *style_fx])


def snare(name="snare", tone=190, noise_level=0.85, decay=170, snap=2200, style_fx=()):
    return design(name, 0.4, [
        layer("analog", level=0.55, pitch=tone, params={"wave": "triangle"}, pitch_env={"amount": 7, "time": 30},
              amp=_env(decay=110)),
        layer("noise", level=noise_level, params={"colour": "white"}, amp=_env(decay=decay, curve=0.7),
              filter={"type": "bandpass", "cutoff": snap, "end": snap * 0.8, "resonance": 0.8}),
    ], [effect("transient", attack=0.4, sustain=0), *style_fx])


def clap(name="clap", style_fx=()):
    return design(name, 0.45, [
        layer("noise", params={"colour": "white", "bursts": 4, "spacing": 10}, amp=_env(decay=160, curve=0.7),
              filter={"type": "bandpass", "cutoff": 1300, "end": 1100, "resonance": 1.4}),
    ], [effect("reverb", size=0.2, decay=0.35, mix=0.18), *style_fx])


def hat(name="hat", decay=45, metallic=True, style_fx=()):
    layers = [layer("noise", level=0.6, params={"colour": "white"}, amp=_env(decay=decay, curve=0.8),
                    filter={"type": "highpass", "cutoff": 7500, "end": 7500, "resonance": 0.8})]
    if metallic:
        layers.append(layer("metal", level=0.7, params={"cluster": "cymbal"}, amp=_env(decay=decay, curve=0.8)))
    return design(name, max(0.12, decay / 1000 * 3), layers, list(style_fx))


def cymbal(name="cymbal", decay=1400, style_fx=()):
    return design(name, 2.0, [
        layer("metal", params={"cluster": "cymbal", "tune": 1.05}, amp=_env(decay=decay, curve=0.6)),
        layer("noise", level=0.35, params={"colour": "white"}, amp=_env(decay=decay * 0.8, curve=0.6),
              filter={"type": "highpass", "cutoff": 5000, "end": 5000}),
    ], list(style_fx))


def tom(name="tom", pitch=110, style_fx=()):
    return design(name, 0.6, [
        layer("modal", pitch=pitch, params={"material": "membrane", "decay": 420, "hardness": 0.5},
              pitch_env={"amount": 5, "time": 80}, amp=_env(decay=450)),
    ], list(style_fx))


def rim(name="rim", style_fx=()):
    return design(name, 0.12, [
        layer("modal", pitch=1700, params={"material": "wood", "decay": 60, "hardness": 0.9}, amp=_env(decay=40)),
        layer("noise", level=0.3, amp=_env(decay=8), filter={"type": "bandpass", "cutoff": 3500, "end": 3500}),
    ], list(style_fx))


def cowbell(name="cowbell", style_fx=()):
    return design(name, 0.5, [
        layer("metal", params={"cluster": "cowbell"}, amp=_env(decay=260, curve=0.7)),
    ], [effect("eq", mid=4, mid_freq=900), *style_fx])


def conga(name="conga", pitch=220, style_fx=()):
    return design(name, 0.45, [
        layer("modal", pitch=pitch, params={"material": "membrane", "decay": 260, "hardness": 0.7},
              pitch_env={"amount": 3, "time": 25}, amp=_env(decay=280)),
    ], list(style_fx))


def shaker(name="shaker", style_fx=()):
    return design(name, 0.18, [
        layer("noise", params={"colour": "white"}, amp=_env(attack=15, decay=60, curve=0.6),
              filter={"type": "bandpass", "cutoff": 6000, "end": 7000, "resonance": 0.9}),
    ], list(style_fx))


# -- instruments ----------------------------------------------------------------------------------

def _instrument(name, length, layers, effects=(), playmode="key", loop="auto", release=180, notes=""):
    return design(name, length, layers, list(effects), playmode=playmode, root="auto", loop=loop, release=release,
                  category="instruments", notes=notes)


INSTRUMENTS = {
    "sub bass": lambda: _instrument("sub bass", 1.5, [
        layer("analog", pitch=55, params={"wave": "sine", "sub": 0.2}, amp=_env(attack=3, decay=600, sustain=0.8))]),
    "acid bass": lambda: _instrument("acid bass", 1.0, [
        layer("analog", pitch=55, params={"wave": "saw"}, amp=_env(attack=2, decay=500, sustain=0.5),
              filter={"type": "lowpass", "cutoff": 2400, "end": 220, "time": 260, "resonance": 9})],
        [effect("drive", amount=0.35, mode="tube")]),
    "fm bass": lambda: _instrument("fm bass", 1.0, [
        layer("fm", pitch=55, params={"ratio": 1, "mod_ratio": 1, "index": 6, "index_decay": 220},
              amp=_env(attack=2, decay=500, sustain=0.6))]),
    "reese": lambda: _instrument("reese", 2.0, [
        layer("analog", pitch=55, params={"wave": "saw", "voices": 2, "detune": 22}, amp=_env(attack=5, decay=900, sustain=0.85),
              filter={"type": "lowpass", "cutoff": 900, "end": 900, "resonance": 1.2})],
        [effect("chorus", depth=0.3, mix=0.25)]),
    "pluck": lambda: _instrument("pluck", 1.0, [
        layer("pluck", pitch=220, params={"brightness": 0.7, "sustain": 0.92})], playmode="oneshot", loop="off"),
    "marimba": lambda: _instrument("marimba", 1.2, [
        layer("modal", pitch=440, params={"material": "marimba", "decay": 900, "hardness": 0.55})],
        playmode="oneshot", loop="off"),
    "kalimba": lambda: _instrument("kalimba", 1.4, [
        layer("modal", pitch=523.25, params={"material": "kalimba", "decay": 1200, "hardness": 0.6})],
        [effect("reverb", decay=1.2, mix=0.2)], playmode="oneshot", loop="off"),
    "bell": lambda: _instrument("bell", 3.0, [
        layer("fm", pitch=523.25, params={"ratio": 1, "mod_ratio": 3.5, "index": 4, "index_decay": 1500},
              amp=_env(decay=2800, curve=0.6))], [effect("reverb", decay=2.2, mix=0.25)], playmode="oneshot", loop="off"),
    "glass": lambda: _instrument("glass", 2.5, [
        layer("modal", pitch=880, params={"material": "glass", "decay": 2400, "hardness": 0.4})],
        [effect("reverb", decay=2.5, mix=0.3)], playmode="oneshot", loop="off"),
    "electric piano": lambda: _instrument("electric piano", 2.0, [
        layer("fm", pitch=261.63, params={"ratio": 1, "mod_ratio": 1, "index": 2.2, "index_decay": 600},
              amp=_env(attack=2, decay=1500, sustain=0.3)),
        layer("fm", level=0.25, pitch=261.63, params={"ratio": 14, "mod_ratio": 1, "index": 1, "index_decay": 60},
              amp=_env(decay=80))], [effect("chorus", depth=0.25, mix=0.3)]),
    "organ": lambda: _instrument("organ", 1.5, [
        layer("additive", pitch=261.63, params={"h1": 1, "h2": 0.8, "h3": 0.6, "h4": 0.5, "h5": 0, "h6": 0.3,
                                               "h8": 0.4, "h12": 0, "h16": 0}, amp=_env(attack=8, decay=200, sustain=1))],
        [effect("chorus", rate=6, depth=0.15, mix=0.35)], release=120),
    "pad": lambda: _pad(),
    "lead": lambda: _instrument("lead", 1.5, [
        layer("analog", pitch=440, params={"wave": "saw", "voices": 3, "detune": 10},
              amp=_env(attack=5, decay=700, sustain=0.7), lfos=[{"target": "pitch", "shape": "sine", "rate": 5.5,
                                                                "depth": 0.015, "fade": 300}],
              filter={"type": "lowpass", "cutoff": 5000, "end": 3000, "time": 400})],
        [effect("delay", time=230, feedback=0.3, mix=0.15)]),
    "string": lambda: _instrument("string", 3.0, [
        layer("analog", pitch=220, params={"wave": "saw", "voices": 4, "detune": 9},
              amp=_env(attack=250, decay=1500, sustain=0.85, release=600),
              lfos=[{"target": "pitch", "shape": "sine", "rate": 5, "depth": 0.01, "fade": 600}],
              filter={"type": "lowpass", "cutoff": 3200, "end": 3200, "resonance": 0.8})],
        [effect("reverb", decay=2.2, mix=0.25)]),
    "choir": lambda: _instrument("choir", 3.0, [
        layer("additive", pitch=261.63, params={"h1": 1, "h2": 0.3, "h3": 0.6, "h4": 0.1, "h5": 0.4, "h6": 0,
                                               "h8": 0, "h12": 0, "h16": 0}, amp=_env(attack=300, decay=2000, sustain=0.8)),
        layer("noise", level=0.08, params={"colour": "pink"}, amp=_env(attack=300, decay=2000, sustain=0.8),
              filter={"type": "bandpass", "cutoff": 1200, "end": 1200, "resonance": 2})],
        [effect("chorus", depth=0.6, mix=0.6), effect("reverb", decay=3, mix=0.35)]),
}


def _pad():
    return _instrument("pad", 4.0, [
        layer("analog", pitch=261.63, params={"wave": "saw", "voices": 5, "detune": 18},
              amp=_env(attack=600, decay=2000, sustain=0.8, release=800),
              filter={"type": "lowpass", "cutoff": 1800, "end": 1800, "resonance": 0.9})],
        [effect("chorus", depth=0.5, mix=0.5), effect("reverb", decay=3.5, size=0.8, mix=0.35)])


FX = {
    "zap": lambda: design("zap", 0.35, [
        layer("analog", pitch=60, params={"wave": "sine"}, pitch_env={"amount": 40, "time": 160}, amp=_env(decay=200))],
        category="fx"),
    "riser": lambda: design("riser", 3.0, [
        layer("noise", params={"colour": "white"}, amp=_env(attack=2800, decay=200, sustain=1, release=20, curve=0.3),
              filter={"type": "bandpass", "cutoff": 300, "end": 9000, "time": 2900, "resonance": 3}),
        layer("analog", level=0.4, pitch=110, params={"wave": "saw", "voices": 3}, pitch_env={"amount": -24, "time": 2900},
              amp=_env(attack=2800, decay=200, sustain=1, release=20, curve=0.3))],
        [effect("reverb", decay=2, mix=0.3)], category="fx"),
    "impact": lambda: design("impact", 2.5, [
        layer("analog", pitch=40, params={"wave": "sine"}, pitch_env={"amount": 24, "time": 120}, amp=_env(decay=1200)),
        layer("noise", level=0.6, params={"colour": "brown"}, amp=_env(decay=900))],
        [effect("drive", amount=0.4), effect("reverb", decay=3, size=0.9, mix=0.35)], category="fx"),
    "vinyl crackle": lambda: design("vinyl crackle", 2.0, [
        layer("noise", params={"colour": "crackle"}, amp=_env(attack=10, decay=2000, sustain=1)),
        layer("noise", level=0.06, params={"colour": "pink"}, amp=_env(attack=10, decay=2000, sustain=1))],
        [effect("eq", low=-8, high=-4)], category="fx"),
}

DRUMS = {
    "kick": lambda: kick(),
    "808 kick": lambda: kick("808 kick", pitch=42, drop=12, drop_time=60, decay=1100, click=0.1, drive=0.15),
    "909 kick": lambda: kick("909 kick", pitch=52, drop=30, drop_time=35, decay=330, click=0.6, drive=0.35),
    "snare": lambda: snare(),
    "909 snare": lambda: snare("909 snare", tone=200, noise_level=1, decay=220, snap=3500),
    "clap": lambda: clap(),
    "rim": lambda: rim(),
    "hat": lambda: hat(),
    "open hat": lambda: hat("open hat", decay=320),
    "cymbal": lambda: cymbal(),
    "cowbell": lambda: cowbell(),
    "tom": lambda: tom(),
    "conga": lambda: conga(),
    "shaker": lambda: shaker(),
}

PRESETS = {**DRUMS, **INSTRUMENTS, **FX}


def preset(name: str) -> Dict[str, Any]:
    if name not in PRESETS:
        raise KeyError(f"no preset '{name}'. Presets: {', '.join(PRESETS)}")
    built = copy.deepcopy(PRESETS[name]())
    built.pop("_category", None)
    return built


def catalogue() -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {"drums": list(DRUMS), "instruments": list(INSTRUMENTS), "fx": list(FX)}
    return groups


# -- kits ----------------------------------------------------------------------------------------

KIT_PADS = ["A.", "A0", "AEnter", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"]
KIT_ROLES = ["kick", "kick2", "clap", "snare", "snare2", "rim", "perc", "hat", "openhat", "perc2", "ride", "crash"]


def _style_fx(style: str) -> List[Dict]:
    if style == "lofi":
        return [effect("lofi", bits=10, rate=18000, noise=0.02, mix=1), effect("eq", high=-5, low=2)]
    if style == "industrial":
        return [effect("drive", mode="fold", amount=0.45), effect("reverb", decay=0.9, size=0.6, mix=0.2)]
    if style == "glitch":
        return [effect("lofi", bits=6, rate=9000, mix=0.6)]
    return []


def kit(style: str) -> List[Dict[str, Any]]:
    """Twelve designs in one style, in group A pad order: [{pad, role, design}]."""
    fx = _style_fx(style)
    if style == "808":
        sounds = [kick("808 kick", 42, 12, 60, 1100, 0.1, 0.15), kick("808 kick short", 46, 12, 50, 420, 0.15, 0.2),
                  clap("808 clap"), snare("808 snare", 180, 0.7, 150, 1800), snare("808 snare b", 220, 0.6, 120, 2400),
                  rim("808 rim"), conga("808 conga", 260), hat("808 hat", 40), hat("808 open hat", 300),
                  cowbell("808 cowbell"), cymbal("808 ride", 900), cymbal("808 crash", 1800)]
    elif style == "909":
        sounds = [kick("909 kick", 52, 30, 35, 330, 0.6, 0.35), kick("909 kick b", 55, 26, 30, 260, 0.7, 0.45),
                  clap("909 clap"), snare("909 snare", 200, 1, 220, 3500), snare("909 snare b", 230, 1, 160, 4200),
                  rim("909 rim"), tom("909 tom", 140), hat("909 hat", 35), hat("909 open hat", 380),
                  tom("909 tom lo", 95), cymbal("909 ride", 1200), cymbal("909 crash", 2000)]
    elif style in ("lofi", "industrial", "glitch", "acoustic"):
        soft = style in ("lofi", "acoustic")
        sounds = [kick(f"{style} kick", 50, 18 if soft else 30, 45, 300, 0.25, 0.2 if soft else 0.5, fx),
                  kick(f"{style} kick b", 56, 14, 40, 220, 0.2, 0.2, fx),
                  clap(f"{style} clap", fx), snare(f"{style} snare", 185, 0.8, 180, 2000, fx),
                  snare(f"{style} snare b", 210, 0.7, 120, 2800, fx), rim(f"{style} rim", fx),
                  conga(f"{style} perc", 240, fx), hat(f"{style} hat", 40, not soft, fx),
                  hat(f"{style} open hat", 280, not soft, fx), shaker(f"{style} shaker", fx),
                  cymbal(f"{style} ride", 900, fx), cymbal(f"{style} crash", 1600, fx)]
    else:
        raise KeyError(f"no kit style '{style}'. Styles: {', '.join(KIT_STYLES)}")
    kit_designs = []
    for pad, role, sound in zip(KIT_PADS, KIT_ROLES, sounds):
        built = copy.deepcopy(sound)
        built.pop("_category", None)
        kit_designs.append({"pad": pad, "role": role, "design": built})
    return kit_designs


KIT_STYLES = ("808", "909", "lofi", "acoustic", "industrial", "glitch")
