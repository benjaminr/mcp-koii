// The designer's sample tab: record the EP-133 (or bounce a pattern played on
// it), load files, edit non-destructively (the server applies the edit chain),
// chop into slices, and send the results to the designer or the device.

import { command } from "./api.js";
import { element, pressedTwice } from "./design-controls.js";
import { drawWave } from "./design-draw.js";
import { bufferToWav, bytesToBase64 } from "./preview-output.js";
import { openDeviceInput } from "./sound.js";

const MAX_RECORD_SECONDS = 60;
const $ = (id) => document.getElementById(id);

// Copies each block of input to the main thread, so a recording is the exact samples, not a compressed stream.
const TAP_PROCESSOR = `
class StudioTap extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input.length) this.port.postMessage(input.map((channel) => channel.slice(0)));
    return true;
  }
}
registerProcessor("koii-studio-tap", StudioTap);
`;

const EDIT_LABELS = {
  trim: (step) => `trim ${step.start.toFixed(3)}–${step.end.toFixed(3)}s`,
  trim_silence: () => "trim silence",
  fade: (step) => `fades ${step.in * 1000}/${step.out * 1000} ms`,
  reverse: () => "reverse",
  normalise: () => "normalise",
  mono: () => "mono",
  pitch: (step) => `pitch ${step.semitones > 0 ? "+" : ""}${step.semitones} st`,
  stretch: (step) => `stretch ×${step.factor}`,
};

class Recorder {
  async start() {
    const { stream } = await openDeviceInput();
    this.stream = stream;
    this.context = new AudioContext();
    const url = URL.createObjectURL(new Blob([TAP_PROCESSOR], { type: "text/javascript" }));
    await this.context.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    this.chunks = [];
    this.node = new AudioWorkletNode(this.context, "koii-studio-tap");
    this.node.port.onmessage = (message) => this.chunks.push(message.data);
    this.context.createMediaStreamSource(stream).connect(this.node);
    this.label = stream.getAudioTracks()[0].label || "audio input";
    this.startedAt = performance.now();
  }

  get seconds() {
    return this.startedAt ? (performance.now() - this.startedAt) / 1000 : 0;
  }

  /** Frames recorded so far (to mark when something happened during the recording). */
  get frames() {
    return (this.chunks || []).reduce((total, chunk) => total + chunk[0].length, 0);
  }

  async stop() {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.node?.disconnect();
    const rate = this.context.sampleRate;
    await this.context.close();
    const chunks = this.chunks;
    const channels = Math.max(1, ...chunks.map((chunk) => chunk.length));
    const frames = chunks.reduce((total, chunk) => total + chunk[0].length, 0);
    const buffer = new AudioBuffer({ length: Math.max(1, frames), numberOfChannels: channels, sampleRate: rate });
    let offset = 0;
    for (const chunk of chunks) {
      for (let c = 0; c < channels; c++) buffer.getChannelData(c).set(chunk[Math.min(c, chunk.length - 1)], offset);
      offset += chunk[0].length;
    }
    this.startedAt = null;
    return buffer;
  }
}

export class Sampler {
  constructor(designer, { getPlayables }) {
    this.designer = designer;
    this.toast = designer.toast;
    this.getPlayables = getPlayables;
    this.sources = [];
    this.current = null;       // { info, buffer, onsets }
    this.edits = [];
    this.selection = null;     // frames
    this.slices = [];
    this.recorder = null;
    this._wire();
  }

  _wire() {
    $("sampler-record").addEventListener("click", () => (this.recorder ? this.stopRecording() : this.record()));
    $("sampler-file").addEventListener("change", (event) => {
      const file = event.target.files[0];
      event.target.value = "";
      if (file) this.load(file);
    });
    $("bounce-btn").addEventListener("click", () => this.bounce());
    $("sampler-play").addEventListener("click", () => this.play());
    for (const button of document.querySelectorAll("[data-edit]")) {
      button.addEventListener("click", () => this.addEdit(button.dataset.edit));
    }
    $("sampler-keep").addEventListener("click", () => this.keep());
    $("sampler-design").addEventListener("click", () => this.designWith());
    $("sampler-upload").addEventListener("click", () => this.upload());
    $("sampler-delete").addEventListener("click", () => this.remove());
    $("chop-mode").addEventListener("change", () => {
      const even = $("chop-mode").value === "even";
      $("chop-count").hidden = !even;
      $("chop-sensitivity-row").hidden = even;
    });
    $("chop-btn").addEventListener("click", () => this.chop());
    $("slices-upload").addEventListener("click", () => this.uploadSlices());
    this._wireSelection($("sampler-wave"));
    new ResizeObserver(() => this.draw()).observe($("sampler-wave"));
  }

