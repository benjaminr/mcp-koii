// What kind of instrument a track or pad is, used to place it on the drum staff
// and to pick a browser synth voice. Guessed from its name, then from the
// factory layout (which the built-in kit names follow).

const NAME_ROLES = [
  // Short abbreviations only match on their own ("ch2" is a hat, "chord" isn't).
  [/^(kick|bassdrum)|^bd\d*$/, "kick"],
  [/^snare|^sd\d*$/, "snare"],
  [/^rim/, "rim"],
  [/^clap|^cp\d*$/, "clap"],
  [/^(openhat|open)|^oh\d*$/, "openhat"],
  [/^(hat|hihat|closedhat)|^(hh|ch)\d*$/, "hat"],
  [/^(ride)/, "ride"],
  [/^(crash|cymbal|splash|china)/, "crash"],
  [/^(tom)/, "tom"],
  [/^(tambo|tambourine|perc|bongo|conga|handdrum|shaker|cowbell|clave|cabasa|guiro|agogo)/, "perc"],
  [/^(bass|sub)/, "bass"],
  [/^(keys|piano|chord|lead|synth|organ|pad|strings|melody)/, "keys"],
];

const FACTORY_PAD_ROLES = {
  "A.": "kick", A0: "kick", AEnter: "clap", A1: "snare", A2: "snare", A3: "rim",
  A4: "perc", A5: "hat", A6: "openhat", A7: "perc", A8: "ride", A9: "crash",
};

export function roleForName(name) {
  const lower = (name || "").toLowerCase();
  for (const [pattern, role] of NAME_ROLES) if (pattern.test(lower)) return role;
  return null;
}

export function roleForPad(label) {
  if (!label) return "other";
  if (label in FACTORY_PAD_ROLES) return FACTORY_PAD_ROLES[label];
  return { B: "bass", C: "keys" }[label[0]] || "other";
}

/** Role of a track from the editor/server: { name, target: { kind, label } }. */
export function roleForTrack(track) {
  if (track.target?.kind === "channel") return roleForName(track.name) === "keys" ? "keys" : "bass";
  return roleForName(track.name) || roleForPad(track.target?.label);
}
