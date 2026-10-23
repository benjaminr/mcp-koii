// Draws the server's score (koii/score.py) as SVG: a percussion staff plus a
// staff per pitched track, with rests, ties, dots, triplets, accents and
// ghost notes. The rhythm spelling is decided by the server; this only lays
// it out, placing each note in proportion to its time so the playhead lines up.

const SVG = "http://www.w3.org/2000/svg";
const HALF = 5;                 // half a staff space
const STAFF_HEIGHT = 8 * HALF;
const WIDTH = 920;
const LEFT = 70;
const RIGHT = 14;
const STEM = 30;
const STAFF_GAP = 110;          // from one staff's top line to the next staff's in a system
const SYSTEM_PADDING = 64;
const BEAMS = { whole: 0, half: 0, quarter: 0, eighth: 1, "16th": 2, "32nd": 3, "64th": 4 };
const HOLLOW = new Set(["whole", "half"]);
const CLEF_GLYPHS = { bass: { glyph: "𝄢", size: 34, dy: -8 }, treble: { glyph: "𝄞", size: 48, dy: -10 } };
const OCTAVE_MARKS = ["", "8vb", "15mb", "22mb"];

function svg(tag, attributes = {}, text) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

export class Notation {
  constructor(container, legend) {
    this.container = container;
    this.legend = legend;
    this.playheads = [];
  }

  render(pattern) {
    this.container.replaceChildren();
    this.legend.replaceChildren();
    this.playheads = [];
    const score = pattern?.score;
    if (!score || !score.staves.length) return;
    this.stepBeats = pattern.step_beats;

    const bars = score.staves[0].bars.length;
    const barsPerSystem = score.steps_per_beat > 4 ? 1 : 2;
    const systems = Math.ceil(bars / barsPerSystem);
    const barWidth = (WIDTH - LEFT - RIGHT) / barsPerSystem;
    const systemHeight = SYSTEM_PADDING + (score.staves.length - 1) * STAFF_GAP + STAFF_HEIGHT + 40;
    const root = svg("svg", { viewBox: `0 0 ${WIDTH} ${systems * systemHeight + 10}`, class: "score", role: "img",
                               "aria-label": "Pattern as sheet music" });

    this.xOf = (beat) => {
      const bar = Math.floor(beat / 4 + 1e-9);
      const within = beat - bar * 4;
      return LEFT + (bar % barsPerSystem) * barWidth + 16 + (within / 4) * (barWidth - 30);
    };

    for (let system = 0; system < systems; system++) {
      const firstBar = system * barsPerSystem;
      const lastBar = Math.min(bars, firstBar + barsPerSystem) - 1;
      const group = svg("g");
      root.append(group);
      score.staves.forEach((staff, index) => {
        const top = system * systemHeight + SYSTEM_PADDING + index * STAFF_GAP;
        this._staff(group, staff, top, firstBar, lastBar, bars, barWidth, system === 0, index === 0);
        const items = staff.bars.slice(firstBar, lastBar + 1).flat();
        this._items(group, staff, items, top, (lastBar + 1) * 4);
      });
      const top = system * systemHeight + SYSTEM_PADDING;
      const bottom = top + (score.staves.length - 1) * STAFF_GAP + STAFF_HEIGHT;
      const line = svg("line", { class: "score-playhead", x1: 0, x2: 0, y1: top - 34, y2: bottom + 14, visibility: "hidden" });
      group.append(line);
      this.playheads.push({ line, from: firstBar * 4, to: (lastBar + 1) * 4 });
    }
    this.container.append(root);
    this._legend(pattern, score);
  }

  // -- staves ---------------------------------------------------------------------

