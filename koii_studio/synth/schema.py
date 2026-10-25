"""
The sound design format: what a design is, every parameter's range and unit,
and how to fill in defaults and check a design.

A design is plain JSON, so the browser, Claude (over MCP) and saved files all
share it:

    {
      "name": "dusty snare",
      "length": 0.45,                      seconds
      "stereo": false,
      "layers": [ {"engine": "analog", "level": 0.7, "pitch": 190, ...,
                   "params": {...engine...}, "amp": {...}, "pitch_env": {...},
                   "filter": {...}, "lfos": [...]} ],
      "effects": [ {"type": "eq", ...}, {"type": "reverb", ...} ],
      "instrument": {"playmode": "oneshot", "root": "auto", "loop": "off", ...},
      "normalise": -1.0
    }

The specs below are the single source of truth: validation, randomising and
morphing, and the browser's controls are all built from them.
"""

import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple, Union

DEVICE_RATE = 46875
MAX_SECONDS = 20.0
MAX_LAYERS = 6
MAX_EFFECTS = 10
MAX_LFOS = 3
FORMAT_VERSION = 1


@dataclass(frozen=True)
class Spec:
    """One parameter: a number in a range (linear or logarithmic) or one of a set of choices."""
    name: str
    label: str
    default: Any
    low: float = 0.0
    high: float = 1.0
    scale: str = "lin"               # "lin", "log" or "choice"
    unit: str = ""
    decimals: int = 2
    choices: Tuple[str, ...] = ()
    help: str = ""

    def check(self, value: Any, where: str) -> Any:
        if self.scale == "choice":
            if value not in self.choices:
                raise DesignError(f"{where}.{self.name} must be one of {', '.join(self.choices)} (got {value!r})")
            return value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DesignError(f"{where}.{self.name} must be a number (got {value!r})")
        if not self.low <= value <= self.high:
            raise DesignError(f"{where}.{self.name} must be {self.low}–{self.high}{' ' + self.unit if self.unit else ''} (got {value})")
        return float(value)

    def describe(self) -> Dict[str, Any]:
        info = {"name": self.name, "label": self.label, "default": self.default, "scale": self.scale}
        if self.scale == "choice":
            info["choices"] = list(self.choices)
        else:
            info.update(low=self.low, high=self.high, unit=self.unit, decimals=self.decimals)
        if self.help:
            info["help"] = self.help
        return info


class DesignError(ValueError):
    """A design that can't be rendered, with the exact place that's wrong."""


def S(name, label, default, low=0.0, high=1.0, scale="lin", unit="", decimals=2, help=""):
    return Spec(name, label, default, low, high, scale, unit, decimals, help=help)


def C(name, label, default, choices, help=""):
    return Spec(name, label, default, scale="choice", choices=tuple(choices), help=help)


# -- sound sources -----------------------------------------------------------------

