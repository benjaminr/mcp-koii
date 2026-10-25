// Playing designed sounds in the browser, through this computer's speakers or
// straight out of the EP-133 (it's a USB audio output too), so a sound can be
// heard through the device's own outputs before it's uploaded.

const DEVICE_LABEL = /ep-?133|k\.?o\.? ?ii|teenage/i;
const STORAGE_KEY = "koii-studio.designer.output";

export function base64ToBytes(encoded) {
  const binary = atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export function bytesToBase64(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

/** An AudioBuffer as a 16-bit WAV file (for sending recordings to the server). */
export function bufferToWav(buffer) {
  const channels = buffer.numberOfChannels;
  const frames = buffer.length;
  const view = new DataView(new ArrayBuffer(44 + frames * channels * 2));
  const text = (offset, value) => [...value].forEach((char, i) => view.setUint8(offset + i, char.charCodeAt(0)));
  text(0, "RIFF");
  view.setUint32(4, 36 + frames * channels * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, buffer.sampleRate, true);
  view.setUint32(28, buffer.sampleRate * channels * 2, true);
  view.setUint16(32, channels * 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, frames * channels * 2, true);
  const data = Array.from({ length: channels }, (_, c) => buffer.getChannelData(c));
  let offset = 44;
  for (let i = 0; i < frames; i++) {
    for (let c = 0; c < channels; c++) {
      view.setInt16(offset, Math.round(Math.max(-1, Math.min(1, data[c][i])) * 32767), true);
      offset += 2;
    }
  }
  return new Uint8Array(view.buffer);
}

export class PreviewOutput {
  constructor() {
    this.context = null;
    this.playing = null;
    this.sinkId = this._remembered();
  }

  get canChooseOutput() {
    return typeof AudioContext !== "undefined" && "setSinkId" in AudioContext.prototype;
  }

  _context() {
    if (!this.context) {
      this.context = new AudioContext({ latencyHint: "interactive" });
      if (this.sinkId && this.canChooseOutput) this.context.setSinkId(this.sinkId).catch(() => {});
    }
    return this.context;
  }

  async decode(encodedWav) {
    return this._context().decodeAudioData(base64ToBytes(encodedWav).buffer);
  }

  /** Audio outputs; labels (and so the EP-133) only show once the page has had microphone permission. */
  async outputs() {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === "audiooutput").map((d) => ({
      id: d.deviceId === "default" ? "" : d.deviceId,
      label: d.label || "output",
      isDevice: DEVICE_LABEL.test(d.label),
    }));
  }

  async useOutput(sinkId) {
    this.sinkId = sinkId || "";
    try {
      localStorage.setItem(STORAGE_KEY, this.sinkId);
    } catch {
      // Remembering the choice is a convenience only.
    }
    if (this.context && this.canChooseOutput) await this.context.setSinkId(this.sinkId);
  }

  _remembered() {
    try {
      return localStorage.getItem(STORAGE_KEY) || "";
    } catch {
      return "";
    }
  }

  /** Play a buffer; loop {start, end} in frames makes it sustain like the device's key mode does. */
  play(buffer, { loop, onEnd, from = 0, to } = {}) {
    this.stop();
    const context = this._context();
    context.resume();
    const source = context.createBufferSource();
    source.buffer = buffer;
    if (loop && loop.start >= 0 && loop.end > loop.start) {
      source.loop = true;
      source.loopStart = loop.start / buffer.sampleRate;
      source.loopEnd = loop.end / buffer.sampleRate;
    }
    source.connect(context.destination);
    const offset = from / buffer.sampleRate;
    if (to && !source.loop) source.start(0, offset, (to - from) / buffer.sampleRate);
    else source.start(0, offset);
    const startedAt = context.currentTime - offset;
    this.playing = { source, buffer, startedAt, looping: source.loop };
    source.onended = () => {
      if (this.playing?.source === source) this.playing = null;
      onEnd?.();
    };
    return this.playing;
  }

  /** Where the playhead is, in frames (wrapped inside the loop when looping). */
  position() {
    if (!this.playing) return null;
    const { source, buffer, startedAt } = this.playing;
    let seconds = this.context.currentTime - startedAt;
    if (source.loop && seconds > source.loopEnd) {
      const span = source.loopEnd - source.loopStart;
      seconds = source.loopStart + ((seconds - source.loopStart) % span);
    }
    return Math.min(buffer.length, Math.round(seconds * buffer.sampleRate));
  }

  stop() {
    if (!this.playing) return;
    const { source } = this.playing;
    this.playing = null;
    try {
      source.stop();
    } catch {
      // Already stopped.
    }
  }
}
