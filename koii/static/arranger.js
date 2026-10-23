// The arranger: a song as a grid. Rows are lanes (one per pattern), columns are
// sections. A lit cell plays that pattern in that section, so layering is lighting
// several cells in one column and sequencing is adding columns. Each column's width
// follows how long it plays.
//
// The text form ("intro x2, verse+bass x4") is what the server plays and checks. The
// grid reads it and writes it back, so typing and clicking stay in step.

const SECTION_FORMAT = /^([\w.\-]+(?:\s*\+\s*[\w.\-]+)*)(?:\s+[x×]\s*(\d+))?$/;
const MAX_REPEAT = 999;
const MAX_SONG_DEPTH = 8;
const DRAG_TYPE = "text/koii-name";
const SECTION_DRAG_TYPE = "text/koii-section";
const LANE_COLOURS = ["#ff5a1f", "#4ba6e0", "#efb02e", "#3fa96b", "#ff4f8b", "#8e7cc3", "#cdd1d0", "#e07b39"];

/** Mark something as a pattern or song that can be dropped on the arranger. */
export function makeDraggable(node, name) {
  node.draggable = true;
  node.addEventListener("dragstart", (event) => {
    event.dataTransfer.setData(DRAG_TYPE, name);
    event.dataTransfer.effectAllowed = "copy";
  });
}

/**
 * Read arrangement text into sections ({ layers, repeat }). Mirrors the server's reader;
 * returns { sections } or { error } for text it can't read.
 */