ENGINES: Dict[str, Dict[str, Any]] = {
    "analog": {
        "label": "analog oscillator",
        "help": "Classic waveforms with unison detune and a sub oscillator: basses, leads, pads, kick bodies.",
        "params": [
            C("wave", "wave", "saw", ("sine", "triangle", "saw", "square", "pulse")),
            S("width", "pulse width", 0.5, 0.05, 0.95),
            S("voices", "unison voices", 1, 1, 7, decimals=0),
            S("detune", "detune", 12, 0, 60, unit="cents", decimals=0),
            S("sub", "sub oscillator", 0, 0, 1),
        ],
    },
    "fm": {
        "label": "FM",
        "help": "Frequency modulation: bells, electric pianos, metallic hits, growly basses.",
        "params": [
            S("ratio", "carrier ratio", 1, 0.25, 16, scale="log"),
            S("mod_ratio", "modulator ratio", 2, 0.25, 16, scale="log"),
            S("index", "modulation index", 3, 0, 20),
            S("index_decay", "index decay", 300, 1, 4000, scale="log", unit="ms", decimals=0),
            S("mod2_ratio", "second modulator ratio", 3.5, 0.25, 16, scale="log"),
            S("index2", "second index", 0, 0, 20),
        ],
    },
    "pluck": {
        "label": "plucked string",
        "help": "Karplus–Strong string model: guitars, harps, plucked basses, koto.",
        "params": [
            S("brightness", "brightness", 0.6, 0, 1),
            S("sustain", "sustain", 0.9, 0, 1),
            S("pick", "pick position", 0.3, 0.05, 0.95),
        ],
    },
    "modal": {
        "label": "struck resonator",
        "help": "A bank of decaying partials like a struck object: marimba, kalimba, glass, bells, tuned toms.",
        "params": [
            C("material", "material", "marimba", ("marimba", "kalimba", "glass", "bell", "wood", "metal", "membrane")),
            S("decay", "decay", 900, 20, 8000, scale="log", unit="ms", decimals=0),
            S("damping", "high damping", 0.5, 0, 1),
            S("hardness", "strike hardness", 0.5, 0, 1),
            S("inharmonic", "stretch partials", 0, -0.5, 0.5),
        ],
    },
    "metal": {
        "label": "metallic cluster",
        "help": "Detuned square-wave clusters like the 808: cymbals, hats, cowbells.",
        "params": [
            C("cluster", "cluster", "cymbal", ("cymbal", "cowbell")),
            S("tune", "tune", 1, 0.5, 2, scale="log"),
        ],
    },
    "additive": {
        "label": "additive harmonics",
        "help": "Sums of harmonics (drawbar style): organs, flutes, soft keys, pads.",
        "params": [
            S("h1", "harmonic 1", 1, 0, 1), S("h2", "harmonic 2", 0.5, 0, 1), S("h3", "harmonic 3", 0.33, 0, 1),
            S("h4", "harmonic 4", 0.25, 0, 1), S("h5", "harmonic 5", 0.2, 0, 1), S("h6", "harmonic 6", 0.16, 0, 1),
            S("h8", "harmonic 8", 0.1, 0, 1), S("h12", "harmonic 12", 0, 0, 1), S("h16", "harmonic 16", 0, 0, 1),
            S("decay_tilt", "upper decay", 0, 0, 1, help="how much faster the upper harmonics fade"),
        ],
    },
    "noise": {
        "label": "noise",
        "help": "Coloured noise and clap-style bursts: snares, hats, claps, breaths, risers.",
        "params": [
            C("colour", "colour", "white", ("white", "pink", "brown", "blue", "crackle")),
            S("bursts", "bursts", 1, 1, 6, decimals=0),
            S("spacing", "burst spacing", 11, 2, 60, unit="ms", decimals=0),
        ],
    },
    "sample": {
        "label": "sample",
        "help": "Plays a recorded or loaded sound, straight or as granular texture.",
        "params": [
            C("source", "source", "", ("",), help="the id of a recorded or loaded sound"),
            S("start", "start", 0, 0, 1),
            S("end", "end", 1, 0, 1),
            C("mode", "mode", "play", ("play", "granular")),
            C("reverse", "reverse", "no", ("no", "yes")),
            S("grain", "grain size", 80, 5, 500, scale="log", unit="ms", decimals=0),
            S("density", "grain density", 20, 1, 200, scale="log", unit="/s", decimals=0),
            S("spray", "position spray", 0.1, 0, 1),
            S("grain_pitch", "grain pitch spread", 0, 0, 12, unit="st", decimals=1),
        ],
    },
}

# -- per-layer shaping --------------------------------------------------------------