  _staff(group, staff, top, firstBar, lastBar, bars, barWidth, firstSystem, topStaff) {
    const right = WIDTH - RIGHT;
    for (let line = 0; line < 5; line++) {
      const y = top + line * 2 * HALF;
      group.append(svg("line", { class: "staff-line", x1: 8, x2: right, y1: y, y2: y }));
    }
    if (staff.clef === "percussion") {
      for (const x of [18, 25]) group.append(svg("rect", { class: "clef", x, y: top + 2 * HALF, width: 3.2, height: 4 * HALF }));
    } else {
      const clef = CLEF_GLYPHS[staff.clef];
      group.append(svg("text", { class: "clef-glyph", x: 14, y: top + STAFF_HEIGHT + clef.dy, "font-size": clef.size }, clef.glyph));
      if (staff.octave_shift) {
        group.append(svg("text", { class: "octave-mark", x: 16, y: top + STAFF_HEIGHT + 18 }, OCTAVE_MARKS[staff.octave_shift]));
      }
      group.append(svg("text", { class: "staff-name", x: 8, y: top - 10 }, staff.name));
    }
    if (firstSystem) {
      group.append(svg("text", { class: "time-sig", x: 46, y: top + 4 * HALF - 1 }, "4"));
      group.append(svg("text", { class: "time-sig", x: 46, y: top + STAFF_HEIGHT - 1 }, "4"));
    }
    for (let bar = firstBar + 1; bar <= lastBar; bar++) {
      const x = LEFT + (bar - firstBar) * barWidth;
      group.append(svg("line", { class: "bar-line", x1: x, x2: x, y1: top, y2: top + STAFF_HEIGHT }));
    }
    for (let bar = firstBar; bar <= lastBar && topStaff; bar++) {
      group.append(svg("text", { class: "bar-number", x: LEFT + (bar - firstBar) * barWidth + 4, y: top - 46 }, String(bar + 1)));
    }
    const final = lastBar === bars - 1;
    group.append(svg("line", { class: final ? "bar-line final" : "bar-line", x1: right, x2: right, y1: top, y2: top + STAFF_HEIGHT }));
    if (final) group.append(svg("line", { class: "bar-line", x1: right - 5, x2: right - 5, y1: top, y2: top + STAFF_HEIGHT }));
  }

  // -- notes and rests ----------------------------------------------------------------

  _items(group, staff, items, top, systemEnd) {
    const yOf = (position) => top + STAFF_HEIGHT - position * HALF;
    const notes = [];
    for (const item of items) {
      const x = this.xOf(item.start);
      if (item.rest) {
        this._rest(group, item, x, top);
        continue;
      }
      const positions = item.heads.map((h) => h.position);
      const mean = positions.reduce((a, b) => a + b, 0) / positions.length;
      const up = staff.kind === "drums" || mean <= 4;
      const note = { item, x, up, low: yOf(Math.min(...positions)), high: yOf(Math.max(...positions)),
                     beams: BEAMS[item.value], beat: Math.floor(item.start + 1e-9) };
      this._heads(group, staff, note, yOf);
      notes.push(note);
    }
    this._stemsAndBeams(group, notes);
    this._ties(group, notes, yOf, systemEnd);
    this._tuplets(group, notes);
  }

  _rest(group, item, x, top) {
    const middle = top + 2 * 2 * HALF;
    if (item.value === "whole") {
      // A whole-bar rest hangs centred in its bar from the fourth line.
      const centre = this.xOf(item.start + 2);
      group.append(svg("rect", { class: "rest-block", x: centre - 6, y: top + 2 * HALF, width: 12, height: 5 }));
    } else if (item.value === "half") {
      group.append(svg("rect", { class: "rest-block", x: x - 6, y: middle - 5, width: 12, height: 5 }));
    } else if (item.value === "quarter") {
      // Drawn rather than taken from a font: music fonts vary a lot between systems.
      group.append(svg("path", { class: "rest-stroke",
        d: `M${x - 2} ${middle - 11} L${x + 4} ${middle - 4} L${x - 1} ${middle + 1} L${x + 5} ${middle + 7} ` +
           `Q${x - 3} ${middle + 4} ${x + 1} ${middle + 12}` }));
    } else {
      // Eighth and shorter: a slanted stem with one hook per flag.
      const hooks = BEAMS[item.value];
      const topY = middle - 8;
      const bottomY = middle + 6 + hooks * 5;
      const stemTop = x + 4;
      const slope = 5 / (bottomY - topY);
      group.append(svg("line", { class: "rest-stroke", x1: stemTop, y1: topY, x2: stemTop - (bottomY - topY) * slope, y2: bottomY }));
      for (let hook = 0; hook < hooks; hook++) {
        const hookY = topY + hook * 6;
        const hookX = stemTop - (hookY - topY) * slope;
        group.append(svg("circle", { class: "rest-dot", cx: hookX - 6, cy: hookY + 2, r: 2.3 }));
        group.append(svg("path", { class: "rest-stroke", d: `M${hookX - 6} ${hookY + 2} Q${hookX - 2} ${hookY + 4} ${hookX} ${hookY}` }));
      }
    }
    for (let d = 0; d < item.dots; d++) group.append(svg("circle", { class: "dot", cx: x + 10 + d * 5, cy: middle - HALF, r: 1.8 }));
  }

