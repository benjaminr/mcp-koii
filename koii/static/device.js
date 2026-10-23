// An on-screen EP-133 K.O. II: group buttons, the 12 pads, the display and the
// two knobs. Pads light up for every note sent to the device and for pads
// pressed on the real device.

const PAD_GRID = [["7", "8", "9"], ["4", "5", "6"], ["1", "2", "3"], [".", "0", "Enter"]];
const PAD_KEYS = [".", "0", "Enter", "1", "2", "3", "4", "5", "6", "7", "8", "9"];
const GROUP_BASE = { A: 36, B: 48, C: 60, D: 72 };
const MIN_LIT_MS = 90;
// Which alias to show on a pad when several point at it.
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

export class Device {
  constructor(container, { onPad, onTransport }) {
    this.group = "A";
    this.aliases = {};            // pad label -> name shown on the pad
    this.lit = new Map();         // pad label -> { velocity, kind, since }
    this.padElements = {};        // key -> element
    this.groupElements = {};
    this.knobAngle = { x: -40, y: 40 };
    this.onPad = onPad;
    container.append(this._build(onTransport));
  }

  _build(onTransport) {
    const ko = element("div", "ko");

    const top = element("div", "ko-top");
    const speaker = element("div", "ko-speaker");
    for (let i = 0; i < 48; i++) speaker.append(element("span"));
    const screen = element("div", "ko-screen");
    this.screenMain = element("div", "ko-screen-main", "KO II");
    this.screenSub = element("div", "ko-screen-sub", "ready");
    screen.append(this.screenMain, this.screenSub);
    const knobs = element("div", "ko-knobs");
    this.knobs = {};
    for (const name of ["x", "y"]) {
      const knob = element("div", "ko-knob");
      const dial = element("div", "ko-knob-dial");
      knob.append(dial, element("span", "ko-knob-label", name.toUpperCase()));
      this.knobs[name] = dial;
      knobs.append(knob);
    }
    top.append(speaker, screen, knobs);

    const body = element("div", "ko-body");
    const groups = element("div", "ko-groups");
    for (const group of Object.keys(GROUP_BASE)) {
      const button = element("button", "ko-group");
      button.type = "button";
      button.append(element("span", "ko-led"), element("span", "ko-group-name", group));
      button.title = `Show group ${group} (notes ${GROUP_BASE[group]}–${GROUP_BASE[group] + 11})`;
      button.addEventListener("click", () => this.selectGroup(group));
      this.groupElements[group] = button;
      groups.append(button);
    }
    const pads = element("div", "ko-pads");
    for (const row of PAD_GRID) {
      for (const key of row) {
        const pad = element("button", "ko-pad");
        pad.type = "button";
        pad.append(element("span", "ko-pad-key", key === "Enter" ? "ENTER" : key), element("span", "ko-pad-alias"));
        pad.addEventListener("pointerdown", (event) => {
          event.preventDefault();
          this.onPad(this.group + key);
        });
        this.padElements[key] = pad;
        pads.append(pad);
      }
    }
    body.append(groups, pads);

    const transport = element("div", "ko-transport");
    for (const [action, label] of [["play", "▶"], ["stop", "■"]]) {
      const button = element("button", `ko-button ko-${action}`, label);
      button.type = "button";
      button.title = action === "play" ? "Play the editor pattern" : "Stop";
      button.addEventListener("click", () => onTransport(action));
      transport.append(button);
    }
    const brand = element("div", "ko-brand");
    brand.innerHTML = "<b>K.O. II</b> EP–133";
    transport.append(brand);

    ko.append(top, body, transport);
    this.selectGroup("A");
    return ko;
  }

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
    for (const [name, button] of Object.entries(this.groupElements)) button.classList.toggle("active", name === group);
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
      pad.style.setProperty("--level", state ? (0.35 + 0.65 * state.velocity / 127).toFixed(2) : "0");
    }
  }

  /** kind: "play" for notes sent to the device, "press" for pads pressed on the device. */
  noteOn(note, velocity, kind = "play") {
    const pad = noteToPad(note);
    if (!pad) return;
    this.lit.set(pad.label, { velocity, kind, since: performance.now() });
    if (pad.group === this.group) this._refreshLit();
    const led = this.groupElements[pad.group];
    led.classList.remove("blink");
    void led.offsetWidth; // restart the animation
    led.classList.add("blink");
    this.knobAngle.x = -135 + (velocity / 127) * 270;
    this.knobs.x.style.transform = `rotate(${this.knobAngle.x}deg)`;
    const alias = this.aliases[pad.label];
    this.screenSub.textContent = `${pad.label}${alias ? " " + alias : ""} · ${velocity}`;
  }

  noteOff(note) {
    const pad = noteToPad(note);
    if (!pad) return;
    const state = this.lit.get(pad.label);
    const wait = state ? Math.max(0, MIN_LIT_MS - (performance.now() - state.since)) : 0;
    setTimeout(() => {
      const current = this.lit.get(pad.label);
      if (current === state) {
        this.lit.delete(pad.label);
        if (pad.group === this.group) this._refreshLit();
      }
    }, wait);
  }

  /** A pitched note on a MIDI channel: no pad, but turn knob Y and show it. */
  pitchedNote(name, channel) {
    this.knobAngle.y = (this.knobAngle.y + 47) % 270 - 135;
    this.knobs.y.style.transform = `rotate(${this.knobAngle.y}deg)`;
    this.screenSub.textContent = `ch${channel} ${name}`;
  }

  setScreen(main, sub) {
    this.screenMain.textContent = main;
    if (sub !== undefined) this.screenSub.textContent = sub;
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
