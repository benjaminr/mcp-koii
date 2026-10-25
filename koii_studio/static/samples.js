// The device's sample library: a searchable list of slots, a waveform and
// metadata view for the selected sample, audition on the device, WAV
// download, and backups with progress.

import { command } from "./api.js";

const DEVICE_MEMORY_BYTES = 128 * 1024 * 1024; // 64 MB on early units; the device doesn't report it

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function megabytes(bytes) {
  return `${(bytes / 1e6).toFixed(1)} MB`;
}

export class SampleBrowser {
  constructor(elements, toast) {
    this.elements = elements;
    this.toast = toast;
    this.listing = null;
    this.selected = null;
    this.query = "";
    elements.load.addEventListener("click", () => this.load(Boolean(this.listing)));
    elements.search.addEventListener("input", () => {
      this.query = elements.search.value.trim().toLowerCase();
      this._renderList();
    });
    elements.play.addEventListener("click", () => this.selected && this._play(this.selected.slot));
    elements.backup.addEventListener("click", () => this._backup());
    elements.cancel.addEventListener("click", () => command("cancel_backup").then(this.toast).catch((e) => this.toast(e.message, true)));
    new ResizeObserver(() => this.waveform && this._drawWaveform(this.waveform)).observe(elements.wave);
  }

  async load(refresh) {
    const { load, summary } = this.elements;
    load.disabled = true;
    summary.textContent = "reading the library…";
    try {
      this.listing = await command("samples", { refresh });
      load.textContent = "refresh";
      this._renderSummary();
      this._renderList();
    } catch (error) {
      summary.textContent = "";
      this.toast(error.message, true);
    } finally {
      load.disabled = false;
    }
  }

  _renderSummary() {
    const { occupied, empty, bytes } = this.listing;
    this.elements.summary.textContent = `${occupied} sounds · ${empty} empty slots · ${megabytes(bytes)}`;
    this.elements.memory.style.width = `${Math.min(100, (bytes / DEVICE_MEMORY_BYTES) * 100)}%`;
    this.elements.memoryLabel.textContent = `${megabytes(bytes)} of ~128 MB`;
  }

  _renderList() {
    const list = this.elements.list;
    list.replaceChildren();
    if (!this.listing) return;
    const sounds = this.listing.sounds.filter((s) => !this.query || s.name.toLowerCase().includes(this.query)
      || String(s.slot).padStart(3, "0").includes(this.query));
    for (const sound of sounds) {
      const row = element("button", "sample-row");
      row.type = "button";
      if (this.selected?.slot === sound.slot) row.classList.add("current");
      row.append(
        element("span", "sample-slot num", String(sound.slot).padStart(3, "0")),
        element("span", "sample-name", sound.name),
        element("span", "sample-meta num", `${sound.seconds.toFixed(2)}s${sound.channels === 2 ? " · st" : ""}`),
      );
      row.addEventListener("click", () => this.select(sound));
      list.append(row);
    }
    if (!sounds.length) list.append(element("p", "library-empty", "no samples match"));
  }

  async select(sound) {
    this.selected = sound;
    this._renderList();
    const { title, meta, download } = this.elements;
    title.textContent = `${String(sound.slot).padStart(3, "0")} ${sound.name}`;
    meta.replaceChildren();
    const facts = [
      ["length", `${sound.seconds.toFixed(3)} s`],
      ["channels", sound.channels === 2 ? "stereo" : "mono"],
      ["rate", `${sound.samplerate} Hz`],
      ["root", sound.root || "–"],
      ["play mode", sound.playmode || "–"],
      ["size", `${(sound.bytes / 1024).toFixed(1)} KB`],
      ["crc-32", sound.crc != null ? sound.crc.toString(16).padStart(8, "0") : "–"],
    ];
    for (const [term, value] of facts) meta.append(element("dt", "", term), element("dd", "num", value));
    download.href = `/api/sample.wav?slot=${sound.slot}`;
    download.setAttribute("download", `${String(sound.slot).padStart(3, "0")} ${sound.name}.wav`);
    this.waveform = null;
    this._drawWaveform(null, "reading from the device…");
    try {
      const response = await fetch(`/api/sample.wav?slot=${sound.slot}`);
      if (!response.ok) throw new Error((await response.json()).error);
      const buffer = await new OfflineAudioContext(1, 1, 44100).decodeAudioData(await response.arrayBuffer());
      if (this.selected?.slot !== sound.slot) return;
      this.waveform = buffer;
      this._drawWaveform(buffer);
    } catch (error) {
      this._drawWaveform(null, "couldn't read it");
      this.toast(error.message, true);
    }
  }

  _drawWaveform(buffer, message) {
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
    if (!buffer) {
      context.fillStyle = "#5b5751";
      context.font = "11px ui-monospace, monospace";
      context.fillText(message || "choose a sample", 10, 18);
      return;
    }
    const channel = buffer.getChannelData(0);
    const perPixel = Math.max(1, Math.floor(channel.length / width));
    context.fillStyle = "#ff5a1f";
    for (let x = 0; x < width; x++) {
      let low = 1;
      let high = -1;
      for (let i = x * perPixel; i < Math.min(channel.length, (x + 1) * perPixel); i++) {
        if (channel[i] < low) low = channel[i];
        if (channel[i] > high) high = channel[i];
      }
      if (high < low) continue;
      const top = height / 2 - high * (height / 2 - 4);
      const bottom = height / 2 - low * (height / 2 - 4);
      context.fillRect(x, top, 1, Math.max(1, bottom - top));
    }
  }

  async _play(slot) {
    try {
      this.toast(await command("play_sample", { slot }));
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  async _backup() {
    try {
      this.toast(await command("backup"));
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  /** Live progress from "backup" events. */
  onBackup(event) {
    const { progress, fill, text, cancel, backup } = this.elements;
    const running = !["done", "failed", "cancelled"].includes(event.stage);
    progress.hidden = false;
    cancel.hidden = !running;
    backup.disabled = running;
    fill.style.width = event.total ? `${(event.done / event.total) * 100}%` : "0";
    const counts = event.total ? `${event.done}/${event.total} ` : "";
    const detail = event.reused ? ` · ${event.reused} unchanged, copied` : "";
    text.textContent = `${event.stage} ${counts}${event.message}${detail}`;
    text.classList.toggle("failed", event.stage === "failed");
  }
}
