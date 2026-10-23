// Sound design: build drum hits and short tonal sounds from a few layers
// (pitched body, filtered noise, click), render them at the EP-133's own rate
// (46,875 Hz, mono, 16-bit), preview them here, and upload them to an empty
// slot on the device. An audio file can be loaded and converted the same way.

import { command } from "./api.js";

export const DEVICE_RATE = 46875;
const NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];

// name, label, min, max, scale ("lin" or "log"), unit, decimals
const PARAMETERS = [
  ["group", "body"],
  ["body", "level", 0, 1, "lin", "", 2],
  ["pitch", "pitch", 20, 2000, "log", "Hz", 0],
  ["drop", "pitch drop", 1, 12, "lin", "×", 1],
  ["dropTime", "drop time", 1, 500, "log", "ms", 0],
  ["group", "noise"],
  ["noise", "level", 0, 1, "lin", "", 2],
  ["noiseCutoff", "filter", 100, 16000, "log", "Hz", 0],
  ["noiseQ", "focus", 0.1, 10, "log", "", 1],
  ["group", "tone filter"],
  ["cutoff", "start", 50, 18000, "log", "Hz", 0],
  ["cutoffEnd", "end", 50, 18000, "log", "Hz", 0],
  ["filterTime", "sweep", 5, 2000, "log", "ms", 0],
  ["resonance", "resonance", 0.1, 15, "log", "", 1],
  ["group", "envelope"],
  ["attack", "attack", 0, 200, "lin", "ms", 0],
  ["decay", "decay", 10, 3000, "log", "ms", 0],
  ["length", "length", 0.05, 4, "log", "s", 2],
  ["group", "character"],
  ["drive", "drive", 0, 1, "lin", "", 2],
  ["click", "click", 0, 1, "lin", "", 2],
  ["bursts", "bursts", 1, 5, "lin", "", 0],
];

const CHOICES = {
  wave: ["sine", "triangle", "sawtooth", "square"],
  noiseType: ["highpass", "bandpass", "lowpass"],
};

const BASE = { body: 1, wave: "sine", pitch: 55, drop: 1, dropTime: 40, noise: 0, noiseType: "bandpass", noiseCutoff: 2000,
               noiseQ: 0.8, cutoff: 16000, cutoffEnd: 16000, filterTime: 200, resonance: 0.7, attack: 1, decay: 200,
               length: 0.5, drive: 0, click: 0, bursts: 1 };

export const PRESETS = {
  kick: { ...BASE, pitch: 48, drop: 4, dropTime: 45, decay: 220, length: 0.55, drive: 0.25, click: 0.3, noise: 0.04, noiseCutoff: 5000 },
  snare: { ...BASE, wave: "triangle", pitch: 190, drop: 1.5, dropTime: 30, body: 0.6, noise: 0.85, noiseCutoff: 2200, noiseQ: 0.7, decay: 160, length: 0.35, click: 0.2 },
  hat: { ...BASE, body: 0, noise: 1, noiseType: "highpass", noiseCutoff: 7500, noiseQ: 0.7, decay: 45, length: 0.15 },
  openhat: { ...BASE, body: 0, noise: 1, noiseType: "highpass", noiseCutoff: 6500, noiseQ: 0.7, decay: 320, length: 0.7 },
  clap: { ...BASE, body: 0, noise: 1, noiseType: "bandpass", noiseCutoff: 1300, noiseQ: 1.3, decay: 140, length: 0.4, bursts: 3 },
  tom: { ...BASE, pitch: 110, drop: 1.8, dropTime: 70, decay: 300, length: 0.6, click: 0.15, noise: 0.06 },
  bass: { ...BASE, wave: "sawtooth", pitch: 55, cutoff: 1400, cutoffEnd: 180, filterTime: 260, resonance: 4, attack: 2, decay: 650, length: 0.9, drive: 0.3 },
  pluck: { ...BASE, wave: "triangle", pitch: 220, cutoff: 4000, cutoffEnd: 350, filterTime: 280, resonance: 2, decay: 380, length: 0.7 },
  zap: { ...BASE, pitch: 60, drop: 12, dropTime: 160, decay: 220, length: 0.35, drive: 0.15 },
};

