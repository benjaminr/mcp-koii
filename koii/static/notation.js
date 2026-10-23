// Sheet music for a pattern: a drum staff (one line or space per instrument)
// and, when there are pitched tracks, a bass or treble staff. Notes are beamed
// per beat with durations taken from the gap to the next hit; rests are left
// out to keep it readable.

import { isHit, velocityOf } from "./model.js";
import { roleForTrack } from "./roles.js";

const SVG = "http://www.w3.org/2000/svg";
const HALF = 5;               // half a staff space: one line/space step
const STAFF_HEIGHT = 8 * HALF;
const WIDTH = 920;
const LEFT = 70;
const RIGHT = 14;
const STEM = 30;
const BLOCK_TOP = 64;         // room above a staff for stems, beams and marks
const DRUM_BLOCK = BLOCK_TOP + STAFF_HEIGHT + 34;
const PITCH_BLOCK = BLOCK_TOP + STAFF_HEIGHT + 56;

// Staff position 0 is the bottom line; each step is half a space up.
const DRUM_VOICES = {
  kick: { pos: 1, name: "Kick" },
  tom: { pos: 6, name: "Tom" },
  perc: { pos: 3, name: "Perc" },
  snare: { pos: 5, name: "Snare" },
  rim: { pos: 5, head: "x", name: "Rim" },
  clap: { pos: 7, name: "Clap" },
  hat: { pos: 9, head: "x", name: "Hi-hat" },
  openhat: { pos: 9, head: "x", open: true, name: "Open hat" },
  ride: { pos: 8, head: "x", name: "Ride" },
  crash: { pos: 10, head: "x", name: "Crash" },
  bass: { pos: 2, name: "Bass pad" },
  keys: { pos: 4, name: "Keys pad" },
  other: { pos: 4, name: "Other" },
};
const LETTERS = { C: 0, D: 1, E: 2, F: 3, G: 4, A: 5, B: 6 };
const CLEFS = {
  bass: { glyph: "𝄢", bottomStep: 2 * 7 + LETTERS.G, size: 34, dy: 2 },   // bottom line G2
  treble: { glyph: "𝄞", bottomStep: 4 * 7 + LETTERS.E, size: 48, dy: 10 }, // bottom line E4
};
const OCTAVE_MARKS = ["", "8vb", "15mb", "22mb"];