  _heads(group, staff, note, yOf) {
    const { item, x } = note;
    for (const head of item.heads) {
      const y = yOf(head.position);
      for (let ledger = 10; ledger <= head.position; ledger += 2) this._ledger(group, x, yOf(ledger));
      for (let ledger = -2; ledger >= head.position; ledger -= 2) this._ledger(group, x, yOf(ledger));
      if (head.notehead === "x") {
        group.append(svg("path", { class: "head-x", d: `M${x - 4} ${y - 4} L${x + 4} ${y + 4} M${x - 4} ${y + 4} L${x + 4} ${y - 4}` }));
      } else {
        group.append(svg("ellipse", { class: HOLLOW.has(item.value) ? "head hollow" : "head", cx: x, cy: y, rx: 5.4, ry: 3.9,
                                      transform: `rotate(-22 ${x} ${y})` }));
      }
      if (staff.kind === "drums" && head.velocity <= 50) {
        group.append(svg("text", { class: "ghost-mark", x: x - 12, y: y + 4 }, "("));
        group.append(svg("text", { class: "ghost-mark", x: x + 8, y: y + 4 }, ")"));
      }
      if (head.accidental && !item.tie_stop) {
        group.append(svg("text", { class: "accidental", x: x - 17, y: y + 5 }, head.accidental === "#" ? "♯" : "♭"));
      }
      for (let d = 0; d < item.dots; d++) {
        group.append(svg("circle", { class: "dot", cx: x + 11 + d * 5, cy: head.position % 2 === 0 ? y - HALF : y, r: 1.8 }));
      }
    }
  }

  _ledger(group, x, y) {
    group.append(svg("line", { class: "ledger", x1: x - 8, x2: x + 8, y1: y, y2: y }));
  }

  _stemsAndBeams(group, notes) {
    // Beam together the notes of one beat that have flags, as long as no rest splits them.
    const groups = [];
    let current = [];
    const flush = () => { if (current.length) groups.push(current); current = []; };
    notes.forEach((note, i) => {
      const previous = notes[i - 1];
      const joins = previous && note.beams > 0 && previous.beams > 0 && previous.beat === note.beat &&
        previous.up === note.up && Math.abs(previous.item.start + previous.item.length - note.item.start) < 1e-6;
      if (!joins) flush();
      current.push(note);
    });
    flush();

    for (const members of groups) {
      const beamed = members.length > 1;
      const up = members[0].up;
      const tip = up ? Math.min(...members.map((n) => n.high)) - STEM : Math.max(...members.map((n) => n.low)) + STEM;
      for (const note of members) {
        if (note.item.value === "whole") continue;
        const stemX = up ? note.x + 5 : note.x - 5;
        const from = up ? note.low - 1 : note.high + 1;
        const to = beamed ? tip : (up ? note.high - STEM : note.low + STEM);
        group.append(svg("line", { class: "stem", x1: stemX, x2: stemX, y1: from, y2: to }));
        if (!beamed) {
          for (let f = 0; f < note.beams; f++) {
            const y = to + (up ? f * 7 : -f * 7);
            group.append(svg("path", { class: "flag", d: `M${stemX} ${y} q 9 ${up ? 5 : -5} 7 ${up ? 15 : -15}` }));
          }
        }
        const markY = up ? to - 8 : note.high - 10;
        if (note.item.heads.some((h) => h.velocity >= 120)) group.append(svg("text", { class: "accent", x: note.x - 4, y: markY }, ">"));
        if (note.item.heads.some((h) => h.open)) group.append(svg("circle", { class: "open-mark", cx: note.x + 1, cy: markY - 12, r: 3.4 }));
      }
      if (beamed) this._beams(group, members, tip, up);
    }
  }

