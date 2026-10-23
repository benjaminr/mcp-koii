// An on-screen EP-133 K.O. II, laid out like the real top panel: faceplate,
// screen (bar.beat.step counter, group indicators, level meters) and the key
// grid with group keys A–D, the 12 pads and the function keys.
//
// Interactive: pads (audition), group keys (choose which group the pads show),
// PLAY (play/stop), − and + (tempo). Other keys are there for the look.

const PAD_KEYS = [".", "0", "Enter", "1", "2", "3", "4", "5", "6", "7", "8", "9"];
const GROUP_BASE = { A: 36, B: 48, C: 60, D: 72 };
const GROUPS = ["A", "B", "C", "D"];
const GROUP_ICONS = { A: "✳", B: "↩", C: "↥", D: "↧" };
const PAD_ROWS = [["7", "8", "9"], ["4", "5", "6"], ["1", "2", "3"], [".", "0", "Enter"]];
// Knob-mode labels printed between the pad rows on the device.
const ROW_LABELS = [["LEVEL", "PITCH", "TIME"], ["LPF", "HPF", "→FX"], ["ATK", "REL", "PAN"], ["TUNE", "VEL", "MOD"]];
const MIN_LIT_MS = 90;
const METER_SEGMENTS = 8;
const METER_DECAY_PER_SECOND = 2.2;
const ALIAS_PREFERENCE = ["kick", "snare", "clap", "rim", "hat", "openhat", "ride", "crash", "perc", "bass", "keys"];

export function noteToPad(note) {
  for (const [group, base] of Object.entries(GROUP_BASE)) {
    if (note >= base && note < base + 12) {
      const key = PAD_KEYS[note - base];
      return { group, key, label: group + key };
    }
  }
  return null;
}