LAYER_SPECS = [
    S("level", "level", 0.8, 0, 1),
    S("pan", "pan", 0, -1, 1, help="left −1 … right 1 (stereo designs only)"),
    S("pitch", "pitch", 110, 20, 8000, scale="log", unit="Hz", decimals=1),
    S("delay", "start delay", 0, 0, 2000, unit="ms", decimals=0),
]
AMP_SPECS = [
    S("attack", "attack", 1, 0, 4000, scale="log", unit="ms", decimals=1),
    S("hold", "hold", 0, 0, 4000, unit="ms", decimals=0),
    S("decay", "decay", 300, 1, 10000, scale="log", unit="ms", decimals=0),
    S("sustain", "sustain", 0, 0, 1),
    S("release", "release", 50, 1, 10000, scale="log", unit="ms", decimals=0),
    S("curve", "curve", 0.5, 0, 1, help="0 linear … 1 sharply exponential"),
]
PITCH_ENV_SPECS = [
    S("amount", "pitch drop", 0, -24, 48, unit="st", decimals=1, help="start this many semitones above the pitch"),
    S("time", "drop time", 40, 1, 8000, scale="log", unit="ms", decimals=0),
]
FILTER_SPECS = [
    C("type", "type", "off", ("off", "lowpass", "highpass", "bandpass", "notch")),
    S("cutoff", "cutoff", 8000, 20, 20000, scale="log", unit="Hz", decimals=0),
    S("end", "end cutoff", 8000, 20, 20000, scale="log", unit="Hz", decimals=0),
    S("time", "sweep time", 200, 1, 8000, scale="log", unit="ms", decimals=0),
    S("resonance", "resonance", 0.7, 0.3, 20, scale="log", decimals=1),
]
LFO_SPECS = [
    C("target", "target", "pitch", ("pitch", "cutoff", "amp", "pan")),
    C("shape", "shape", "sine", ("sine", "triangle", "square", "saw", "random")),
    S("rate", "rate", 5, 0.05, 40, scale="log", unit="Hz", decimals=2),
    S("depth", "depth", 0.2, 0, 1, help="pitch: up to 1 octave; cutoff: up to 4 octaves; amp and pan: full range"),
    S("fade", "fade in", 0, 0, 4000, unit="ms", decimals=0),
]

# -- effects (applied in order to the mix) --------------------------------------------

EFFECTS: Dict[str, Dict[str, Any]] = {
    "eq": {"label": "EQ", "params": [
        S("low", "low shelf", 0, -18, 18, unit="dB", decimals=1),
        S("low_freq", "low freq", 120, 30, 500, scale="log", unit="Hz", decimals=0),
        S("mid", "mid", 0, -18, 18, unit="dB", decimals=1),
        S("mid_freq", "mid freq", 1000, 100, 10000, scale="log", unit="Hz", decimals=0),
        S("mid_q", "mid width", 1, 0.2, 8, scale="log", decimals=1),
        S("high", "high shelf", 0, -18, 18, unit="dB", decimals=1),
        S("high_freq", "high freq", 8000, 1500, 18000, scale="log", unit="Hz", decimals=0),
    ]},
    "drive": {"label": "drive", "params": [
        C("mode", "mode", "tanh", ("tanh", "fold", "clip", "tube")),
        S("amount", "amount", 0.3, 0, 1), S("mix", "mix", 1, 0, 1),
    ]},
    "lofi": {"label": "lo-fi", "params": [
        S("bits", "bit depth", 12, 3, 16, decimals=0),
        S("rate", "sample rate", 26000, 2000, 46875, scale="log", unit="Hz", decimals=0),
        S("noise", "hiss", 0, 0, 0.2, decimals=3), S("mix", "mix", 1, 0, 1),
    ]},
    "compressor": {"label": "compressor", "params": [
        S("threshold", "threshold", -18, -60, 0, unit="dB", decimals=1),
        S("ratio", "ratio", 4, 1, 20, scale="log", decimals=1),
        S("attack", "attack", 5, 0.1, 200, scale="log", unit="ms", decimals=1),
        S("release", "release", 80, 5, 2000, scale="log", unit="ms", decimals=0),
        S("makeup", "make-up", 0, 0, 24, unit="dB", decimals=1),
    ]},
    "transient": {"label": "transient shaper", "params": [
        S("attack", "attack", 0.3, -1, 1), S("sustain", "sustain", 0, -1, 1),
    ]},
    "chorus": {"label": "chorus", "params": [
        S("rate", "rate", 0.8, 0.05, 8, scale="log", unit="Hz", decimals=2),
        S("depth", "depth", 0.4, 0, 1), S("mix", "mix", 0.4, 0, 1),
    ]},
    "delay": {"label": "delay", "params": [
        S("time", "time", 180, 5, 1500, scale="log", unit="ms", decimals=0),
        S("feedback", "feedback", 0.35, 0, 0.95), S("tone", "tone", 0.5, 0, 1), S("mix", "mix", 0.25, 0, 1),
    ]},
    "reverb": {"label": "reverb", "params": [
        S("size", "size", 0.5, 0, 1), S("decay", "decay", 1.5, 0.1, 10, scale="log", unit="s", decimals=2),
        S("damping", "damping", 0.5, 0, 1), S("predelay", "pre-delay", 10, 0, 200, unit="ms", decimals=0),
        S("mix", "mix", 0.25, 0, 1),
    ]},
    "width": {"label": "stereo width", "params": [
        S("amount", "width", 1.3, 0, 2), S("haas", "haas delay", 0, 0, 30, unit="ms", decimals=1),
    ]},
}

