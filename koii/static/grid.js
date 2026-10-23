// The step grid: one row per track, one cell per step. Click or drag to paint
// with the selected brush. Shorter tracks repeat; their repeats are shown faded,
// and painting on one first copies the track out to the full length.

import { cloneModel, isHit, normaliseHolds, patternLength, repeatTo, stepsPerBeat, velocityOf } from "./model.js";

const CYCLE = { ".": "x", "-": "x", x: "X", X: "o", o: "." };

export const BRUSHES = [
  { symbol: "cycle", label: "cycle", title: "Click cycles rest → hit → accent → ghost" },
  { symbol: "x", label: "x", title: "Hit (velocity 100)" },
  { symbol: "X", label: "X", title: "Accent (127)" },
  { symbol: "o", label: "o", title: "Ghost (50)" },
  { symbol: "-", label: "–", title: "Hold the previous note" },
  { symbol: ".", label: "·", title: "Rest (erase)" },
  ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => ({ symbol: String(n), label: String(n), title: `Level ${n}` })),
];

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export class Grid {
  /**
   * handlers: getBrush(), onEdit(model), onAudition(trackIndex), onRemove(i), onMove(i, delta),
   * onRename(i), onNotes(i, text)
   */
  constructor(container, handlers) {
    this.container = container;
    this.handlers = handlers;
    this.model = null;
    this.columns = [];
    this.playhead = null;
    this.painting = null;
    document.addEventListener("pointermove", (event) => this._paintMove(event));
    document.addEventListener("pointerup", () => this._endPaint());
    document.addEventListener("pointercancel", () => this._endPaint());
  }

  render(model) {
    this.model = model;
    this.container.replaceChildren();
    this.columns = [];
    this.playhead = null;
    const length = patternLength(model);
    const beat = stepsPerBeat(model);
    const bar = beat * 4;
    if (!length) {
      this.container.append(element("p", "empty", "No tracks yet. Add one below."));
      return;
    }
    const grid = element("div", "grid");
    grid.style.setProperty("--steps", length);

    const header = element("div", "grid-row grid-header");
    header.append(element("div", "track-head"));
    const headerCells = element("div", "cells");
    for (let step = 0; step < length; step++) {
      const cell = element("div", this._columnClass(step, beat, bar) + " head-cell");
      if (step % beat === 0) cell.textContent = `${Math.floor(step / bar) + 1}.${Math.floor((step % bar) / beat) + 1}`;
      headerCells.append(cell);
      this.columns[step] = [cell];
    }
    header.append(headerCells);
    grid.append(header);

    model.tracks.forEach((track, index) => grid.append(...this._trackRows(track, index, length, beat, bar)));
    this.container.append(grid);
  }

  _columnClass(step, beat, bar) {
    let name = "cell";
    if (step % bar === 0) name += " bar-start";
    else if (step % beat === 0) name += " beat-start";
    return name;
  }

  _trackRows(track, index, length, beat, bar) {
    const row = element("div", "grid-row");
    row.dataset.track = index;

    const head = element("div", "track-head");
    const name = element("button", "track-name", track.name);
    name.type = "button";
    name.title = "Click to hear it, double-click to rename";
    name.addEventListener("click", () => this.handlers.onAudition(index));
    name.addEventListener("dblclick", () => this.handlers.onRename(index));
    const target = element("span", "track-target", describeTarget(track.target));
    const tools = element("span", "track-tools");
    for (const [action, label, title] of [["up", "↑", "Move up"], ["down", "↓", "Move down"], ["remove", "✕", "Remove track"]]) {
      const button = element("button", "icon", label);
      button.type = "button";
      button.title = title;
      button.addEventListener("click", () => {
        if (action === "remove") this.handlers.onRemove(index);
        else this.handlers.onMove(index, action === "up" ? -1 : 1);
      });
      tools.append(button);
    }
    head.append(name, target, tools);

    const cells = element("div", "cells");
    for (let step = 0; step < length; step++) {
      const cell = element("div", this._columnClass(step, beat, bar));
      cell.dataset.step = step;
      this._paintCell(cell, track, step);
      cell.addEventListener("pointerdown", (event) => this._startPaint(event, index, step));
      cell.addEventListener("contextmenu", (event) => event.preventDefault());
      cells.append(cell);
      this.columns[step].push(cell);
    }
    row.append(head, cells);

    const rows = [row];
    if (track.target?.kind === "channel" || track.notes) {
      const notesRow = element("div", "grid-row notes-row");
      const label = element("div", "track-head notes-label", "notes");
      const input = element("input", "notes-input");
      input.value = track.notes || "";
      input.placeholder = "C1 Eb1 G0 (C4 = middle C, chords with +)";
      input.spellcheck = false;
      input.addEventListener("change", () => this.handlers.onNotes(index, input.value));
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") input.blur();
      });
      notesRow.append(label, input);
      rows.push(notesRow);
    }
    return rows;
  }

  _paintCell(cell, track, step) {
    const own = track.symbols.length;
    const symbol = track.symbols[step % own];
    cell.classList.remove("hit", "accent", "ghost", "hold", "repeat", "level");
    cell.textContent = "";
    if (step >= own) cell.classList.add("repeat");
    if (symbol === "-") cell.classList.add("hold");
    else if (isHit(symbol)) {
      cell.classList.add("hit");
      if (symbol === "X") cell.classList.add("accent");
      if (symbol === "o") cell.classList.add("ghost");
      if (/[1-9]/.test(symbol)) {
        cell.classList.add("level");
        cell.textContent = symbol;
      }
      cell.style.setProperty("--v", (velocityOf(symbol) / 127).toFixed(2));
    }
  }

  // -- painting ---------------------------------------------------------------

  _startPaint(event, trackIndex, step) {
    if (event.button !== 0 && event.button !== 2) return;
    event.preventDefault();
    const working = cloneModel(this.model);
    const track = working.tracks[trackIndex];
    const length = patternLength(working);
    if (step >= track.symbols.length) track.symbols = repeatTo(track.symbols, length);
    const brush = this.handlers.getBrush();
    let value;
    if (event.button === 2 || event.altKey) value = ".";
    else if (event.shiftKey) value = "-";
    else if (brush === "cycle") value = CYCLE[track.symbols[step]] ?? "x";
    else value = brush;
    this.painting = { trackIndex, value, working, row: event.currentTarget.parentElement };
    this._apply(step);
  }

  _paintMove(event) {
    if (!this.painting) return;
    const cell = document.elementFromPoint(event.clientX, event.clientY)?.closest?.(".cell[data-step]");
    if (!cell || cell.parentElement !== this.painting.row) return;
    const step = Number(cell.dataset.step);
    const track = this.painting.working.tracks[this.painting.trackIndex];
    if (step >= track.symbols.length) track.symbols = repeatTo(track.symbols, patternLength(this.painting.working));
    this._apply(step);
  }

  _apply(step) {
    const { working, trackIndex, value, row } = this.painting;
    const symbols = working.tracks[trackIndex].symbols;
    if (value === "-" && (step === 0 || symbols[step - 1] === ".")) return;
    symbols[step] = value;
    normaliseHolds(symbols);
    row.querySelectorAll(".cell[data-step]").forEach((cell) =>
      this._paintCell(cell, working.tracks[trackIndex], Number(cell.dataset.step)));
  }

  _endPaint() {
    if (!this.painting) return;
    const { working } = this.painting;
    this.painting = null;
    this.handlers.onEdit(working);
  }

  // -- playhead ---------------------------------------------------------------

  setPlayhead(step) {
    if (step === this.playhead) return;
    if (this.playhead !== null) this.columns[this.playhead]?.forEach((cell) => cell.classList.remove("playhead"));
    this.playhead = step;
    if (step === null) return;
    this.columns[step]?.forEach((cell) => cell.classList.add("playhead"));
    this._follow(this.columns[step]?.[0]);
  }

  /** Keep the playhead in view when the pattern is wider than the panel. */
  _follow(cell) {
    const scroller = this.container;
    if (!cell || scroller.scrollWidth <= scroller.clientWidth || this.painting) return;
    const left = cell.getBoundingClientRect().left - scroller.getBoundingClientRect().left + scroller.scrollLeft;
    const visibleFrom = scroller.scrollLeft + 160;
    const visibleTo = scroller.scrollLeft + scroller.clientWidth - 40;
    if (left < visibleFrom || left > visibleTo) scroller.scrollLeft = Math.max(0, left - 170);
  }
}

export function describeTarget(target) {
  if (!target) return "?";
  if (target.kind === "channel") return `${target.label} · pitched`;
  if (target.kind === "pad") return `${target.label} · ${target.note}`;
  return target.label === String(target.note) ? `note ${target.note}` : `${target.label} · ${target.note}`;
}