function svg(tag, attributes = {}, text) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function parseNoteName(name) {
  const match = /^([A-Ga-g])([#b]?)(-?\d+)$/.exec(name);
  if (!match) return null;
  const letter = match[1].toUpperCase();
  // `degree` counts letter names (C0 = 0, D0 = 1, ...), which is what staff position follows.
  return { degree: Number(match[3]) * 7 + LETTERS[letter], accidental: match[2] };
}

/** How a note of `steps` grid steps is written: number of beams/flags and whether it's dotted. */
function noteValue(steps, stepBeats, triplet) {
  const beats = steps * stepBeats + 1e-9;
  if (triplet) return { beams: beats >= 1 ? 0 : beats > 1 / 6 + 1e-6 ? 1 : 2, dotted: false };
  for (const [limit, beams, dotted] of [[1, 0, false], [0.75, 1, true], [0.5, 1, false], [0.375, 2, true],
                                         [0.25, 2, false], [0.1875, 3, true], [0.125, 3, false]]) {
    if (beats >= limit) return { beams, dotted };
  }
  return { beams: 4, dotted: false };
}

export class Notation {
  constructor(container, legend) {
    this.container = container;
    this.legend = legend;
    this.playheads = [];
    this.layout = null;
  }

  render(pattern) {
    this.container.replaceChildren();
    this.legend.replaceChildren();
    this.playheads = [];
    if (!pattern || !pattern.tracks.length) return;

    const stepsPerBar = pattern.steps_per_beat * 4;
    const bars = Math.ceil(pattern.length / stepsPerBar);
    const barsPerSystem = stepsPerBar > 16 ? 1 : 2;
    const systems = Math.ceil(bars / barsPerSystem);
    const barWidth = (WIDTH - LEFT - RIGHT) / barsPerSystem;
    const triplet = pattern.steps_per_beat % 3 === 0;

    const drumTracks = pattern.tracks.filter((t) => t.target.kind !== "channel");
    const pitchedTracks = pattern.tracks.filter((t) => t.target.kind === "channel");
    const systemHeight = (drumTracks.length ? DRUM_BLOCK : 0) + (pitchedTracks.length ? PITCH_BLOCK : 0);
    const height = systems * systemHeight + 10;
    const root = svg("svg", { viewBox: `0 0 ${WIDTH} ${height}`, class: "score", role: "img",
                               "aria-label": "Pattern as sheet music" });

    this.layout = { stepsPerBar, barsPerSystem, barWidth, systems };
    const xOf = (step) => {
      const bar = Math.floor(step / stepsPerBar);
      const barX = LEFT + (bar % barsPerSystem) * barWidth;
      return barX + 14 + ((step % stepsPerBar) + 0.35) * ((barWidth - 22) / stepsPerBar);
    };
    this.xOf = xOf;

    const drumOnsets = this._drumOnsets(pattern, drumTracks);
    const pitched = this._pitchedOnsets(pattern, pitchedTracks);

    for (let system = 0; system < systems; system++) {
      const firstBar = system * barsPerSystem;
      const lastBar = Math.min(bars, firstBar + barsPerSystem) - 1;
      const firstStep = firstBar * stepsPerBar;
      const lastStep = Math.min(pattern.length, (lastBar + 1) * stepsPerBar) - 1;
      let y = system * systemHeight;
      const group = svg("g");
      root.append(group);

      const staffTops = [];
      if (drumTracks.length) {
        const top = y + BLOCK_TOP;
        this._staff(group, top, firstBar, lastBar, barWidth, system === 0, "drums", pattern, bars);
        this._voice(group, drumOnsets, top, firstStep, lastStep, pattern, triplet, xOf);
        staffTops.push(top);
        y += DRUM_BLOCK;
      }
      if (pitchedTracks.length) {
        const top = y + BLOCK_TOP;
        this._staff(group, top, firstBar, lastBar, barWidth, system === 0, pitched.clef, pattern, bars, pitched.octaves);
        this._voice(group, pitched.onsets, top, firstStep, lastStep, pattern, triplet, xOf);
        staffTops.push(top);
      }
      const playhead = svg("line", { class: "score-playhead", x1: 0, x2: 0,
                                     y1: staffTops[0] - BLOCK_TOP + 14, y2: staffTops[staffTops.length - 1] + STAFF_HEIGHT + 12,
                                     visibility: "hidden" });
      group.append(playhead);
      this.playheads.push({ line: playhead, firstStep, lastStep });
    }
    this.container.append(root);
    this._renderLegend(drumTracks, pitchedTracks, pitched);
  }

  _drumOnsets(pattern, tracks) {
    const onsets = new Map();
    for (const track of tracks) {
      const voice = DRUM_VOICES[roleForTrack(track)] || DRUM_VOICES.other;
      const own = track.symbols.length;
      for (let step = 0; step < pattern.length; step++) {
        const symbol = track.symbols[step % own];
        if (!isHit(symbol)) continue;
        const list = onsets.get(step) || [];
        list.push({ pos: voice.pos, head: voice.head || "normal", open: voice.open, velocity: velocityOf(symbol) });
        onsets.set(step, list);
      }
    }
    return onsets;
  }

  _pitchedOnsets(pattern, tracks) {
    const raw = [];
    for (const track of tracks) {
      const own = track.symbols.length;
      let noteIndex = 0;
      for (let step = 0; step < pattern.length; step++) {
        const symbol = track.symbols[step % own];
        if (!isHit(symbol) || !track.notes.length) continue;
        const chord = track.notes[noteIndex % track.notes.length].split("+");
        noteIndex++;
        for (const name of chord) {
          const parsed = parseNoteName(name);
          if (parsed) raw.push({ step, ...parsed, velocity: velocityOf(symbol) });
        }
      }
    }
    const degrees = raw.map((note) => note.degree).sort((a, b) => a - b);
    const median = degrees.length ? degrees[Math.floor(degrees.length / 2)] : 0;
    const clef = median >= CLEFS.treble.bottomStep - 2 ? "treble" : "bass";
    let octaves = 0;
    // Shift low lines up by octaves (marked 8vb/15mb) until the middle note sits on the staff.
    while (median + octaves * 7 - CLEFS[clef].bottomStep < 2 && octaves < 3) octaves++;
    const onsets = new Map();
    for (const note of raw) {
      const list = onsets.get(note.step) || [];
      list.push({ pos: note.degree + octaves * 7 - CLEFS[clef].bottomStep, head: "normal",
                  accidental: note.accidental, velocity: note.velocity });
      onsets.set(note.step, list);
    }
    return { onsets, clef, octaves };
  }

  _staff(group, top, firstBar, lastBar, barWidth, first, clef, pattern, bars, octaves = 0) {
    const left = 8;
    const right = WIDTH - RIGHT;
    for (let line = 0; line < 5; line++) {
      const y = top + line * 2 * HALF;
      group.append(svg("line", { class: "staff-line", x1: left, x2: right, y1: y, y2: y }));
    }
    if (clef === "drums") {
      group.append(svg("rect", { class: "clef", x: 18, y: top + 2 * HALF, width: 3.2, height: 4 * HALF }));
      group.append(svg("rect", { class: "clef", x: 25, y: top + 2 * HALF, width: 3.2, height: 4 * HALF }));
    } else {
      const spec = CLEFS[clef];
      group.append(svg("text", { class: "clef-glyph", x: 14, y: top + STAFF_HEIGHT - spec.dy + (clef === "bass" ? -6 : 0),
                                 "font-size": spec.size }, spec.glyph));
      if (octaves) group.append(svg("text", { class: "octave-mark", x: 16, y: top + STAFF_HEIGHT + 18 }, OCTAVE_MARKS[octaves]));
    }
    if (first) {
      group.append(svg("text", { class: "time-sig", x: 46, y: top + 2 * HALF * 2 - 1 }, "4"));
      group.append(svg("text", { class: "time-sig", x: 46, y: top + STAFF_HEIGHT - 1 }, "4"));
    }
    for (let bar = firstBar; bar <= lastBar + 1; bar++) {
      const x = bar === lastBar + 1 ? right : LEFT + (bar - firstBar) * barWidth;
      if (bar <= lastBar && bar !== firstBar) {
        group.append(svg("line", { class: "bar-line", x1: x, x2: x, y1: top, y2: top + STAFF_HEIGHT }));
      }
      if (bar <= lastBar && clef !== "bass" && clef !== "treble") {
        group.append(svg("text", { class: "bar-number", x: x + 4, y: top - BLOCK_TOP + 12 }, String(bar + 1)));
      }
    }
    const end = svg("line", { class: lastBar === bars - 1 ? "bar-line final" : "bar-line",
                              x1: right, x2: right, y1: top, y2: top + STAFF_HEIGHT });
    group.append(end);
    if (lastBar === bars - 1) {
      group.append(svg("line", { class: "bar-line", x1: right - 5, x2: right - 5, y1: top, y2: top + STAFF_HEIGHT }));
    }
  }

  _voice(group, onsets, top, firstStep, lastStep, pattern, triplet, xOf) {
    const beat = pattern.steps_per_beat;
    const yOf = (pos) => top + STAFF_HEIGHT - pos * HALF;
    for (let beatStart = firstStep - (firstStep % beat); beatStart <= lastStep; beatStart += beat) {
      const beatEnd = beatStart + beat;
      const steps = [...onsets.keys()].filter((s) => s >= beatStart && s < beatEnd).sort((a, b) => a - b);
      if (!steps.length) continue;
      const notes = steps.map((step, i) => {
        const heads = onsets.get(step);
        const duration = (i + 1 < steps.length ? steps[i + 1] : beatEnd) - step;
        const value = noteValue(duration, pattern.step_beats, triplet);
        const ys = heads.map((h) => yOf(h.pos));
        return { step, heads, value, x: xOf(step), low: Math.max(...ys), high: Math.min(...ys) };
      });
      const beamed = notes.length > 1 && notes.some((n) => n.value.beams > 0);
      const tip = Math.min(...notes.map((n) => n.high)) - STEM;

      for (const note of notes) {
        this._heads(group, note, yOf);
        const stemX = note.x + 5;
        const stemTop = beamed ? tip : note.high - STEM;
        group.append(svg("line", { class: "stem", x1: stemX, x2: stemX, y1: note.low - 1, y2: stemTop }));
        if (!beamed) {
          for (let f = 0; f < note.value.beams; f++) {
            group.append(svg("path", { class: "flag", d: `M${stemX} ${stemTop + f * 7} q 9 5 7 15` }));
          }
        }
        const markY = (beamed ? tip : stemTop) - 8;
        if (note.heads.some((h) => h.velocity >= 120)) {
          group.append(svg("text", { class: "accent", x: note.x - 1, y: markY }, ">"));
        }
        if (note.heads.some((h) => h.open)) {
          group.append(svg("circle", { class: "open-mark", cx: note.x + 1, cy: markY - 12, r: 3.4 }));
        }
      }
      if (beamed) this._beams(group, notes, tip, triplet);
    }
  }

  _heads(group, note, yOf) {
    for (const head of note.heads) {
      const y = yOf(head.pos);
      for (let ledger = 10; ledger <= head.pos; ledger += 2) {
        const ly = yOf(ledger);
        group.append(svg("line", { class: "ledger", x1: note.x - 8, x2: note.x + 8, y1: ly, y2: ly }));
      }
      for (let ledger = -2; ledger >= head.pos; ledger -= 2) {
        const ly = yOf(ledger);
        group.append(svg("line", { class: "ledger", x1: note.x - 8, x2: note.x + 8, y1: ly, y2: ly }));
      }
      const ghost = head.velocity <= 50;
      if (head.head === "x") {
        group.append(svg("path", { class: "head-x", d: `M${note.x - 4} ${y - 4} L${note.x + 4} ${y + 4} M${note.x - 4} ${y + 4} L${note.x + 4} ${y - 4}` }));
      } else {
        group.append(svg("ellipse", { class: "head", cx: note.x, cy: y, rx: 5.4, ry: 3.9,
                                      transform: `rotate(-22 ${note.x} ${y})` }));
      }
      if (ghost) {
        group.append(svg("text", { class: "ghost-mark", x: note.x - 12, y: y + 4 }, "("));
        group.append(svg("text", { class: "ghost-mark", x: note.x + 8, y: y + 4 }, ")"));
      }
      if (head.accidental) {
        group.append(svg("text", { class: "accidental", x: note.x - 17, y: y + 5 }, head.accidental === "#" ? "♯" : "♭"));
      }
      if (note.value.dotted) {
        const dotY = head.pos % 2 === 0 ? y - HALF : y;
        group.append(svg("circle", { class: "dot", cx: note.x + 11, cy: dotY, r: 1.8 }));
      }
    }
  }

  _beams(group, notes, tip, triplet) {
    const stemX = (note) => note.x + 5;
    const deepest = Math.max(...notes.map((n) => Math.max(1, n.value.beams)));
    group.append(svg("rect", { class: "beam", x: stemX(notes[0]), y: tip, width: stemX(notes.at(-1)) - stemX(notes[0]) + 1.4, height: 4 }));
    for (let level = 2; level <= deepest; level++) {
      const y = tip + (level - 1) * 7;
      notes.forEach((note, i) => {
        if (note.value.beams < level) return;
        const next = notes[i + 1];
        if (next && next.value.beams >= level) {
          group.append(svg("rect", { class: "beam", x: stemX(note), y, width: stemX(next) - stemX(note) + 1.4, height: 4 }));
        } else if (!(notes[i - 1] && notes[i - 1].value.beams >= level)) {
          const towards = next ? 1 : -1;
          const x = towards > 0 ? stemX(note) : stemX(note) - 8;
          group.append(svg("rect", { class: "beam", x, y, width: 9, height: 4 }));
        }
      });
    }
    if (triplet) {
      const middle = (stemX(notes[0]) + stemX(notes.at(-1))) / 2;
      group.append(svg("text", { class: "tuplet", x: middle - 3, y: tip - 5 }, "3"));
    }
  }

  _renderLegend(drumTracks, pitchedTracks, pitched) {
    for (const track of drumTracks) {
      const voice = DRUM_VOICES[roleForTrack(track)] || DRUM_VOICES.other;
      const chip = document.createElement("span");
      chip.className = "legend-chip";
      chip.textContent = `${track.name} → ${voice.name}${voice.head === "x" ? " (×)" : ""}`;
      this.legend.append(chip);
    }
    for (const track of pitchedTracks) {
      const chip = document.createElement("span");
      chip.className = "legend-chip pitched";
      chip.textContent = `${track.name} → ${pitched.clef} clef${pitched.octaves ? `, ${OCTAVE_MARKS[pitched.octaves]}` : ""}`;
      this.legend.append(chip);
    }
    const note = document.createElement("span");
    note.className = "legend-note";
    note.textContent = "> accent · ( ) ghost · ○ open · rests not shown";
    this.legend.append(note);
  }

  setPlayhead(step) {
    for (const { line, firstStep, lastStep } of this.playheads) {
      if (step !== null && step >= firstStep && step <= lastStep) {
        const x = this.xOf(step);
        line.setAttribute("x1", x);
        line.setAttribute("x2", x);
        line.setAttribute("visibility", "visible");
      } else {
        line.setAttribute("visibility", "hidden");
      }
    }
  }
}