# -- how the sound behaves on the EP-133 --------------------------------------------------

INSTRUMENT_SPECS = [
    C("playmode", "play mode", "oneshot", ("oneshot", "key", "legato"),
      help="oneshot plays the whole sample; key and legato stop on note-off and can sustain"),
    Spec("root", "root note", "auto", scale="choice", choices=("auto", "none"),
         help="'auto' detects the pitch, 'none' leaves C4, or a MIDI note number 0–127"),
    C("loop", "loop", "off", ("off", "auto"), help="'auto' finds a seamless loop for sustaining sounds"),
    S("attack", "device attack", 0, 0, 255, decimals=0),
    S("release", "device release", 255, 0, 255, decimals=0),
    S("amplitude", "device level", 100, 0, 100, decimals=0),
    C("tempo", "tempo sync", "off", ("off", "bpm"), help="'bpm' makes the device stretch the sample to the project tempo"),
    # The device's own limits (it refuses anything outside them; measured on OS 2.5).
    S("bpm", "sample tempo", 120, 60, 180, unit="BPM", decimals=1),
    S("bars", "length in bars", 1, 0.25, 4, decimals=2),
]

DESIGN_SPECS = [
    S("length", "length", 0.6, 0.02, MAX_SECONDS, scale="log", unit="s", decimals=3),
    C("stereo", "stereo", "no", ("no", "yes")),
    S("normalise", "normalise to", -1, -24, 0, unit="dBFS", decimals=1),
]


def _defaults(specs: Sequence[Spec]) -> Dict[str, Any]:
    return {spec.name: copy.deepcopy(spec.default) for spec in specs}


def default_layer(engine: str = "analog") -> Dict[str, Any]:
    if engine not in ENGINES:
        raise DesignError(f"unknown engine '{engine}'. Engines: {', '.join(ENGINES)}")
    return {"engine": engine, **_defaults(LAYER_SPECS), "params": _defaults(ENGINES[engine]["params"]),
            "amp": _defaults(AMP_SPECS), "pitch_env": _defaults(PITCH_ENV_SPECS), "filter": _defaults(FILTER_SPECS),
            "lfos": []}


def default_effect(kind: str) -> Dict[str, Any]:
    if kind not in EFFECTS:
        raise DesignError(f"unknown effect '{kind}'. Effects: {', '.join(EFFECTS)}")
    return {"type": kind, **_defaults(EFFECTS[kind]["params"])}


def default_design() -> Dict[str, Any]:
    return {"version": FORMAT_VERSION, "name": "new sound", "length": 0.6, "stereo": False, "normalise": -1.0,
            "layers": [default_layer("analog")], "effects": [], "instrument": _defaults(INSTRUMENT_SPECS)}


# -- validation -----------------------------------------------------------------------------

def _merge(values: Any, specs: Sequence[Spec], where: str, allow_extra: Sequence[str] = ()) -> Dict[str, Any]:
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise DesignError(f"{where} must be an object")
    known = {spec.name: spec for spec in specs}
    unknown = set(values) - set(known) - set(allow_extra)
    if unknown:
        raise DesignError(f"{where} has unknown setting(s) {', '.join(sorted(unknown))}. "
                          f"Known: {', '.join(known)}")
    merged = {}
    for spec in specs:
        value = values.get(spec.name, copy.deepcopy(spec.default))
        merged[spec.name] = spec.check(value, where)
    return merged