  _wireSelection(canvas) {
    let anchor = null;
    const frameAt = (event) => {
      const box = canvas.getBoundingClientRect();
      const frames = this.current?.buffer.length || 0;
      return Math.round(Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)) * frames);
    };
    canvas.addEventListener("pointerdown", (event) => {
      if (!this.current) return;
      anchor = frameAt(event);
      this.selection = null;
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener("pointermove", (event) => {
      if (anchor === null) return;
      const here = frameAt(event);
      this.selection = { start: Math.min(anchor, here), end: Math.max(anchor, here) };
      this.draw();
    });
    canvas.addEventListener("pointerup", () => {
      anchor = null;
      if (this.selection && this.selection.end - this.selection.start < 64) this.selection = null;
      this.draw();
      this.describeSelection();
    });
  }

  show() {
    this.fillBounceChoices();
    if (!this.current && this.sources.length) this.select(this.sources[0].id);
    this.draw();
  }

  fillBounceChoices() {
    const select = $("bounce-what");
    const current = select.value;
    select.replaceChildren(new Option("current pattern", "current"));
    const { patterns, songs } = this.getPlayables();
    for (const name of patterns) select.append(new Option(`pattern · ${name}`, name));
    for (const name of songs) select.append(new Option(`song · ${name}`, name));
    if (current) select.value = current;
  }

  // -- the list of sources -------------------------------------------------------------------

  showSources(sources) {
    this.sources = sources;
    const list = $("sampler-sources");
    list.replaceChildren();
    if (!sources.length) {
      list.append(element("p", "hint", "Nothing yet: record the EP-133, bounce a pattern, or load a file."));
      return;
    }
    for (const source of sources) {
      const row = element("button", "sample-row");
      row.type = "button";
      row.classList.toggle("current", source.id === this.current?.info.id);
      row.append(element("span", "sample-slot num", source.origin), element("span", "sample-name", source.name),
                 element("span", "sample-length num", `${source.seconds.toFixed(2)}s${source.bpm ? ` · ${source.bpm} bpm` : ""}`));
      row.addEventListener("click", () => this.select(source.id));
      list.append(row);
    }
  }

  async select(id, edits = []) {
    try {
      const result = await command("source_get", { id, edits });
      this.current = { info: result.info, buffer: await this.designer.output.decode(result.wav), onsets: result.onsets,
                       fits: result.fits_device, analysis: result.analysis };
      this.edits = edits;
      this.selection = null;
      this.slices = [];
      $("slices-upload").hidden = true;
      $("chop-summary").textContent = "";
      $("sampler-title").textContent = `${result.info.name} · ${result.info.origin}` +
        (result.fits_device ? "" : " · longer than the device's 20 s: trim before uploading");
      this.showEdits();
      this.showSources(this.sources);
      this.draw();
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  draw() {
    const buffer = this.current?.buffer;
    const markers = this.slices.length ? this.slices : [];
    drawWave($("sampler-wave"), buffer, { selection: this.selection, markers,
                                         playhead: this.playing ? this.designer.output.position() : null });
  }

  describeSelection() {
    if (!this.current) return;
    const rate = this.current.buffer.sampleRate;
    $("sampler-status").textContent = this.selection
      ? `selection ${(this.selection.start / rate).toFixed(3)}–${(this.selection.end / rate).toFixed(3)} s` : "";
  }

  play() {
    if (!this.current) return;
    const { start, end } = this.selection || { start: 0, end: undefined };
    this.playing = this.designer.output.play(this.current.buffer, { from: start, to: end, onEnd: () => {
      this.playing = null;
      this.draw();
    } });
    const step = () => {
      this.draw();
      if (this.playing) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // -- editing ----------------------------------------------------------------------------

  addEdit(op) {
    if (!this.current) return this.toast("Choose a source first.", true);
    const rate = this.current.buffer.sampleRate;
    const step = { op };
    if (op === "trim") {
      if (!this.selection) return this.toast("Drag across the waveform to select what to keep.", true);
      Object.assign(step, { start: this.selection.start / rate, end: this.selection.end / rate });
    }
    if (op === "fade") Object.assign(step, { in: 0.002, out: 0.03 });
    if (op === "pitch") Object.assign(step, { semitones: Number($("edit-semitones").value) || 0, keep_length: true });
    if (op === "stretch") Object.assign(step, { factor: Number($("edit-stretch").value) || 1 });
    this.select(this.current.info.id, [...this.edits, step]);
  }

  showEdits() {
    const chips = $("sampler-edits");
    chips.replaceChildren();
    this.edits.forEach((step, index) => {
      const chip = element("button", "brush edit-chip", `${EDIT_LABELS[step.op](step)} ✕`);
      chip.type = "button";
      chip.title = "Remove this edit";
      chip.addEventListener("click", () => this.select(this.current.info.id, this.edits.filter((_, i) => i !== index)));
      chips.append(chip);
    });
    if (!this.edits.length && this.current) chips.append(element("span", "hint", "No edits: this is the original."));
  }

  async keep() {
    if (!this.current || !this.edits.length) return this.toast("Make an edit first.", true);
    try {
      const entry = await command("source_save_edit", { id: this.current.info.id, edits: this.edits });
      await this.designer.refreshLibrary();
      await this.select(entry.id);
      this.toast(`Kept as “${entry.name}”.`);
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  /** Edits are applied by keeping them first, so the designer's sample layer uses exactly this sound. */
  async currentSourceId() {
    if (!this.edits.length) return this.current.info.id;
    const entry = await command("source_save_edit", { id: this.current.info.id, edits: this.edits });
    await this.designer.refreshLibrary();
    await this.select(entry.id);
    return entry.id;
  }

  async designWith() {
    if (!this.current) return;
    try {
      const id = await this.currentSourceId();
      const design = await command("source_design", { id, name: this.current.info.name });
      await this.designer.open(design);
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  async upload() {
    if (!this.current) return;
    if (!pressedTwice($("sampler-upload"), `upload “${this.current.info.name}”?`)) return;
    try {
      const id = await this.currentSourceId();
      const tempo = this.current.info.bpm;
      const result = await command(tempo ? "bounce_upload" : "source_upload", { id });
      this.toast(result.message);
      this.designer.onUploaded(result);
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  async remove() {
    if (!this.current) return;
    if (!pressedTwice($("sampler-delete"), "delete source?")) return;
    try {
      await command("source_delete", { id: this.current.info.id });
      this.current = null;
      this.edits = [];
      await this.designer.refreshLibrary();
      this.draw();
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  // -- chopping ---------------------------------------------------------------------------

  async chop() {
    if (!this.current) return;
    const even = $("chop-mode").value === "even";
    try {
      const pieces = await command("source_chop", {
        id: this.current.info.id, edits: this.edits,
        slices: even ? Number($("chop-count").value) : undefined,
        sensitivity: Number($("chop-sensitivity").value) / 100,
      });
      this.slicePieces = pieces;
      const rate = this.current.buffer.sampleRate;
      let position = 0;
      this.slices = pieces.map((piece) => {
        const start = position;
        position += Math.round(piece.seconds * rate);
        return start;
      });
      $("chop-summary").textContent = `${pieces.length} slices, kept as sources` +
        (pieces.length > 12 ? "; the first 12 can go to pads in one go" : "");
      $("slices-upload").hidden = false;
      await this.designer.refreshLibrary();
      this.draw();
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  async uploadSlices() {
    if (!this.slicePieces?.length) return;
    const count = Math.min(12, this.slicePieces.length);
    if (!pressedTwice($("slices-upload"), `upload ${count} slices?`)) return;
    try {
      const result = await command("slices_upload", { ids: this.slicePieces.map((piece) => piece.id) });
      this.toast(result.message.split("\n")[0]);
      this.designer.showTab("kit");
      this.designer.kit.onEvent({ type: "kit", stage: "start", style: "slices", first: result.first, total: result.total });
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  // -- recording ----------------------------------------------------------------------------

  async record({ seconds = MAX_RECORD_SECONDS } = {}) {
    try {
      this.recorder = new Recorder();
      await this.recorder.start();
    } catch (error) {
      this.recorder = null;
      return this.toast(`Couldn't record: ${error.message}`, true);
    }
    $("sampler-record").setAttribute("aria-pressed", "true");
    const tick = () => {
      if (!this.recorder) return;
      $("sampler-status").textContent = `● recording ${this.recorder.label} · ${this.recorder.seconds.toFixed(1)} s`;
      if (this.recorder.seconds >= seconds) this.stopRecording();
      else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  async stopRecording({ save = true } = {}) {
    if (!this.recorder) return null;
    const recorder = this.recorder;
    this.recorder = null;
    $("sampler-record").setAttribute("aria-pressed", "false");
    $("sampler-status").textContent = "";
    const buffer = await recorder.stop();
    if (!save) return buffer;
    try {
      const entry = await command("source_add", { wav: bytesToBase64(bufferToWav(buffer)), name: "recording",
                                                  origin: "recording" });
      await this.designer.refreshLibrary();
      await this.select(entry.id, [{ op: "trim_silence" }]);
      this.toast(`Recorded ${buffer.duration.toFixed(1)} s. Silence at the ends is trimmed (an edit you can remove).`);
    } catch (error) {
      this.toast(error.message, true);
    }
    return buffer;
  }

  async load(file) {
    try {
      // Decode in the browser (it reads MP3, AAC, FLAC…), then send it on as a WAV.
      const decoded = await new OfflineAudioContext(1, 1, 44100).decodeAudioData(await file.arrayBuffer());
      const entry = await command("source_add", { wav: bytesToBase64(bufferToWav(decoded)),
                                                  name: file.name.replace(/\.[^.]+$/, "").slice(0, 40), origin: "file" });
      await this.designer.refreshLibrary();
      await this.select(entry.id);
    } catch (error) {
      this.toast(`Couldn't load that file: ${error.message}`, true);
    }
  }

  /** Record the EP-133 while koii studio plays a pattern on it once, then keep it as a tempo-synced loop. */
  async bounce() {
    if (this.recorder) return;
    const choice = $("bounce-what").value;
    const what = choice === "current" ? this.getPlayables().current : choice;
    if (!what) return this.toast("Write a pattern first.", true);
    let plan;
    try {
      plan = await command("bounce_plan", { what });
    } catch (error) {
      return this.toast(error.message, true);
    }
    if (!plan.fits_device) this.toast(`That's ${plan.seconds.toFixed(1)} s, more than a device sample; it'll need trimming.`);
    // The recording's own limit is a safety net; the bounce stops it when the pattern has played.
    await this.record({ seconds: plan.record_seconds + 5 });
    if (!this.recorder) return;
    const recorder = this.recorder;
    await new Promise((resolve) => setTimeout(resolve, 300));   // a moment of silence before the first hit
    const startFrame = recorder.frames;
    const rate = recorder.context.sampleRate;
    try {
      await command("play", { what, repeat: 1 });
    } catch (error) {
      await this.stopRecording({ save: false });
      return this.toast(error.message, true);
    }
    $("sampler-status").textContent = `● bouncing ${plan.bars} bar(s) at ${plan.bpm} BPM…`;
    await new Promise((resolve) => setTimeout(resolve, plan.record_seconds * 1000 + 200));
    const buffer = await this.stopRecording({ save: false });
    try {
      const entry = await command("bounce_save", {
        wav: bytesToBase64(bufferToWav(buffer)), name: `bounce ${what.slice(0, 24)}`.trim(),
        bars: plan.bars, bpm: plan.bpm, latency: startFrame / rate,
      });
      await this.designer.refreshLibrary();
      await this.select(entry.id);
      this.toast(`Bounced ${plan.bars} bar(s) at ${plan.bpm} BPM. “upload as is” sends it with tempo sync on.`);
    } catch (error) {
      this.toast(error.message, true);
    }
  }
}