  _beams(group, members, tip, up) {
    const stemX = (note) => (up ? note.x + 5 : note.x - 5);
    const levelY = (level) => (up ? tip + (level - 1) * 7 : tip - (level - 1) * 7 - 4);
    const deepest = Math.max(...members.map((n) => n.beams));
    for (let level = 1; level <= deepest; level++) {
      members.forEach((note, i) => {
        if (note.beams < level) return;
        const next = members[i + 1];
        if (next && next.beams >= level) {
          group.append(svg("rect", { class: "beam", x: stemX(note), y: levelY(level), width: stemX(next) - stemX(note) + 1.4, height: 4 }));
        } else if (!(members[i - 1] && members[i - 1].beams >= level)) {
          // A lone short note in a beamed group gets a stub towards its neighbour.
          const x = next ? stemX(note) : stemX(note) - 8;
          group.append(svg("rect", { class: "beam", x, y: levelY(level), width: 9, height: 4 }));
        }
      });
    }
  }

  _ties(group, notes, yOf, systemEnd) {
    notes.forEach((note, i) => {
      if (!note.item.tie_start) return;
      const next = notes[i + 1];
      // Ties to the next system end at this system's edge.
      const toX = next && next.item.tie_stop ? next.x : this.xOf(Math.min(systemEnd, note.item.start + note.item.length)) - 4;
      for (const head of note.item.heads) {
        const y = yOf(head.position) + (note.up ? 6 : -6);
        const bend = note.up ? 7 : -7;
        group.append(svg("path", { class: "tie", d: `M${note.x + 4} ${y} Q ${(note.x + toX) / 2} ${y + bend} ${toX - 4} ${y}` }));
      }
    });
  }

  _tuplets(group, notes) {
    let run = [];
    const flush = () => {
      if (run.length) {
        const up = run[0].up;
        const middle = (run[0].x + run.at(-1).x + 6) / 2;
        const y = up ? Math.min(...run.map((n) => n.high)) - STEM - 9 : Math.max(...run.map((n) => n.low)) + STEM + 16;
        group.append(svg("text", { class: "tuplet", x: middle - 2, y }, "3"));
      }
      run = [];
    };
    notes.forEach((note) => {
      if (!note.item.tuplet) return flush();
      if (run.length && run[0].beat !== note.beat) flush();
      run.push(note);
    });
    flush();
  }

  _legend(pattern, score) {
    const noteheads = new Map();
    for (const staff of score.staves.filter((s) => s.kind === "drums")) {
      for (const bar of staff.bars) for (const item of bar) for (const head of item.heads) noteheads.set(head.track, head.notehead);
    }
    for (const track of pattern.tracks.filter((t) => t.target.kind !== "channel")) {
      const chip = document.createElement("span");
      chip.className = "legend-chip";
      chip.textContent = `${track.name}${noteheads.get(track.name) === "x" ? " ×" : ""}`;
      this.legend.append(chip);
    }
    for (const staff of score.staves.filter((s) => s.kind === "pitched")) {
      const chip = document.createElement("span");
      chip.className = "legend-chip pitched";
      chip.textContent = `${staff.name} · ${staff.clef} clef${staff.octave_shift ? ` · ${OCTAVE_MARKS[staff.octave_shift]}` : ""}`;
      this.legend.append(chip);
    }
    const note = document.createElement("span");
    note.className = "legend-note";
    note.textContent = "> accent · ( ) ghost · ○ open · swing is played, not written";
    this.legend.append(note);
  }

  setPlayhead(step) {
    const beat = step === null ? null : step * this.stepBeats;
    for (const { line, from, to } of this.playheads) {
      if (beat !== null && beat >= from && beat < to) {
        const x = this.xOf(beat);
        line.setAttribute("x1", x);
        line.setAttribute("x2", x);
        line.setAttribute("visibility", "visible");
      } else {
        line.setAttribute("visibility", "hidden");
      }
    }
  }
}