export function padToNote(label) {
  return GROUP_BASE[label[0]] + PAD_KEYS.indexOf(label.slice(1));
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** A two-part key like SOUND / EDIT: a label on top, a second label below. */
function splitKey(top, bottom, variant = "") {
  const key = element("div", `ko-split ${variant}`);
  key.append(element("span", "ko-split-top", top), element("span", "ko-split-bottom", bottom));
  return key;
}

function led(className = "") {
  return element("span", `ko-led ${className}`);
}

export class Device {
  /** handlers: onPad(label), onTransport(action) where action is "play", "minus" or "plus". */
  constructor(container, { onPad, onTransport }) {
    this.group = "A";
    this.aliases = {};
    this.lit = new Map();
    this.padElements = {};
    this.groupElements = {};
    this.groupLeds = {};
    this.meters = {};
    this.levels = { A: 0, B: 0, C: 0, D: 0 };
    this.lastTick = performance.now();
    this.onPad = onPad;
    this.onTransport = onTransport;
    container.append(this._build());
    this.selectGroup("A");
  }

  // -- construction -------------------------------------------------------------

  _build() {
    const ko = element("div", "ko");
    ko.append(this._faceplate(), this._screen(), this._face());
    return ko;
  }

  _faceplate() {
    const plate = element("div", "ko-plate");
    const name = element("div", "ko-name");
    name.append(element("span", "ko-name-model", "ep-133"), element("span", "ko-name-note", "simulated view"));
    this.modeTag = element("span", "ko-mode-tag", "MAIN");
    const grille = element("div", "ko-grille");
    for (let i = 0; i < 40; i++) grille.append(element("span"));
    plate.append(name, this.modeTag, grille);
    return plate;
  }

  _screen() {
    const screen = element("div", "ko-screen");

    const groups = element("div", "ko-screen-groups");
    this.screenGroups = {};
    for (const group of GROUPS) {
      const cell = element("span", `ko-screen-group g-${group}`, group);
      this.screenGroups[group] = cell;
      groups.append(cell);
    }

    const middle = element("div", "ko-screen-middle");
    const counter = element("div", "ko-counter");
    counter.append(element("span", "ko-counter-ghost", "8.8.8"));
    this.counter = element("span", "ko-counter-value", "1.1.1");
    counter.append(this.counter);
    const status = element("div", "ko-screen-status");
    this.playIcon = element("span", "ko-play-icon", "▶");
    this.bpmText = element("span", "ko-bpm", "BPM ---");
    this.subText = element("span", "ko-sub", "ready");
    status.append(this.playIcon, this.bpmText, this.subText);
    middle.append(element("span", "ko-screen-label", "BAR"), counter, status);

    const meters = element("div", "ko-meters");
    for (const group of GROUPS) {
      const meter = element("div", `ko-meter g-${group}`);
      for (let i = 0; i < METER_SEGMENTS; i++) meter.append(element("span"));
      this.meters[group] = [...meter.children];
      meters.append(meter);
    }

    screen.append(groups, middle, meters);
    return screen;
  }

  _face() {
    const face = element("div", "ko-face");
    const place = (node, column, row, span = 1) => {
      node.style.gridColumn = String(column);
      node.style.gridRow = span > 1 ? `${row} / span ${span}` : String(row);
      face.append(node);
      return node;
    };

    // Top row: volume, SOUND/EDIT, MAIN/COMMIT, TEMPO/LOOP, the BPM–METRONOME bracket, X and Y.
    const volume = element("div", "ko-knob-wrap");
    volume.append(element("span", "ko-caption", "VOLUME"), element("div", "ko-knob volume"));
    place(volume, 1, 1);
    place(splitKey("SOUND", "EDIT"), 2, 1);
    place(splitKey("MAIN", "COMMIT", "orange"), 3, 1);
    place(splitKey("TEMPO", "LOOP", "grey"), 4, 1);
    this.knobX = element("div", "ko-knob x");
    this.knobY = element("div", "ko-knob y");
    const xWrap = element("div", "ko-knob-wrap");
    xWrap.append(element("span", "ko-caption", "BPM"), this.knobX, element("span", "ko-knob-tag orange", "X"));
    const yWrap = element("div", "ko-knob-wrap");
    yWrap.append(element("span", "ko-caption", "SWING"), this.knobY, element("span", "ko-knob-tag", "Y"));
    place(xWrap, 6, 1);
    place(yWrap, 7, 1);

    // Pad rows, each with a strip of labels and LEDs above it.
    PAD_ROWS.forEach((keys, index) => {
      const labelRow = 2 + index * 2;
      const keyRow = labelRow + 1;
      const group = GROUPS[index];

      const groupLed = place(element("div", "ko-label"), 2, labelRow);
      this.groupLeds[group] = led();
      groupLed.append(this.groupLeds[group]);
      ROW_LABELS[index].forEach((text, column) => {
        const label = place(element("div", "ko-label"), 3 + column, labelRow);
        label.append(led(), element("span", "", text));
      });

      const groupKey = element("button", "ko-group");
      groupKey.type = "button";
      groupKey.append(element("span", "ko-group-letter", group), element("span", "ko-group-icon", GROUP_ICONS[group]));
      groupKey.title = `Show group ${group} on the pads (notes ${GROUP_BASE[group]}–${GROUP_BASE[group] + 11})`;
      groupKey.addEventListener("click", () => this.selectGroup(group));
      this.groupElements[group] = groupKey;
      place(groupKey, 2, keyRow);

      keys.forEach((key, column) => {
        const pad = element("button", "ko-pad");
        pad.type = "button";
        pad.append(element("span", key === "Enter" ? "ko-pad-key enter" : "ko-pad-key", key === "Enter" ? "ENTER" : key),
                   element("span", "ko-pad-alias"));
        pad.addEventListener("pointerdown", (event) => {
          event.preventDefault();
          this.onPad(this.group + key);
        });
        this.padElements[key] = pad;
        place(pad, 3 + column, keyRow);
      });
    });

    // Left column: KEYS, FADER, the fader and SHIFT.
    place(element("div", "ko-flat", "KEYS"), 1, 3);
    place(element("div", "ko-flat", "FADER"), 1, 5);
    const fader = element("div", "ko-fader");
    fader.append(element("span", "ko-fader-cap"));
    place(fader, 1, 7);
    place(element("div", "ko-flat light", "SHIFT"), 1, 9);

    // Right columns: SAMPLE/CHOP, TIMING/CORRECT, FX/OUTPUT, ERASE/SYSTEM, − +, RECORD PLAY.
    place(splitKey("SAMPLE", "CHOP", "sample"), 6, 3);
    place(splitKey("TIMING", "CORRECT"), 7, 3);
    place(splitKey("FX", "OUTPUT"), 6, 5);
    place(splitKey("ERASE", "SYSTEM", "light"), 7, 5);
    place(this._actionKey("−", "ko-wide light", "Tempo −1", "minus"), 6, 7);
    place(this._actionKey("+", "ko-wide light", "Tempo +1", "plus"), 7, 7);
    const ledPair = place(element("div", "ko-label ko-led-pair"), "6 / span 2", 8);
    ledPair.append(led("on"), led("on"));
    place(element("div", "ko-wide orange ko-record", "RECORD"), 6, 9);
    this.playKey = place(this._actionKey("PLAY", "ko-wide grey", "Play / stop the editor pattern", "play"), 7, 9);
    return face;
  }

  _actionKey(text, className, title, action) {
    const key = element("button", className, text);
    key.type = "button";
    key.title = title;
    key.addEventListener("click", () => this.onTransport(action));
    return key;
  }

  // -- state ----------------------------------------------------------------------

  setKit(kit) {
    this.aliases = {};
    for (const pad of kit?.pads || []) {
      const ranked = [...pad.aliases].sort((a, b) => rank(a) - rank(b) || a.length - b.length);
      if (ranked.length) this.aliases[pad.pad] = ranked[0];
    }
    this._label();
  }

  selectGroup(group) {
    this.group = group;
    for (const [name, key] of Object.entries(this.groupElements)) key.classList.toggle("active", name === group);
    for (const [name, cell] of Object.entries(this.screenGroups)) cell.classList.toggle("selected", name === group);
    this._label();
    this._refreshLit();
  }

  _label() {
    for (const [key, pad] of Object.entries(this.padElements)) {
      const label = this.group + key;
      pad.querySelector(".ko-pad-alias").textContent = this.aliases[label] || "";
      pad.title = `${label} · note ${padToNote(label)}` + (this.aliases[label] ? ` · ${this.aliases[label]}` : "");
    }
  }

  _refreshLit() {
    for (const [key, pad] of Object.entries(this.padElements)) {
      const state = this.lit.get(this.group + key);
      pad.classList.toggle("lit", Boolean(state && state.kind === "play"));
      pad.classList.toggle("pressed", Boolean(state && state.kind === "press"));
      pad.style.setProperty("--level", state ? (0.45 + 0.55 * state.velocity / 127).toFixed(2) : "0");
    }
  }

  /** kind: "play" for notes sent to the device, "press" for pads pressed on the device. */
  noteOn(note, velocity, kind = "play") {
    const pad = noteToPad(note);
    if (!pad) return;
    this.lit.set(pad.label, { velocity, kind, since: performance.now() });
    if (pad.group === this.group) this._refreshLit();
    this.levels[pad.group] = Math.max(this.levels[pad.group], velocity / 127);
    for (const indicator of [this.groupLeds[pad.group], this.screenGroups[pad.group]]) {
      indicator.classList.remove("blink");
      void indicator.offsetWidth; // restart the animation
      indicator.classList.add("blink");
    }
    this.knobX.style.setProperty("--turn", `${-135 + (velocity / 127) * 270}deg`);
    const alias = this.aliases[pad.label];
    this.subText.textContent = `${pad.label}${alias ? " " + alias : ""} ${velocity}`;
  }

  noteOff(note) {
    const pad = noteToPad(note);
    if (!pad) return;
    const state = this.lit.get(pad.label);
    const wait = state ? Math.max(0, MIN_LIT_MS - (performance.now() - state.since)) : 0;
    setTimeout(() => {
      if (this.lit.get(pad.label) === state) {
        this.lit.delete(pad.label);
        if (pad.group === this.group) this._refreshLit();
      }
    }, wait);
  }

  /** A pitched note on a MIDI channel: no pad lights, but it shows on screen and turns knob Y. */
  pitchedNote(name, channel, velocity = 100) {
    this.knobY.style.setProperty("--turn", `${-135 + ((channel * 37 + name.length * 23) % 270)}deg`);
    this.subText.textContent = `ch${channel} ${name}`;
    this.levels.B = Math.max(this.levels.B, velocity / 127);
  }

  setCounter(text) {
    if (this.counter.textContent !== text) this.counter.textContent = text;
  }

  setPlaying(playing, mode) {
    this.playIcon.classList.toggle("on", playing);
    this.playKey.classList.toggle("on", playing);
    this.modeTag.textContent = mode || (playing ? "PLAY" : "MAIN");
  }

  setBpm(bpm) {
    this.bpmText.textContent = bpm ? `BPM ${bpm}` : "BPM ---";
  }

  setSub(text) {
    this.subText.textContent = text;
  }

  /** Called every animation frame: lets the level meters fall back. */
  tick() {
    const now = performance.now();
    const fall = ((now - this.lastTick) / 1000) * METER_DECAY_PER_SECOND;
    this.lastTick = now;
    for (const group of GROUPS) {
      this.levels[group] = Math.max(0, this.levels[group] - fall);
      const lit = Math.round(this.levels[group] * METER_SEGMENTS);
      this.meters[group].forEach((segment, i) => segment.classList.toggle("on", METER_SEGMENTS - i <= lit));
    }
  }

  clear() {
    this.lit.clear();
    this._refreshLit();
  }
}

function rank(alias) {
  const index = ALIAS_PREFERENCE.indexOf(alias);
  return index === -1 ? ALIAS_PREFERENCE.length : index;
}

// -- A small piano strip for notes played on MIDI channels ----------------------

const WHITE = [0, 2, 4, 5, 7, 9, 11];
const NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];

