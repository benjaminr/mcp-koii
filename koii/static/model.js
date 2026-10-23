// The editor's pattern model and its conversion to and from KOII notation text.
//
// The server is the authority on what a pattern means (it parses and validates
// it). The browser keeps a simple model it can edit, turns that model back into
// text, and asks the server to check it.

export const GRID_STEPS_PER_BEAT = { "1/4": 1, "1/8": 2, "1/16": 4, "1/32": 8, "1/8t": 3, "1/16t": 6 };
export const DEFAULT_BPM = 120;
export const DEFAULT_SWING = 50;
export const DEFAULT_GRID = "1/16";
export const BEATS_PER_BAR = 4;

const LETTER_VELOCITY = { x: 100, X: 127, o: 50 };

export function velocityOf(symbol) {
  if (symbol in LETTER_VELOCITY) return LETTER_VELOCITY[symbol];
  if (/^[1-9]$/.test(symbol)) return Math.round((Number(symbol) * 127) / 9);
  return null;
}

export const isHit = (symbol) => velocityOf(symbol) !== null;

export function stepsPerBeat(model) {
  return GRID_STEPS_PER_BEAT[model.grid] ?? 4;
}

export function stepsPerBar(model) {
  return stepsPerBeat(model) * BEATS_PER_BAR;
}

export function patternLength(model) {
  return model.tracks.reduce((longest, track) => Math.max(longest, track.symbols.length), 0);
}

export function cloneModel(model) {
  return JSON.parse(JSON.stringify(model));
}

/** A hold ('-') must follow a hit or another hold; anything else becomes a rest. */
export function normaliseHolds(symbols) {
  for (let i = 0; i < symbols.length; i++) {
    if (symbols[i] === "-" && (i === 0 || symbols[i - 1] === ".")) symbols[i] = ".";
  }
  return symbols;
}

/** Repeat a track's steps until it is `length` long (used before editing a repeated part). */
export function repeatTo(symbols, length) {
  const out = [];
  for (let i = 0; i < length; i++) out.push(symbols[i % symbols.length]);
  return out;
}

export function modelFromPattern(pattern) {
  return {
    bpm: pattern.bpm,
    swing: pattern.swing,
    grid: pattern.grid,
    maps: { ...pattern.maps },
    tracks: pattern.tracks.map((track) => ({
      name: track.name,
      symbols: [...track.symbols],
      notes: track.notes.join(" "),
      target: track.target,
    })),
  };
}

export function emptyModel() {
  return {
    bpm: 96,
    swing: 54,
    grid: DEFAULT_GRID,
    maps: {},
    tracks: [
      { name: "kick", symbols: [..."x.....x...x....."], notes: "", target: null },
      { name: "snare", symbols: [..."....x.......x..o"], notes: "", target: null },
      { name: "hat", symbols: [..."x.x.x.x.x.x.x.xX"], notes: "", target: null },
    ],
  };
}

/** Write a model as notation text: one line per bar per track, beats separated by '|'. */
export function modelToText(model) {
  const lines = [`@bpm ${model.bpm}`];
  if (model.swing !== DEFAULT_SWING) lines.push(`@swing ${model.swing}`);
  if (model.grid !== DEFAULT_GRID) lines.push(`@grid ${model.grid}`);
  for (const [name, target] of Object.entries(model.maps || {})) lines.push(`@map ${name} = ${target}`);
  lines.push("");

  const beat = stepsPerBeat(model);
  const bar = beat * BEATS_PER_BAR;
  const width = model.tracks.reduce((widest, track) => Math.max(widest, track.name.length), 0) + 1;
  for (const track of model.tracks) {
    const label = `${track.name}:`.padEnd(width + 1);
    for (let start = 0; start < track.symbols.length; start += bar) {
      const barSymbols = track.symbols.slice(start, start + bar);
      const beats = [];
      for (let i = 0; i < barSymbols.length; i += beat) beats.push(barSymbols.slice(i, i + beat).join(""));
      lines.push(label + beats.join("|"));
    }
    if (track.notes && track.notes.trim()) lines.push(`${track.name} notes: ${track.notes.trim()}`);
  }
  return lines.join("\n") + "\n";
}

/**
 * Change the pattern to `bars` bars. Growing copies the last bar of full-length
 * tracks; shorter tracks that still fit evenly keep repeating as they are.
 */
export function setBars(model, bars) {
  const length = patternLength(model);
  const bar = stepsPerBar(model);
  const newLength = Math.max(1, bars) * bar;
  for (const track of model.tracks) {
    const own = track.symbols.length;
    if (own < length && newLength % own === 0) continue;
    let symbols = own === length ? track.symbols : repeatTo(track.symbols, length);
    if (newLength > symbols.length) {
      const lastBar = symbols.slice(Math.max(0, symbols.length - bar));
      while (symbols.length < newLength) symbols = symbols.concat(lastBar);
    }
    track.symbols = normaliseHolds(symbols.slice(0, newLength));
  }
}

export function addTrack(model, name, pitched) {
  const taken = new Set(model.tracks.map((track) => track.name.toLowerCase()));
  let unique = name;
  for (let n = 2; taken.has(unique.toLowerCase()); n++) unique = `${name}${n}`;
  const length = patternLength(model) || stepsPerBar(model);
  model.tracks.push({ name: unique, symbols: Array(length).fill("."), notes: pitched ? "C1" : "", target: null });
}