def _merge_sample_params(values: Dict[str, Any], where: str) -> Dict[str, Any]:
    # The sample source is an id string chosen at runtime, so it can't be a fixed choice.
    values = dict(values or {})
    source = values.pop("source", "")
    specs = [spec for spec in ENGINES["sample"]["params"] if spec.name != "source"]
    merged = _merge(values, specs, where)
    if not isinstance(source, str):
        raise DesignError(f"{where}.source must be a sound id")
    merged["source"] = source
    if merged["end"] <= merged["start"]:
        raise DesignError(f"{where}: end must come after start")
    return merged


def validate(design: Any) -> Dict[str, Any]:
    """A complete, checked copy of a design with every default filled in. Raises DesignError."""
    if not isinstance(design, dict):
        raise DesignError("a design must be a JSON object")
    known = {"version", "name", "length", "stereo", "normalise", "layers", "effects", "instrument", "notes"}
    unknown = set(design) - known
    if unknown:
        raise DesignError(f"the design has unknown key(s) {', '.join(sorted(unknown))}")
    out: Dict[str, Any] = {"version": FORMAT_VERSION, "name": str(design.get("name") or "new sound")[:40]}
    stereo = design.get("stereo", False)
    stereo = {"yes": True, "no": False}.get(stereo, stereo)
    if not isinstance(stereo, bool):
        raise DesignError("stereo must be true or false")
    top = _merge({"length": design.get("length", 0.6), "normalise": design.get("normalise", -1.0)},
                 [s for s in DESIGN_SPECS if s.name != "stereo"], "design")
    out.update(top, stereo=stereo)
    if "notes" in design:
        out["notes"] = str(design["notes"])[:2000]

    layers = design.get("layers")
    if not isinstance(layers, list) or not layers:
        raise DesignError("a design needs at least one layer")
    if len(layers) > MAX_LAYERS:
        raise DesignError(f"at most {MAX_LAYERS} layers")
    out["layers"] = []
    for index, layer in enumerate(layers):
        where = f"layers[{index}]"
        if not isinstance(layer, dict):
            raise DesignError(f"{where} must be an object")
        engine = layer.get("engine", "analog")
        if engine not in ENGINES:
            raise DesignError(f"{where}.engine must be one of {', '.join(ENGINES)} (got {engine!r})")
        extra = set(layer) - {"engine", "params", "amp", "pitch_env", "filter", "lfos"} - {s.name for s in LAYER_SPECS}
        if extra:
            raise DesignError(f"{where} has unknown setting(s) {', '.join(sorted(extra))}")
        checked = {"engine": engine, **_merge({k: layer[k] for k in layer if k in {s.name for s in LAYER_SPECS}},
                                              LAYER_SPECS, where)}
        params = layer.get("params")
        checked["params"] = (_merge_sample_params(params, f"{where}.params") if engine == "sample"
                             else _merge(params, ENGINES[engine]["params"], f"{where}.params"))
        checked["amp"] = _merge(layer.get("amp"), AMP_SPECS, f"{where}.amp")
        checked["pitch_env"] = _merge(layer.get("pitch_env"), PITCH_ENV_SPECS, f"{where}.pitch_env")
        checked["filter"] = _merge(layer.get("filter"), FILTER_SPECS, f"{where}.filter")
        lfos = layer.get("lfos") or []
        if not isinstance(lfos, list) or len(lfos) > MAX_LFOS:
            raise DesignError(f"{where}.lfos must be a list of at most {MAX_LFOS}")
        checked["lfos"] = [_merge(lfo, LFO_SPECS, f"{where}.lfos[{i}]") for i, lfo in enumerate(lfos)]
        out["layers"].append(checked)

    effects = design.get("effects") or []
    if not isinstance(effects, list) or len(effects) > MAX_EFFECTS:
        raise DesignError(f"effects must be a list of at most {MAX_EFFECTS}")
    out["effects"] = []
    for index, effect in enumerate(effects):
        where = f"effects[{index}]"
        if not isinstance(effect, dict) or effect.get("type") not in EFFECTS:
            raise DesignError(f"{where}.type must be one of {', '.join(EFFECTS)}")
        values = {k: v for k, v in effect.items() if k != "type"}
        out["effects"].append({"type": effect["type"], **_merge(values, EFFECTS[effect["type"]]["params"], where)})

    instrument = dict(design.get("instrument") or {})
    root = instrument.pop("root", "auto")
    if not (root in ("auto", "none") or (isinstance(root, (int, float)) and not isinstance(root, bool) and 0 <= root <= 127)):
        raise DesignError("instrument.root must be 'auto', 'none' or a MIDI note 0–127")
    merged = _merge(instrument, [s for s in INSTRUMENT_SPECS if s.name != "root"], "instrument")
    merged["root"] = int(root) if isinstance(root, (int, float)) else root
    out["instrument"] = merged
    return out