export function noteName(note) {
  return `${NOTE_NAMES[note % 12]}${Math.floor(note / 12) - 1}`;
}

export class Keys {
  constructor(container, { low = 12, high = 71 } = {}) {
    this.keys = new Map();
    const strip = element("div", "keys");
    const whiteCount = [...Array(high - low + 1).keys()].filter((i) => WHITE.includes((low + i) % 12)).length;
    let whiteIndex = 0;
    for (let note = low; note <= high; note++) {
      const isWhite = WHITE.includes(note % 12);
      const key = element("div", isWhite ? "key white" : "key black");
      key.title = noteName(note);
      if (isWhite) {
        key.style.left = `${(whiteIndex / whiteCount) * 100}%`;
        key.style.width = `${100 / whiteCount}%`;
        if (note % 12 === 0) key.append(element("span", "key-label", noteName(note)));
        whiteIndex++;
      } else {
        key.style.left = `${(whiteIndex / whiteCount) * 100 - 35 / whiteCount}%`;
        key.style.width = `${70 / whiteCount}%`;
      }
      this.keys.set(note, key);
      strip.append(key);
    }
    container.append(strip);
  }

  noteOn(note) {
    this.keys.get(note)?.classList.add("on");
  }

  noteOff(note) {
    const key = this.keys.get(note);
    if (key) setTimeout(() => key.classList.remove("on"), MIN_LIT_MS);
  }
}