export function parseArrangement(text) {
  const sections = [];
  for (const line of text.split("\n")) {
    const code = line.replace(/(^|\s)#.*$/, "");
    for (const raw of code.split(",")) {
      const item = raw.trim();
      if (!item) continue;
      const match = SECTION_FORMAT.exec(item);
      if (!match) return { error: `can't read '${item}'` };
      const repeat = Number(match[2] || 1);
      if (repeat < 1 || repeat > MAX_REPEAT) return { error: `repeat in '${item}' must be 1–${MAX_REPEAT}` };
      sections.push({ layers: match[1].split("+").map((name) => name.trim()), repeat });
    }
  }
  return { sections };
}

/** Sections back to text, skipping empty ones. */
export function arrangementText(sections) {
  return sections
    .filter((section) => section.layers.length)
    .map((section) => section.layers.join("+") + (section.repeat > 1 ? ` x${section.repeat}` : ""))
    .join(", ");
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function tool(label, title, onClick) {
  const node = element("button", "arr-tool", label);
  node.type = "button";
  node.title = title;
  node.setAttribute("aria-label", title);
  node.addEventListener("click", onClick);
  return node;
}

function formatSeconds(seconds) {
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  return `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
}

export class Arranger {
  /**
   * container: where the grid goes. getLibrary(): { patterns, songs } as the server sends them.
   * onChange(text): the grid was edited. onAudition(name): play one pattern or song.
   */
  constructor(container, { getLibrary, onChange, onAudition }) {
    this.container = container;
    this.getLibrary = getLibrary;
    this.onChange = onChange;
    this.onAudition = onAudition;
    this.sections = [];
    this.lanes = [];
    this.playing = null;
    container.addEventListener("dragover", (event) => this._dragOver(event));
    container.addEventListener("dragleave", (event) => this._dragLeave(event));
    container.addEventListener("drop", (event) => this._drop(event));
    this.render();
  }

  // -- reading and writing --------------------------------------------------------------

  /** Show arrangement text (typed, or a song opened). Lanes added by hand but unused stay. */
  setText(text) {
    const { sections, error } = parseArrangement(text);
    if (error) return false;   // the server reports it; keep the grid as it was meanwhile
    this.sections = sections;
    const used = sections.flatMap((section) => section.layers);
    this.lanes = [...new Set([...used, ...this.lanes.filter((lane) => this._exists(lane))])];
    this.render();
    return true;
  }

  /** Start a new, empty song. */
  clear() {
    this.sections = [];
    this.lanes = [];
    this.render();
  }

  text() {
    return arrangementText(this.sections.map((section) => ({ ...section, layers: this._inLaneOrder(section.layers) })));
  }

  _changed() {
    this.render();
    this.onChange(this.text());
  }

  // -- editing ------------------------------------------------------------------------

  addLane(name) {
    if (!this.lanes.includes(name)) this.lanes.push(name);
    this.render();
  }

  /** Add a section at the end (or at `index`) playing these patterns. */
  addSection(layers = [], index = this.sections.length) {
    for (const name of layers) if (!this.lanes.includes(name)) this.lanes.push(name);
    this.sections.splice(index, 0, { layers: [...layers], repeat: 1 });
    this._changed();
  }

  _toggle(lane, column) {
    const section = this.sections[column];
    section.layers = section.layers.includes(lane)
      ? section.layers.filter((name) => name !== lane)
      : this._inLaneOrder([...section.layers, lane]);
    this._changed();
  }

  _repeat(column, delta) {
    const section = this.sections[column];
    section.repeat = Math.min(MAX_REPEAT, Math.max(1, section.repeat + delta));
    this._changed();
  }

  _moveSection(from, to) {
    if (to < 0 || to >= this.sections.length || from === to) return;
    const [section] = this.sections.splice(from, 1);
    this.sections.splice(to, 0, section);
    this._changed();
  }

  _duplicate(column) {
    const section = this.sections[column];
    this.sections.splice(column + 1, 0, { layers: [...section.layers], repeat: section.repeat });
    this._changed();
  }

  _removeSection(column) {
    this.sections.splice(column, 1);
    this._changed();
  }

  _removeLane(lane) {
    this.lanes = this.lanes.filter((name) => name !== lane);
    for (const section of this.sections) section.layers = section.layers.filter((name) => name !== lane);
    this._changed();
  }

  _moveLane(lane, delta) {
    const from = this.lanes.indexOf(lane);
    const to = from + delta;
    if (to < 0 || to >= this.lanes.length) return;
    this.lanes.splice(from, 1);
    this.lanes.splice(to, 0, lane);
    this._changed();   // the top lit lane sets a section's tempo, so the text can change
  }

  /** Each lane gets its own colour, in lane order. */
  _colour(lane) {
    return LANE_COLOURS[this._laneIndex(lane) % LANE_COLOURS.length];
  }

  _inLaneOrder(names) {
    return [...names].sort((a, b) => this._laneIndex(a) - this._laneIndex(b));
  }

  _laneIndex(name) {
    const index = this.lanes.indexOf(name);
    return index < 0 ? Number.MAX_SAFE_INTEGER : index;
  }

  // -- what each section plays like ------------------------------------------------------

  _library() {
    const library = this.getLibrary() || { patterns: [], songs: [] };
    return {
      patterns: new Map(library.patterns.map((pattern) => [pattern.name, pattern])),
      songs: new Map(library.songs.map((song) => [song.name, song])),
    };
  }

  _exists(name) {
    const { patterns, songs } = this._library();
    return patterns.has(name) || songs.has(name);
  }

  /**
   * How a section plays: { seconds, bpm, beats } or { problem }. Follows the server's rules:
   * the first layer sets the tempo (unless a song sets one), shorter layers must divide the
   * longest, and a song plays on its own.
   */
  _measure(layers, repeat, library, bpmOverride = null, depth = 0) {
    if (!layers.length) return { empty: true };
    const ordered = this._inLaneOrder(layers);
    const song = ordered.length === 1 ? library.songs.get(ordered[0]) : null;
    if (song) {
      if (depth >= MAX_SONG_DEPTH) return { problem: "songs nest too deeply" };
      const inner = parseArrangement(song.arrangement);
      if (inner.error) return { problem: `song '${song.name}': ${inner.error}` };
      let seconds = 0;
      for (const section of inner.sections) {
        const measured = this._measure(section.layers, section.repeat, library, bpmOverride || song.bpm, depth + 1);
        if (measured.problem) return { problem: `in song '${song.name}': ${measured.problem}` };
        seconds += measured.seconds || 0;
      }
      return { seconds: seconds * repeat, song: true };
    }
    const patterns = [];
    for (const name of ordered) {
      if (library.songs.has(name)) return { problem: `'${name}' is a song; songs play on their own, not layered` };
      const pattern = library.patterns.get(name);
      if (!pattern) return { problem: `no pattern named '${name}'` };
      if (pattern.error) return { problem: `'${name}' doesn't parse` };
      patterns.push(pattern);
    }
    const beats = Math.max(...patterns.map((pattern) => pattern.beats));
    const misfit = patterns.find((pattern) => beats % pattern.beats);
    if (misfit) return { problem: `'${misfit.name}' is ${misfit.beats} beats, which doesn't fit ${beats} beats evenly` };
    const bpm = bpmOverride || patterns[0].bpm;
    return { seconds: (beats * 60 / bpm) * repeat, bpm, beats };
  }

  // -- playback --------------------------------------------------------------------------

  /** Light the section playing `seconds` into the arrangement, or none (null). */
  setPlayhead(seconds) {
    const columns = this.timing || [];
    let column = null;
    let progress = 0;
    if (seconds !== null) {
      let start = 0;
      for (const [index, entry] of columns.entries()) {
        const length = entry.seconds || 0;
        if (length && seconds < start + length) {
          column = index;
          progress = (seconds - start) / length;
          break;
        }
        start += length;
      }
    }
    if (column !== this.playing) {
      this.container.querySelectorAll(".arr-playing").forEach((node) => node.classList.remove("arr-playing"));
      if (column !== null) this.container.querySelectorAll(`[data-column="${column}"]`).forEach((node) => node.classList.add("arr-playing"));
      this.playing = column;
    }
    if (column !== null) this.container.style.setProperty("--arr-progress", progress.toFixed(3));
  }

  // -- drawing ---------------------------------------------------------------------------

  render() {
    const library = this._library();
    this.timing = this.sections.map((section) => this._measure(section.layers, section.repeat, library));
    const total = this.timing.reduce((sum, entry) => sum + (entry.seconds || 0), 0);
    const grid = element("div", "arr-grid");
    const widths = this.timing.map((entry) => (entry.seconds ? Math.max(0.6, (entry.seconds / (total || 1)) * this.sections.length) : 1));
    grid.style.gridTemplateColumns = `minmax(130px, 170px) ${widths.map((width) => `minmax(76px, ${width.toFixed(3)}fr)`).join(" ")} 44px`;

    grid.append(this._corner(total));
    this.sections.forEach((section, column) => grid.append(this._sectionHead(section, column)));
    grid.append(this._addColumn(this.sections.length + 2));

    for (const lane of this.lanes) {
      grid.append(this._laneHead(lane, library));
      this.sections.forEach((section, column) => grid.append(this._cell(lane, section, column)));
      grid.append(element("div", "arr-filler"));
    }
    grid.append(...this._emptyLane());

    this.container.replaceChildren(grid);
    if (!this.sections.length && !this.lanes.length) {
      this.container.append(element("p", "arr-empty",
        "Drag a pattern onto the grid, or press + on it in the list, to start a song. Light more cells in a column to layer patterns."));
    }
    this.playing = null;
  }

  _corner(total) {
    const corner = element("div", "arr-corner");
    corner.append(element("span", "arr-corner-label", "lanes ↓ · sections →"));
    if (total) corner.append(element("span", "arr-total num", formatSeconds(total)));
    return corner;
  }

  _sectionHead(section, column) {
    const head = element("div", "arr-head");
    head.dataset.column = column;
    head.dataset.drop = "section";
    head.draggable = true;
    head.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData(SECTION_DRAG_TYPE, String(column));
      event.dataTransfer.effectAllowed = "move";
    });
    const timing = this.timing[column];
    const top = element("div", "arr-head-top");
    top.append(element("span", "arr-number num", String(column + 1)));
    const repeat = element("span", "arr-repeat");
    repeat.append(tool("−", "Play it fewer times", () => this._repeat(column, -1)),
                  element("span", "num", `×${section.repeat}`),
                  tool("+", "Play it more times", () => this._repeat(column, 1)));
    top.append(repeat);
    head.append(top);

    let detail = "empty: light a cell below";
    if (timing.problem) detail = "can't play";
    else if (timing.song) detail = `song · ${formatSeconds(timing.seconds)}`;
    else if (timing.seconds) detail = `${+(timing.beats / 4).toFixed(2)} bar${timing.beats === 4 ? "" : "s"} · ${timing.bpm} · ${formatSeconds(timing.seconds)}`;
    const info = element("div", "arr-detail num", detail);
    if (timing.problem) {
      head.classList.add("arr-problem");
      head.title = timing.problem;
    }
    head.append(info);

    const tools = element("div", "arr-head-tools");
    tools.append(
      tool("←", "Move earlier", () => this._moveSection(column, column - 1)),
      tool("→", "Move later", () => this._moveSection(column, column + 1)),
      tool("⧉", "Duplicate", () => this._duplicate(column)),
      tool("✕", "Remove this section", () => this._removeSection(column)),
    );
    head.append(tools, element("div", "arr-progress"));
    return head;
  }

  _addColumn(gridColumn) {
    const add = element("button", "arr-add-column", "+");
    add.style.gridArea = `1 / ${gridColumn}`;   // the header row, after the last section
    add.type = "button";
    add.title = "Add a section (a copy of the last one); or drop a pattern here";
    add.dataset.drop = "new-section";
    add.addEventListener("click", () => {
      const last = this.sections[this.sections.length - 1];
      this.addSection(last ? last.layers : []);
    });
    return add;
  }

  _laneHead(lane, library) {
    const head = element("div", "arr-lane");
    head.dataset.lane = lane;
    head.dataset.drop = "lane";
    const swatch = element("span", "arr-swatch");
    swatch.style.background = this._colour(lane);
    const name = element("button", "arr-lane-name", lane);
    name.type = "button";
    name.title = library.songs.has(lane) ? "A song: click to hear it" : "Click to hear it";
    name.addEventListener("click", () => this.onAudition(lane));
    if (!this._exists(lane)) {
      head.classList.add("arr-problem");
      head.title = `no pattern or song named '${lane}'`;
    }
    const tools = element("span", "arr-lane-tools");
    tools.append(
      tool("↑", "Move this lane up (the top lit lane sets a section's tempo)", () => this._moveLane(lane, -1)),
      tool("↓", "Move this lane down", () => this._moveLane(lane, 1)),
      tool("✕", "Remove this lane from the song", () => this._removeLane(lane)),
    );
    head.append(swatch, name, tools);
    return head;
  }

  _cell(lane, section, column) {
    const on = section.layers.includes(lane);
    const cell = element("button", `arr-cell${on ? " on" : ""}`);
    cell.type = "button";
    cell.dataset.column = column;
    cell.dataset.lane = lane;
    cell.dataset.drop = "cell";
    cell.setAttribute("aria-pressed", String(on));
    cell.title = `${on ? "Stop playing" : "Play"} ${lane} in section ${column + 1}`;
    if (on) {
      cell.style.setProperty("--lane", this._colour(lane));
      if (section.repeat > 1) cell.append(element("span", "arr-cell-repeat num", `×${section.repeat}`));
    }
    cell.addEventListener("click", () => this._toggle(lane, column));
    return cell;
  }

  /** The last row is always an empty lane: drop a pattern on it to add a lane (lit where it lands). */
  _emptyLane() {
    const head = element("div", "arr-lane arr-lane-empty", "drop a pattern here");
    head.dataset.drop = "new-lane";
    head.title = "Drag a pattern from the list onto this row to add a lane; onto one of its cells to light it there too";
    const cells = this.sections.map((section, column) => {
      const cell = element("div", "arr-cell arr-cell-empty");
      cell.dataset.column = column;
      cell.dataset.drop = "new-lane";
      return cell;
    });
    return [head, ...cells, element("div", "arr-filler")];
  }

  // -- dragging in ----------------------------------------------------------------------

  _target(event) {
    return event.target.closest?.("[data-drop]") || null;
  }

  _dragOver(event) {
    const types = [...event.dataTransfer.types];
    if (!types.includes(DRAG_TYPE) && !types.includes(SECTION_DRAG_TYPE)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = types.includes(SECTION_DRAG_TYPE) ? "move" : "copy";
    const target = this._target(event);
    if (target !== this.dropTarget) {
      this.dropTarget?.classList.remove("arr-drop");
      target?.classList.add("arr-drop");
      this.dropTarget = target;
    }
    this.container.classList.add("arr-dragging");
  }

  _dragLeave(event) {
    if (this.container.contains(event.relatedTarget)) return;
    this.dropTarget?.classList.remove("arr-drop");
    this.dropTarget = null;
    this.container.classList.remove("arr-dragging");
  }

  /**
   * Drop a pattern on a cell to play it there, on a section to layer it in, on + for a new
   * section, or anywhere else for a new lane. Drop a section on another to move it there.
   */
  _drop(event) {
    event.preventDefault();
    const target = this._target(event);
    this._dragLeave({ relatedTarget: null });
    const moved = event.dataTransfer.getData(SECTION_DRAG_TYPE);
    if (moved !== "") {
      if (target?.dataset.column !== undefined) this._moveSection(Number(moved), Number(target.dataset.column));
      return;
    }
    const name = event.dataTransfer.getData(DRAG_TYPE);
    if (!name) return;
    const column = target?.dataset.column !== undefined ? Number(target.dataset.column) : null;
    if (target?.dataset.drop === "new-section" || (!this.sections.length && column === null)) {
      this.addSection([name]);
      return;
    }
    if (!this.lanes.includes(name)) this.lanes.push(name);
    if (column !== null && !this.sections[column].layers.includes(name)) {
      this._toggle(name, column);
      return;
    }
    this.render();
  }
}