def schema() -> Dict[str, Any]:
    """Everything a client needs to build controls and explain the format."""
    return {
        "rate": DEVICE_RATE, "max_seconds": MAX_SECONDS, "max_layers": MAX_LAYERS,
        "design": [s.describe() for s in DESIGN_SPECS],
        "layer": [s.describe() for s in LAYER_SPECS],
        "amp": [s.describe() for s in AMP_SPECS],
        "pitch_env": [s.describe() for s in PITCH_ENV_SPECS],
        "filter": [s.describe() for s in FILTER_SPECS],
        "lfo": [s.describe() for s in LFO_SPECS],
        "instrument": [s.describe() for s in INSTRUMENT_SPECS],
        "engines": {name: {"label": e["label"], "help": e["help"], "params": [s.describe() for s in e["params"]]}
                    for name, e in ENGINES.items()},
        "effects": {name: {"label": e["label"], "params": [s.describe() for s in e["params"]]}
                    for name, e in EFFECTS.items()},
    }


# Choices that change what a layer or effect *is* rather than how it sounds; variation leaves them alone.
STRUCTURAL_CHOICES = {"source", "mode", "type", "target"}


def numeric_specs(design: Dict[str, Any], choices: bool = False) -> List[Tuple[Tuple[Union[str, int], ...], Spec]]:
    """
    Every numeric parameter in a design with its path, for randomising and morphing.

    With choices=True, also the engine and effect choices that are safe to vary (waveforms and
    materials), but not structural ones such as a sample layer's mode or an LFO's target.
    """
    def wanted(spec: Spec) -> bool:
        if spec.scale != "choice":
            return True
        return choices and spec.name not in STRUCTURAL_CHOICES

    found: List[Tuple[Tuple[Union[str, int], ...], Spec]] = []
    for spec in DESIGN_SPECS:
        if spec.scale != "choice":
            found.append(((spec.name,), spec))
    for i, layer in enumerate(design["layers"]):
        engine_specs = [s for s in ENGINES[layer["engine"]]["params"] if s.name != "source"]
        groups = [((), LAYER_SPECS), (("params",), engine_specs), (("amp",), AMP_SPECS),
                  (("pitch_env",), PITCH_ENV_SPECS), (("filter",), FILTER_SPECS)]
        for prefix, specs in groups:
            for spec in specs:
                if spec.scale != "choice" or (prefix == ("params",) and wanted(spec)):
                    found.append((("layers", i, *prefix, spec.name), spec))
        for j, _ in enumerate(layer["lfos"]):
            for spec in LFO_SPECS:
                if spec.scale != "choice":
                    found.append((("layers", i, "lfos", j, spec.name), spec))
    for i, effect in enumerate(design["effects"]):
        for spec in EFFECTS[effect["type"]]["params"]:
            if wanted(spec):
                found.append((("effects", i, spec.name), spec))
    return found


def get_path(design: Dict[str, Any], path: Sequence[Union[str, int]]) -> Any:
    value: Any = design
    for key in path:
        value = value[key]
    return value


def set_path(design: Dict[str, Any], path: Sequence[Union[str, int]], value: Any) -> None:
    target: Any = design
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
