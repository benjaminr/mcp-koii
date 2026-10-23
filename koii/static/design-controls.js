// Controls for a sound design, built from the server's schema: a stack of
// layers (engine, pitch, envelopes, filter, LFOs), an effects rack and the
// instrument settings the device stores. Changing a value edits the design in
// place and calls onChange; adding, removing or reordering rebuilds the cards.

const NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];

export function noteName(midi) {
  return `${NOTE_NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

export function hzToNote(hz) {
  return noteName(Math.round(69 + 12 * Math.log2(hz / 440)));
}

export function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/**
 * Two presses to do something that writes to the device: the first press changes the
 * button's label to a question; a second press within a few seconds goes ahead.
 * Returns true when this press should go ahead.
 */
export function pressedTwice(button, question, seconds = 5) {
  if (button.classList.contains("confirming")) {
    clearTimeout(button.confirmTimer);
    button.classList.remove("confirming");
    button.textContent = button.dataset.label;
    return true;
  }
  button.dataset.label = button.textContent;
  button.textContent = question;
  button.classList.add("confirming");
  button.confirmTimer = setTimeout(() => {
    button.classList.remove("confirming");
    button.textContent = button.dataset.label;
  }, seconds * 1000);
  return false;
}

// -- one parameter ------------------------------------------------------------------------

// Log sliders need a positive lower end; ranges that start at 0 (attack, hold) use log(1 + x).
function toPosition(spec, value) {
  if (spec.scale === "log" && spec.low > 0) return Math.log(value / spec.low) / Math.log(spec.high / spec.low);
  if (spec.scale === "log") return Math.log1p(value) / Math.log1p(spec.high);
  return (value - spec.low) / (spec.high - spec.low);
}

function fromPosition(spec, position) {
  let value;
  if (spec.scale === "log" && spec.low > 0) value = spec.low * (spec.high / spec.low) ** position;
  else if (spec.scale === "log") value = Math.expm1(position * Math.log1p(spec.high));
  else value = spec.low + position * (spec.high - spec.low);
  return Number(Math.min(spec.high, Math.max(spec.low, value)).toFixed(spec.decimals));
}

function formatValue(spec, value) {
  const text = Number(value).toFixed(spec.decimals);
  const unit = spec.unit ? ` ${spec.unit}` : "";
  return spec.name === "pitch" && spec.unit === "Hz" ? `${text}${unit} · ${hzToNote(value)}` : `${text}${unit}`;
}

/** A labelled slider or select bound to target[spec.name]. */
export function control(spec, target, onChange) {
  const row = element("label", "param");
  if (spec.help) row.title = spec.help;
  row.append(element("span", "param-name", spec.label));
  if (spec.scale === "choice") {
    const select = element("select", "param-choice");
    for (const choice of spec.choices) {
      const option = element("option", "", choice);
      option.value = choice;
      select.append(option);
    }
    select.value = target[spec.name];
    select.addEventListener("change", () => {
      target[spec.name] = select.value;
      onChange({ structural: false });
    });
    row.append(select, element("span", "param-value"));
    row.classList.add("choice");
    return row;
  }
  const input = element("input");
  input.type = "range";
  input.min = 0;
  input.max = 1000;
  input.value = Math.round(toPosition(spec, target[spec.name]) * 1000);
  const readout = element("span", "param-value num", formatValue(spec, target[spec.name]));
  input.addEventListener("input", () => {
    target[spec.name] = fromPosition(spec, input.value / 1000);
    readout.textContent = formatValue(spec, target[spec.name]);
    onChange({ structural: false });
  });
  // Double-click the value to type an exact one (Enter keeps it, Escape doesn't).
  readout.title = `double-click to type a value (${spec.low}–${spec.high}${spec.unit ? ` ${spec.unit}` : ""})`;
  readout.addEventListener("dblclick", (event) => {
    event.preventDefault();
    const field = element("input", "param-exact num");
    field.type = "number";
    field.step = "any";
    field.value = target[spec.name];
    readout.replaceWith(field);
    field.focus();
    field.select();
    const finish = (keep) => {
      const typed = Number(field.value);
      if (keep && field.value !== "" && Number.isFinite(typed)) {
        target[spec.name] = Math.min(spec.high, Math.max(spec.low, typed));
        input.value = Math.round(toPosition(spec, target[spec.name]) * 1000);
        onChange({ structural: false });
      }
      readout.textContent = formatValue(spec, target[spec.name]);
      field.replaceWith(readout);
    };
    field.addEventListener("keydown", (key) => {
      if (key.key === "Enter") finish(true);
      if (key.key === "Escape") finish(false);
    });
    field.addEventListener("blur", () => field.isConnected && finish(true));
  });
  row.append(input, readout);
  return row;
}

/**
 * A titled group of controls. Clicking the title folds it; `folded` is a Set of keys
 * remembered across rebuilds, and `foldedAtFirst` says whether it starts folded.
 */
function group(title, specs, target, onChange, { skip = [], key, folded, foldedAtFirst = false } = {}) {
  const box = element("fieldset", "param-group");
  const legend = element("legend", "fold", title);
  box.append(legend);
  if (key && folded && foldedAtFirst && !folded.has(`seen:${key}`)) folded.add(key);
  if (key && folded) folded.add(`seen:${key}`);
  const isFolded = key && folded?.has(key);
  box.classList.toggle("folded", Boolean(isFolded));
  if (key && folded) {
    legend.title = "show or hide";
    legend.addEventListener("click", () => {
      if (folded.has(key)) folded.delete(key);
      else folded.add(key);
      box.classList.toggle("folded");
    });
  }
  for (const spec of specs) {
    if (!skip.includes(spec.name)) box.append(control(spec, target, onChange));
  }
  return box;
}

function smallButton(label, title, onClick) {
  const button = element("button", "btn small ghost", label);
  button.type = "button";
  button.title = title;
  button.addEventListener("click", onClick);
  return button;
}

function defaultsOf(specs) {
  return Object.fromEntries(specs.map((spec) => [spec.name, spec.default]));
}

// -- the whole design ------------------------------------------------------------------------

export class DesignControls {
  constructor(container, { onChange, onAudition }) {
    this.container = container;
    this.onChange = onChange;
    this.onAudition = onAudition;
    this.schema = null;
    this.design = null;
    this.collapsed = new Set();
  }

  show(schema, design) {
    this.schema = schema;
    this.design = design;
    this.collapsed = new Set();   // a different sound: fold afresh
    this.build();
  }

  changed(details) {
    if (details.structural) this.build();
    this.onChange(this.design, details);
  }

  build() {
    const { schema, design } = this;
    const change = (details) => this.changed(details);
    this.container.replaceChildren();

    const layers = element("div", "design-column");
    layers.append(element("h3", "design-column-head", "layers"));
    design.layers.forEach((layer, index) => layers.append(this.layerCard(layer, index)));
    if (design.layers.length < schema.max_layers) layers.append(this.adder("+ layer", Object.keys(schema.engines),
      (engine) => {
        design.layers.push(this.newLayer(engine));
        change({ structural: true });
      }, (engine) => schema.engines[engine].label));

    const rack = element("div", "design-column");
    rack.append(element("h3", "design-column-head", "effects · in order"));
    design.effects.forEach((effect, index) => rack.append(this.effectCard(effect, index)));
    rack.append(this.adder("+ effect", Object.keys(schema.effects), (kind) => {
      design.effects.push({ type: kind, ...defaultsOf(schema.effects[kind].params) });
      change({ structural: true });
    }, (kind) => schema.effects[kind].label));

    rack.append(this.soundCard(), this.instrumentCard());
    this.container.append(layers, rack);
  }

  newLayer(engine) {
    const { schema } = this;
    return {
      engine, ...defaultsOf(schema.layer), params: defaultsOf(schema.engines[engine].params),
      amp: defaultsOf(schema.amp), pitch_env: defaultsOf(schema.pitch_env), filter: defaultsOf(schema.filter), lfos: [],
    };
  }

  adder(label, options, onPick, describe) {
    const select = element("select", "adder");
    const placeholder = element("option", "", label);
    placeholder.value = "";
    select.append(placeholder);
    for (const option of options) {
      const node = element("option", "", describe(option));
      node.value = option;
      select.append(node);
    }
    select.addEventListener("change", () => {
      if (select.value) onPick(select.value);
      select.value = "";
    });
    return select;
  }

  cardHead(title, key, actions) {
    const head = element("div", "card-head");
    const toggle = element("button", "card-toggle", `${this.collapsed.has(key) ? "▸" : "▾"} ${title}`);
    toggle.type = "button";
    toggle.addEventListener("click", () => {
      if (this.collapsed.has(key)) this.collapsed.delete(key);
      else this.collapsed.add(key);
      this.build();
    });
    head.append(toggle, ...actions);
    return head;
  }

  move(list, index, delta) {
    const other = index + delta;
    if (other < 0 || other >= list.length) return;
    [list[index], list[other]] = [list[other], list[index]];
    this.changed({ structural: true });
  }

  layerCard(layer, index) {
    const { schema, design } = this;
    const change = (details) => this.changed(details);
    const key = `layer-${index}`;
    const card = element("section", "design-card layer-card");
    const engine = schema.engines[layer.engine];
    card.append(this.cardHead(`${index + 1} · ${engine.label}`, key, [
      smallButton("solo", "Hear this layer on its own", () => this.onAudition({ layer: index })),
      smallButton("↑", "Move up", () => this.move(design.layers, index, -1)),
      smallButton("↓", "Move down", () => this.move(design.layers, index, 1)),
      smallButton("⧉", "Duplicate", () => {
        if (design.layers.length >= schema.max_layers) return;
        design.layers.splice(index + 1, 0, structuredClone(layer));
        change({ structural: true });
      }),
      smallButton("✕", "Remove", () => {
        if (design.layers.length === 1) return;
        design.layers.splice(index, 1);
        change({ structural: true });
      }),
    ]));
    if (this.collapsed.has(key)) return card;
    const body = element("div", "card-body");
    const engineSelect = this.adder(`engine: ${layer.engine}`, Object.keys(schema.engines), (name) => {
      Object.assign(layer, { engine: name, params: defaultsOf(schema.engines[name].params) });
      change({ structural: true });
    }, (name) => schema.engines[name].label);
    engineSelect.title = engine.help;
    body.append(engineSelect);
    if (layer.engine === "sample") body.append(this.sourcePicker(layer));
    const fold = (name, foldedAtFirst = false) => ({ key: `${key}-${name}`, folded: this.collapsed, foldedAtFirst });
    body.append(group("sound", engine.params, layer.params, change, { skip: ["source"], ...fold("sound") }));
    body.append(group("level · pitch", schema.layer, layer, change, fold("level")));
    body.append(group("amp envelope", schema.amp, layer.amp, change, fold("amp")));
    // Parts that aren't doing anything start folded, to keep the stack short.
    body.append(group("pitch envelope", schema.pitch_env, layer.pitch_env, change,
                      fold("pitch", layer.pitch_env.amount === 0)));
    body.append(group("filter", schema.filter, layer.filter, change, fold("filter", layer.filter.type === "off")));
    layer.lfos.forEach((lfo, lfoIndex) => {
      const box = group(`lfo ${lfoIndex + 1}`, schema.lfo, lfo, change, fold(`lfo${lfoIndex}`));
      box.querySelector("legend").append(" ", smallButton("✕", "Remove LFO", () => {
        layer.lfos.splice(lfoIndex, 1);
        change({ structural: true });
      }));
      body.append(box);
    });
    if (layer.lfos.length < 3) {
      body.append(smallButton("+ lfo", "Wobble pitch, filter, level or pan", () => {
        layer.lfos.push(defaultsOf(schema.lfo));
        change({ structural: true });
      }));
    }
    card.append(body);
    return card;
  }

  sourcePicker(layer) {
    const row = element("label", "param choice");
    row.append(element("span", "param-name", "source"));
    const select = element("select", "param-choice");
    const sources = this.sources || [];
    const known = new Set();
    for (const source of sources) {
      const option = element("option", "", `${source.name} · ${source.seconds}s`);
      option.value = source.id;
      known.add(source.id);
      select.append(option);
    }
    if (layer.params.source && !known.has(layer.params.source)) {
      const option = element("option", "", layer.params.source);
      option.value = layer.params.source;
      select.append(option);
    }
    if (!select.options.length) {
      const none = element("option", "", "no sources yet: record or load one");
      none.value = "";
      select.append(none);
    }
    select.value = layer.params.source || "";
    select.addEventListener("change", () => {
      layer.params.source = select.value;
      this.changed({ structural: true });
    });
    // Or sample a sound already on the device, read from the latest backup.
    const slot = element("input", "slot-input num");
    slot.type = "number";
    slot.min = 1;
    slot.max = 999;
    slot.placeholder = "slot";
    slot.title = "Sample a device sound by slot (read from the latest backup)";
    slot.value = layer.params.source?.startsWith("slot:") ? layer.params.source.slice(5) : "";
    slot.addEventListener("change", () => {
      const number = Number(slot.value);
      if (number >= 1 && number <= 999) {
        layer.params.source = `slot:${number}`;
        this.changed({ structural: true });
      }
    });
    row.append(select, slot);
    return row;
  }

  effectCard(effect, index) {
    const { schema, design } = this;
    const change = (details) => this.changed(details);
    const key = `effect-${index}`;
    const card = element("section", "design-card effect-card");
    card.append(this.cardHead(`${index + 1} · ${schema.effects[effect.type].label}`, key, [
      smallButton("↑", "Earlier in the chain", () => this.move(design.effects, index, -1)),
      smallButton("↓", "Later in the chain", () => this.move(design.effects, index, 1)),
      smallButton("✕", "Remove", () => {
        design.effects.splice(index, 1);
        change({ structural: true });
      }),
    ]));
    if (!this.collapsed.has(key)) {
      const body = element("div", "card-body");
      for (const spec of schema.effects[effect.type].params) body.append(control(spec, effect, change));
      card.append(body);
    }
    return card;
  }

  soundCard() {
    const { schema, design } = this;
    const card = element("section", "design-card");
    card.append(this.cardHead("sample", "sample", []));
    if (this.collapsed.has("sample")) return card;
    const body = element("div", "card-body");
    for (const spec of schema.design) {
      if (spec.name === "stereo") {
        const row = element("label", "param choice");
        const box = element("input");
        box.type = "checkbox";
        box.checked = Boolean(design.stereo);
        box.addEventListener("change", () => {
          design.stereo = box.checked;
          this.changed({ structural: false });
        });
        row.append(element("span", "param-name", "stereo"), box, element("span", "param-value", "pans and width"));
        body.append(row);
      } else {
        body.append(control(spec, design, (details) => this.changed(details)));
      }
    }
    card.append(body);
    return card;
  }

  instrumentCard() {
    const { schema, design } = this;
    const change = (details) => this.changed(details);
    const card = element("section", "design-card instrument-card");
    card.append(this.cardHead("on the device", "instrument", []));
    if (this.collapsed.has("instrument")) return card;
    const body = element("div", "card-body");
    for (const spec of schema.instrument) {
      if (spec.name === "root") body.append(this.rootControl(design.instrument));
      else if ((spec.name === "bpm" || spec.name === "bars") && design.instrument.tempo !== "bpm") continue;
      // Turning tempo sync on or off shows or hides its bpm and bars.
      else body.append(control(spec, design.instrument, () => change({ structural: spec.name === "tempo" })));
    }
    card.append(body);
    return card;
  }

  rootControl(instrument) {
    const row = element("label", "param choice");
    row.title = "What the device treats as the sound's own note. 'auto' detects it.";
    row.append(element("span", "param-name", "root note"));
    const select = element("select", "param-choice");
    const options = [["auto", "auto (detect)"], ["none", "none (C4)"]];
    for (let midi = 24; midi <= 96; midi++) options.push([String(midi), noteName(midi)]);
    for (const [value, label] of options) {
      const option = element("option", "", label);
      option.value = value;
      select.append(option);
    }
    select.value = String(instrument.root);
    select.addEventListener("change", () => {
      instrument.root = /^\d+$/.test(select.value) ? Number(select.value) : select.value;
      this.changed({ structural: false });
    });
    row.append(select, element("span", "param-value"));
    return row;
  }
}