function noteName(hz) {
  const midi = Math.round(69 + 12 * Math.log2(hz / 440));
  return `${NOTE_NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

function toSlider(spec, value) {
  const [, , min, max, scale] = spec;
  return scale === "log" ? Math.log(value / min) / Math.log(max / min) : (value - min) / (max - min);
}

function fromSlider(spec, position) {
  const [, , min, max, scale, , decimals] = spec;
  const value = scale === "log" ? min * (max / min) ** position : min + (max - min) * position;
  return Number(value.toFixed(decimals));
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Render a set of parameters to a mono AudioBuffer at the device's rate, peak-normalised to −1 dBFS. */
export async function renderSound(p) {
  const frames = Math.max(1, Math.round(p.length * DEVICE_RATE));
  const context = new OfflineAudioContext(1, frames, DEVICE_RATE);
  const end = p.length;
  const attack = Math.max(0.0005, p.attack / 1000);
  const decay = p.decay / 1000;

  const amp = context.createGain();
  amp.gain.setValueAtTime(0, 0);
  amp.gain.linearRampToValueAtTime(1, attack);
  amp.gain.setTargetAtTime(0, attack, decay / 3);

  const tone = context.createBiquadFilter();
  tone.type = "lowpass";
  tone.Q.value = p.resonance;
  tone.frequency.setValueAtTime(Math.min(p.cutoff, DEVICE_RATE / 2 - 100), 0);
  tone.frequency.exponentialRampToValueAtTime(Math.min(p.cutoffEnd, DEVICE_RATE / 2 - 100), p.filterTime / 1000);

  const shaper = context.createWaveShaper();
  const curve = new Float32Array(1024);
  const k = 1 + p.drive * 8; // gentle by default; full drive is a hard, square-ish clip
  for (let i = 0; i < curve.length; i++) {
    const x = (i / (curve.length - 1)) * 2 - 1;
    curve[i] = Math.tanh(k * x) / Math.tanh(k);
  }
  shaper.curve = curve;
  tone.connect(shaper).connect(amp).connect(context.destination);

  if (p.body > 0) {
    const oscillator = context.createOscillator();
    oscillator.type = p.wave;
    oscillator.frequency.setValueAtTime(p.pitch * p.drop, 0);
    oscillator.frequency.exponentialRampToValueAtTime(p.pitch, Math.max(0.001, p.dropTime / 1000));
    const level = context.createGain();
    level.gain.value = p.body;
    oscillator.connect(level).connect(tone);
    oscillator.start(0);
    oscillator.stop(end);
  }

  const noiseBuffer = context.createBuffer(1, frames, DEVICE_RATE);
  const data = noiseBuffer.getChannelData(0);
  for (let i = 0; i < frames; i++) data[i] = Math.random() * 2 - 1;

  if (p.noise > 0) {
    const source = context.createBufferSource();
    source.buffer = noiseBuffer;
    const filter = context.createBiquadFilter();
    filter.type = p.noiseType;
    filter.frequency.value = Math.min(p.noiseCutoff, DEVICE_RATE / 2 - 100);
    filter.Q.value = p.noiseQ;
    const level = context.createGain();
    // Claps: several short bursts before the tail.
    const bursts = Math.max(1, Math.round(p.bursts));
    level.gain.setValueAtTime(0, 0);
    for (let b = 0; b < bursts - 1; b++) {
      level.gain.setValueAtTime(p.noise, b * 0.011);
      level.gain.setTargetAtTime(0.05 * p.noise, b * 0.011 + 0.002, 0.003);
    }
    level.gain.setValueAtTime(p.noise, (bursts - 1) * 0.011);
    source.connect(filter).connect(level).connect(tone);
    source.start(0);
  }

  if (p.click > 0) {
    const source = context.createBufferSource();
    source.buffer = noiseBuffer;
    const filter = context.createBiquadFilter();
    filter.type = "highpass";
    filter.frequency.value = 3000;
    const level = context.createGain();
    level.gain.setValueAtTime(p.click, 0);
    level.gain.exponentialRampToValueAtTime(0.0001, 0.006);
    source.connect(filter).connect(level).connect(amp);
    source.start(0);
    source.stop(0.01);
  }

  const buffer = await context.startRendering();
  normalise(buffer);
  return buffer;
}

function normalise(buffer, target = 10 ** (-1 / 20)) {
  let peak = 0;
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    for (const value of buffer.getChannelData(c)) peak = Math.max(peak, Math.abs(value));
  }
  if (peak < 1e-6) return;
  const gain = target / peak;
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const channel = buffer.getChannelData(c);
    for (let i = 0; i < channel.length; i++) channel[i] *= gain;
  }
}

/** Decode any audio file the browser understands and convert it to the device's rate (mono or stereo). */
export async function convertFile(file, keepStereo) {
  const decoded = await new OfflineAudioContext(1, 1, 44100).decodeAudioData(await file.arrayBuffer());
  const channels = keepStereo && decoded.numberOfChannels > 1 ? 2 : 1;
  const frames = Math.ceil(decoded.duration * DEVICE_RATE);
  const context = new OfflineAudioContext(channels, frames, DEVICE_RATE);
  const source = context.createBufferSource();
  source.buffer = decoded;
  source.connect(context.destination);
  source.start(0);
  const buffer = await context.startRendering();
  normalise(buffer);
  return buffer;
}

/** AudioBuffer -> 16-bit little-endian interleaved PCM, base64-encoded for the upload request. */
export function toPcmBase64(buffer) {
  const channels = buffer.numberOfChannels;
  const view = new DataView(new ArrayBuffer(buffer.length * channels * 2));
  const data = Array.from({ length: channels }, (_, c) => buffer.getChannelData(c));
  for (let i = 0; i < buffer.length; i++) {
    for (let c = 0; c < channels; c++) {
      const value = Math.max(-1, Math.min(1, data[c][i]));
      view.setInt16((i * channels + c) * 2, Math.round(value * 32767), true);
    }
  }
  const bytes = new Uint8Array(view.buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

export class SoundDesigner {
  constructor(elements, { toast, onUploaded, suggestSlot }) {
    this.elements = elements;
    this.toast = toast;
    this.onUploaded = onUploaded;
    this.suggestSlot = suggestSlot;
    this.params = { ...PRESETS.kick };
    this.preset = "kick";
    this.buffer = null;
    this.source = "design";
    this.sliders = {};
    this._build();
    this._renderSoon();
  }

  _build() {
    const { presets, controls, preview, upload, file, randomise } = this.elements;
    for (const name of Object.keys(PRESETS)) {
      const button = element("button", "brush", name);
      button.type = "button";
      button.addEventListener("click", () => this.usePreset(name));
      button.dataset.preset = name;
      presets.append(button);
    }
    let group = null;
    for (const spec of PARAMETERS) {
      if (spec[0] === "group") {
        group = element("fieldset", "param-group");
        group.append(element("legend", "", spec[1]));
        if (spec[1] === "body") group.append(this._choice("wave"));
        if (spec[1] === "noise") group.append(this._choice("noiseType"));
        controls.append(group);
        continue;
      }
      const [name, label] = spec;
      const row = element("label", "param");
      const input = element("input");
      input.type = "range";
      input.min = 0;
      input.max = 1000;
      const readout = element("span", "param-value num");
      input.addEventListener("input", () => {
        this.params[name] = fromSlider(spec, input.value / 1000);
        this._showValue(spec, readout);
        this.source = "design";
        this._renderSoon();
      });
      row.append(element("span", "param-name", label), input, readout);
      this.sliders[name] = { input, readout, spec };
      group.append(row);
    }
    preview.addEventListener("click", () => this.preview());
    upload.addEventListener("click", () => this.upload());
    randomise.addEventListener("click", () => this.randomise());
    file.addEventListener("change", () => file.files[0] && this.loadFile(file.files[0]));
    new ResizeObserver(() => this._draw()).observe(this.elements.wave);
    this._sync();
  }

  _choice(name) {
    const select = element("select", "param-choice");
    for (const option of CHOICES[name]) {
      const node = element("option", "", option);
      node.value = option;
      select.append(node);
    }
    select.addEventListener("change", () => {
      this.params[name] = select.value;
      this.source = "design";
      this._renderSoon();
    });
    this.sliders[name] = { select };
    return select;
  }

  _showValue(spec, readout) {
    const [name, , , , , unit, decimals] = spec;
    const value = this.params[name];
    readout.textContent = `${value.toFixed(decimals)}${unit ? ` ${unit}` : ""}${name === "pitch" ? ` · ${noteName(value)}` : ""}`;
  }

  _sync() {
    for (const [name, control] of Object.entries(this.sliders)) {
      if (control.select) control.select.value = this.params[name];
      else {
        control.input.value = Math.round(toSlider(control.spec, this.params[name]) * 1000);
        this._showValue(control.spec, control.readout);
      }
    }
    for (const button of this.elements.presets.querySelectorAll("button")) {
      button.classList.toggle("active", button.dataset.preset === this.preset);
    }
    if (!this.elements.name.value || this.elements.name.dataset.auto === "true") {
      this.elements.name.value = `koii ${this.preset}`;
      this.elements.name.dataset.auto = "true";
    }
  }

  usePreset(name) {
    this.preset = name;
    this.params = { ...PRESETS[name] };
    this.source = "design";
    this._sync();
    this._renderSoon();
  }

  randomise() {
    // Nudge every continuous parameter of the current preset by up to ±25% of its range.
    const base = PRESETS[this.preset];
    for (const spec of PARAMETERS) {
      if (spec[0] === "group" || spec[0] === "bursts") continue;
      const position = toSlider(spec, base[spec[0]]) + (Math.random() - 0.5) * 0.5;
      this.params[spec[0]] = fromSlider(spec, Math.min(1, Math.max(0, position)));
    }
    this.source = "design";
    this._sync();
    this._renderSoon();
  }

  async loadFile(file) {
    try {
      this.buffer = await convertFile(file, this.elements.stereo.checked);
      this.source = "file";
      this.elements.name.value = file.name.replace(/\.[^.]+$/, "").slice(0, 20);
      this.elements.name.dataset.auto = "false";
      this._draw();
    } catch (error) {
      this.toast(`Couldn't read that file: ${error.message}`, true);
    }
  }

  _renderSoon() {
    clearTimeout(this.renderTimer);
    this.renderTimer = setTimeout(async () => {
      if (this.source !== "design") return;
      this.buffer = await renderSound(this.params);
      this._draw();
    }, 60);
  }

  _draw() {
    const canvas = this.elements.wave;
    const ratio = window.devicePixelRatio || 1;
    const { width, height } = canvas.getBoundingClientRect();
    if (!width) return;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const context = canvas.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.fillStyle = "#0e0d0f";
    context.fillRect(0, 0, width, height);
    context.fillStyle = "rgba(240, 233, 216, 0.08)";
    context.fillRect(0, height / 2, width, 1);
    const buffer = this.buffer;
    if (!buffer) return;
    const data = buffer.getChannelData(0);
    const perPixel = Math.max(1, Math.floor(data.length / width));
    context.fillStyle = "#ff5a1f";
    for (let x = 0; x < width; x++) {
      let low = 1;
      let high = -1;
      for (let i = x * perPixel; i < Math.min(data.length, (x + 1) * perPixel); i++) {
        if (data[i] < low) low = data[i];
        if (data[i] > high) high = data[i];
      }
      if (high < low) continue;
      const top = height / 2 - high * (height / 2 - 4);
      context.fillRect(x, top, 1, Math.max(1, height / 2 - low * (height / 2 - 4) - top));
    }
    const kb = (buffer.length * buffer.numberOfChannels * 2) / 1024;
    this.elements.readout.textContent =
      `${buffer.duration.toFixed(3)} s · ${buffer.numberOfChannels === 2 ? "stereo" : "mono"} · ${DEVICE_RATE} Hz · ${kb.toFixed(1)} KB`;
  }

  preview() {
    if (!this.buffer) return;
    this.previewContext ||= new AudioContext();
    const source = this.previewContext.createBufferSource();
    source.buffer = this.buffer;
    source.connect(this.previewContext.destination);
    this.previewContext.resume();
    source.start();
  }

  async upload() {
    if (!this.buffer) return;
    const slotInput = this.elements.slot;
    let slot = Number(slotInput.value);
    if (!slot) {
      slot = await this.suggestSlot();
      slotInput.value = slot;
    }
    const name = this.elements.name.value.trim() || `koii ${this.preset}`;
    if (!confirm(`Upload “${name}” (${this.buffer.duration.toFixed(2)} s) to slot ${slot} on the EP-133?\n\n` +
                 "koii only writes to empty slots (or ones it uploaded itself) and checks the result against the device's checksum.")) return;
    const button = this.elements.upload;
    button.disabled = true;
    button.textContent = "uploading…";
    try {
      const result = await command("upload_sample", {
        slot, name, channels: this.buffer.numberOfChannels, pcm: toPcmBase64(this.buffer),
      });
      this.toast(result.message);
      slotInput.value = "";
      this.onUploaded(result);
    } catch (error) {
      this.toast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "⤒ upload to device";
    }
  }
}
