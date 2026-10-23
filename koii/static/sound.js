// Sound visualisation: oscilloscope, spectrum, spectrogram, level meters and a
// four-band balance view, analysing either the EP-133's USB audio input (the
// real device) or the browser simulator's voices. It only listens: nothing is
// played back, so you never hear anything twice.

const SPECTRUM_BANDS = 56;
const LOWEST_HZ = 25;
const HIGHEST_HZ = 18000;
const SPECTRUM_FLOOR_DB = -96;
const SPECTRUM_CEILING_DB = -12;
const METER_FLOOR_DB = -60;
const CLIP_LEVEL = 0.995;
const PEAK_HOLD_SECONDS = 1.2;
const PEAK_FALL_DB_PER_SECOND = 24;
const SCOPE_SAMPLES = 1024;
const SPECTROGRAM_SPEED = 2;       // CSS pixels per frame
const BALANCE_BANDS = [
  { name: "sub", from: 20, to: 80 },
  { name: "low", from: 80, to: 300 },
  { name: "mid", from: 300, to: 3000 },
  { name: "high", from: 3000, to: 16000 },
];
const FREQUENCY_LABELS = [50, 100, 200, 500, 1000, 2000, 5000, 10000];
const DEVICE_LABEL = /ep-?133|k\.?o/i;
const STORAGE_KEY = "koii.sound.input";
// The live strip in the top bar: LED columns of spectrum, then stereo meters.
const STRIP_COLUMN_PX = 5;
const STRIP_SEGMENT_PX = 3;
const STRIP_FLOOR_DB = -90;      // a little hotter than the spectrum screen, so quiet sounds still show
const STRIP_CEILING_DB = -20;
const STRIP_METER_PX = 150;
const STRIP_METER_SEGMENTS = 24;

/**
 * Open an audio input, preferring the EP-133 (found by name once permission is granted).
 * Returns { stream, inputs }. Needs a user gesture the first time.
 */
export async function openDeviceInput(deviceId) {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("this browser can't capture audio inputs");
  const constraints = (id) => ({
    audio: { deviceId: id ? { exact: id } : undefined, echoCancellation: false, noiseSuppression: false,
             autoGainControl: false, channelCount: { ideal: 2 } },
  });
  let stream = await navigator.mediaDevices.getUserMedia(constraints(deviceId || rememberedInput()));
  // Input names are only visible after permission is granted; switch to the EP-133 if it's elsewhere.
  const inputs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput");
  const current = stream.getAudioTracks()[0];
  const device = inputs.find((d) => DEVICE_LABEL.test(d.label));
  if (!deviceId && device && current.getSettings().deviceId !== device.deviceId) {
    stream.getTracks().forEach((track) => track.stop());
    stream = await navigator.mediaDevices.getUserMedia(constraints(device.deviceId));
  }
  rememberInput(stream.getAudioTracks()[0].getSettings().deviceId);
  return { stream, inputs };
}

/**
 * The EP-133's audio input, found without asking for anything: only when the browser
 * already may use audio inputs (so no permission prompt) and the EP-133 is among them.
 * Returns { permission: "granted" | "prompt" | "denied" | "unknown", device }.
 */
export async function permittedDeviceInput() {
  let permission = "unknown";
  try {
    permission = (await navigator.permissions.query({ name: "microphone" })).state;
  } catch {
    // Some browsers can't say; then only a click starts listening.
  }
  if (permission !== "granted" || !navigator.mediaDevices?.enumerateDevices) return { permission, device: null };
  const inputs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput");
  return { permission, device: inputs.find((d) => DEVICE_LABEL.test(d.label)) || null };
}

function rememberedInput() {
  try {
    return localStorage.getItem(STORAGE_KEY) || undefined;
  } catch {
    return undefined;
  }
}

function rememberInput(deviceId) {
  try {
    if (deviceId) localStorage.setItem(STORAGE_KEY, deviceId);
  } catch {
    // Not kept; the EP-133 is found by name next time anyway.
  }
}

const toDb = (amplitude) => (amplitude > 0 ? 20 * Math.log10(amplitude) : -Infinity);
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

function colour(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** A canvas that keeps its backing store matched to its CSS size and the screen's pixel ratio. */
class Surface {
  /** onResize runs after the canvas changes size, e.g. to redraw it while nothing is playing. */
  constructor(canvas, onResize) {
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.resize();
    new ResizeObserver(() => {
      if (this.resize()) onResize?.();
    }).observe(canvas);
  }

  resize() {
    const ratio = window.devicePixelRatio || 1;
    const { width, height } = this.canvas.getBoundingClientRect();
    if (!width || !height) return false;
    const w = Math.round(width * ratio);
    const h = Math.round(height * ratio);
    if (this.canvas.width === w && this.canvas.height === h) return false;
    this.canvas.width = w;
    this.canvas.height = h;
    this.ratio = ratio;
    this.width = width;
    this.height = height;
    this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.fresh = true;
    return true;
  }
}

export class SoundScope {
  /** elements: { scope, spectrum, spectrogram, meters, balance } canvases, plus status and readout elements. */
  constructor(elements, onChange) {
    const redrawIdle = () => {
      if (!this.running) this._idle();
    };
    this.surfaces = {
      scope: new Surface(elements.scope, redrawIdle),
      spectrum: new Surface(elements.spectrum, redrawIdle),
      spectrogram: new Surface(elements.spectrogram, redrawIdle),
      meters: new Surface(elements.meters, redrawIdle),
      balance: new Surface(elements.balance, redrawIdle),
    };
    if (elements.strip) this.surfaces.strip = new Surface(elements.strip, redrawIdle);
    this.stripPeaks = new Float32Array(0);
    this.readout = elements.readout;
    this.onChange = onChange;
    this.running = false;
    this.peaks = new Float32Array(SPECTRUM_BANDS).fill(SPECTRUM_FLOOR_DB);
    this.meterPeaks = [{ db: -Infinity, held: 0, clip: 0 }, { db: -Infinity, held: 0, clip: 0 }];
    this.beatMark = null;
    this.lastFrame = performance.now();
    this._palette();
    this._idle();
  }

  _palette() {
    this.colours = {
      screen: colour("--screen") || "#0e0d0f",
      text: colour("--screen-text") || "#f0e9d8",
      signal: colour("--signal") || "#ff5a1f",
      press: colour("--press") || "#3d7fa3",
      warn: colour("--warn") || "#efb02e",
      dim: "#2a2724",
      grid: "rgba(240, 233, 216, 0.08)",
    };
    // Spectrogram colour map: silence is the screen colour, loud is cream.
    const stops = [[0, [14, 13, 15]], [0.35, [31, 42, 68]], [0.6, [61, 127, 163]], [0.82, [255, 90, 31]], [1, [240, 233, 216]]];
    this.heat = new Uint8ClampedArray(256 * 3);
    for (let i = 0; i < 256; i++) {
      const t = i / 255;
      const upper = stops.findIndex(([at]) => at >= t);
      const [a, ca] = stops[Math.max(0, upper - 1)];
      const [b, cb] = stops[upper];
      const mix = b === a ? 0 : (t - a) / (b - a);
      for (let c = 0; c < 3; c++) this.heat[i * 3 + c] = ca[c] + (cb[c] - ca[c]) * mix;
    }
  }

  // -- sources -----------------------------------------------------------------------

  /** Listen to an audio input; picks the EP-133 when it can see one. Needs a user gesture. */
  async listenToInput(deviceId) {
    const { stream, inputs } = await openDeviceInput(deviceId);
    const track = stream.getAudioTracks()[0];
    const context = new AudioContext({ latencyHint: "interactive" });
    // Started without a click, the browser may hold the context until the first one.
    if (context.state === "suspended") {
      const resume = () => context.resume();
      document.addEventListener("pointerdown", resume, { once: true });
      document.addEventListener("keydown", resume, { once: true });
    }
    const source = context.createMediaStreamSource(stream);
    const settings = track.getSettings();
    this._connect(context, source, { owned: true, stream,
      label: track.label || "audio input", channels: settings.channelCount || 2, inputs });
  }

  /** Listen to the browser simulator's voices (no permission needed). */
  listenToNode(context, node, label) {
    this._connect(context, node, { owned: false, label, channels: 2, inputs: [] });
  }

  stop() {
    if (!this.graph) return;
    const { context, stream, owned, source, splitter, mix } = this.graph;
    stream?.getTracks().forEach((track) => track.stop());
    try {
      source.disconnect(splitter);
      source.disconnect(mix);
    } catch {
      // Already disconnected.
    }
    if (owned) context.close();
    this.graph = null;
    this.running = false;
    this._idle();
    this.onChange?.(this.describe());
  }

  _connect(context, source, details) {
    this.stop();
    const splitter = context.createChannelSplitter(2);
    const left = context.createAnalyser();
    const right = context.createAnalyser();
    const mix = context.createAnalyser();
    for (const analyser of [left, right]) {
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0;
    }
    mix.fftSize = 8192;
    mix.smoothingTimeConstant = 0.6;
    source.connect(splitter);
    splitter.connect(left, 0);
    splitter.connect(right, 1);
    source.connect(mix);
    this.graph = {
      context, source, splitter, mix, left, right, ...details,
      time: [new Float32Array(left.fftSize), new Float32Array(right.fftSize)],
      spectrum: new Float32Array(mix.frequencyBinCount),
    };
    this.running = true;
    this.lastFrame = performance.now();
    this.onChange?.(this.describe());
    requestAnimationFrame(() => this._frame());
  }

  describe() {
    if (!this.graph) return { listening: false, text: "not listening" };
    const { label, channels, context } = this.graph;
    return { listening: true, label,
             text: `${label} · ${(context.sampleRate / 1000).toFixed(1)} kHz · ${channels === 1 ? "mono" : "stereo"}` };
  }

  /** Mark beats on the spectrogram: { bar, beat } while playing, or null. */
  setBeat(mark) {
    const key = mark ? `${mark.bar}.${mark.beat}` : null;
    if (key && key !== this.beatKey) this.beatMark = mark;
    this.beatKey = key;
  }

  // -- drawing -----------------------------------------------------------------------

  _frame() {
    if (!this.running) return;
    requestAnimationFrame(() => this._frame());
    const now = performance.now();
    const seconds = Math.min(0.1, (now - this.lastFrame) / 1000);
    this.lastFrame = now;
    const { left, right, mix, time, spectrum, channels } = this.graph;
    left.getFloatTimeDomainData(time[0]);
    if (channels === 1) time[1].set(time[0]);
    else right.getFloatTimeDomainData(time[1]);
    mix.getFloatFrequencyData(spectrum);
    this._scope(time);
    const bands = this._bands(spectrum);
    this._spectrum(bands, seconds);
    this._spectrogram(spectrum);
    this._meters(time, seconds);
    this._balance(spectrum);
    this._strip(spectrum, seconds);
  }

  _clear(surface) {
    const { context, width, height } = surface;
    context.fillStyle = this.colours.screen;
    context.fillRect(0, 0, width, height);
  }

  _idle() {
    for (const name of ["scope", "spectrum", "meters", "balance"]) {
      const surface = this.surfaces[name];
      if (!surface.width) continue;
      this._clear(surface);
      surface.context.fillStyle = this.colours.dim;
      surface.context.font = "11px ui-monospace, monospace";
      surface.context.fillText("no signal", 10, 18);
    }
    const spectrogram = this.surfaces.spectrogram;
    if (spectrogram.width) this._clear(spectrogram);
    if (this.surfaces.strip?.width) this._strip(null, 0);
    if (this.readout) this.readout.textContent = "peak –∞ dB · rms –∞ dB";
  }

  _scope(time) {
    const surface = this.surfaces.scope;
    const { context, width, height } = surface;
    this._clear(surface);
    context.strokeStyle = this.colours.grid;
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(0, height / 2);
    context.lineTo(width, height / 2);
    context.stroke();
    // Start where the left channel rises through zero, so the waveform stands still.
    const samples = time[0];
    let start = 0;
    for (let i = 1; i < samples.length - SCOPE_SAMPLES; i++) {
      if (samples[i - 1] < 0 && samples[i] >= 0) {
        start = i;
        break;
      }
    }
    const draw = (data, stroke, alpha) => {
      context.globalAlpha = alpha;
      context.strokeStyle = stroke;
      context.lineWidth = 1.5;
      context.beginPath();
      for (let i = 0; i < SCOPE_SAMPLES; i++) {
        const x = (i / (SCOPE_SAMPLES - 1)) * width;
        const y = height / 2 - data[start + i] * (height / 2 - 4);
        if (i === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      }
      context.stroke();
      context.globalAlpha = 1;
    };
    draw(time[1], this.colours.text, 0.45);
    draw(time[0], this.colours.signal, 1);
  }

  _binFor(frequency) {
    return Math.round((frequency / (this.graph.context.sampleRate / 2)) * this.graph.spectrum.length);
  }

  _bands(spectrum, count = SPECTRUM_BANDS) {
    const bands = new Float32Array(count);
    const ratio = HIGHEST_HZ / LOWEST_HZ;
    for (let band = 0; band < count; band++) {
      const from = this._binFor(LOWEST_HZ * ratio ** (band / count));
      const to = Math.max(from + 1, this._binFor(LOWEST_HZ * ratio ** ((band + 1) / count)));
      let loudest = -Infinity;
      for (let bin = from; bin < to && bin < spectrum.length; bin++) loudest = Math.max(loudest, spectrum[bin]);
      bands[band] = loudest;
    }
    return bands;
  }

  _xForFrequency(frequency, width) {
    return (Math.log(frequency / LOWEST_HZ) / Math.log(HIGHEST_HZ / LOWEST_HZ)) * width;
  }

  _spectrum(bands, seconds) {
    const surface = this.surfaces.spectrum;
    const { context, width, height } = surface;
    this._clear(surface);
    const plot = height - 14;
    const level = (db) => clamp((db - SPECTRUM_FLOOR_DB) / (SPECTRUM_CEILING_DB - SPECTRUM_FLOOR_DB), 0, 1);
    context.fillStyle = this.colours.grid;
    for (const frequency of FREQUENCY_LABELS) context.fillRect(Math.round(this._xForFrequency(frequency, width)), 0, 1, plot);
    const column = width / SPECTRUM_BANDS;
    const segment = 4;
    for (let band = 0; band < SPECTRUM_BANDS; band++) {
      const value = level(bands[band]);
      this.peaks[band] = Math.max(this.peaks[band] - PEAK_FALL_DB_PER_SECOND * seconds, bands[band]);
      const x = band * column + 1;
      const w = Math.max(1, column - 2);
      const lit = Math.round((value * plot) / segment);
      for (let s = 0; s < Math.floor(plot / segment); s++) {
        context.fillStyle = s < lit ? this.colours.signal : this.colours.dim;
        context.fillRect(x, plot - (s + 1) * segment + 1, w, segment - 1);
      }
      const peakY = plot - level(this.peaks[band]) * plot;
      context.fillStyle = this.colours.text;
      context.fillRect(x, Math.min(plot - 1, peakY), w, 1.5);
    }
    context.fillStyle = "rgba(240, 233, 216, 0.55)";
    context.font = "9px ui-monospace, monospace";
    for (const frequency of FREQUENCY_LABELS) {
      const label = frequency >= 1000 ? `${frequency / 1000}k` : String(frequency);
      context.fillText(label, this._xForFrequency(frequency, width) + 2, height - 3);
    }
  }

  _spectrogram(spectrum) {
    const surface = this.surfaces.spectrogram;
    const { canvas, context, width, ratio } = surface;
    if (!width) return;
    if (surface.fresh) {
      this._clear(surface);
      surface.fresh = false;
    }
    const shift = Math.round(SPECTROGRAM_SPEED * ratio);
    const rows = canvas.height;
    context.save();
    context.setTransform(1, 0, 0, 1, 0, 0);
    context.drawImage(canvas, shift, 0, canvas.width - shift, rows, 0, 0, canvas.width - shift, rows);
    const column = context.createImageData(shift, rows);
    const ratioHz = HIGHEST_HZ / LOWEST_HZ;
    for (let y = 0; y < rows; y++) {
      const frequency = LOWEST_HZ * ratioHz ** (1 - y / rows);
      const db = spectrum[clamp(this._binFor(frequency), 0, spectrum.length - 1)];
      const index = Math.round(clamp((db - SPECTRUM_FLOOR_DB) / (SPECTRUM_CEILING_DB - SPECTRUM_FLOOR_DB), 0, 1) * 255) * 3;
      for (let x = 0; x < shift; x++) {
        const offset = (y * shift + x) * 4;
        column.data[offset] = this.heat[index];
        column.data[offset + 1] = this.heat[index + 1];
        column.data[offset + 2] = this.heat[index + 2];
        column.data[offset + 3] = 255;
      }
    }
    context.putImageData(column, canvas.width - shift, 0);
    if (this.beatMark) {
      const isBar = this.beatMark.beat === 1;
      context.fillStyle = isBar ? "rgba(255, 90, 31, 0.85)" : "rgba(240, 233, 216, 0.22)";
      context.fillRect(canvas.width - shift, 0, Math.max(1, Math.round(ratio)), rows);
      if (isBar) {
        context.font = `${Math.round(10 * ratio)}px ui-monospace, monospace`;
        context.fillText(String(this.beatMark.bar), canvas.width - shift - Math.round(14 * ratio), Math.round(12 * ratio));
      }
      this.beatMark = null;
    }
    context.restore();
  }

  _meters(time, seconds) {
    const surface = this.surfaces.meters;
    const { context, width, height } = surface;
    this._clear(surface);
    const now = performance.now() / 1000;
    const rowHeight = (height - 22) / 2;
    const segments = 40;
    const segmentWidth = (width - 30) / segments;
    const readings = [];
    time.forEach((samples, channel) => {
      let peak = 0;
      let sum = 0;
      for (const sample of samples) {
        const size = Math.abs(sample);
        if (size > peak) peak = size;
        sum += sample * sample;
      }
      const rms = Math.sqrt(sum / samples.length);
      const db = toDb(peak);
      const hold = this.meterPeaks[channel];
      if (db >= hold.db || now - hold.held > PEAK_HOLD_SECONDS) {
        hold.db = db >= hold.db ? db : hold.db - PEAK_FALL_DB_PER_SECOND * seconds;
        if (db >= hold.db) hold.held = now;
      }
      if (peak >= CLIP_LEVEL) hold.clip = now;
      readings.push({ db, rms: toDb(rms), held: hold.db, clipping: now - hold.clip < PEAK_HOLD_SECONDS });

      const y = 4 + channel * (rowHeight + 4);
      context.fillStyle = this.colours.text;
      context.font = "10px ui-monospace, monospace";
      context.fillText(channel ? "R" : "L", 4, y + rowHeight / 2 + 4);
      const lit = clamp((db - METER_FLOOR_DB) / -METER_FLOOR_DB, 0, 1) * segments;
      const held = clamp((hold.db - METER_FLOOR_DB) / -METER_FLOOR_DB, 0, 1) * segments;
      for (let s = 0; s < segments; s++) {
        const segmentDb = METER_FLOOR_DB + (s / segments) * -METER_FLOOR_DB;
        const hot = segmentDb > -6 ? this.colours.signal : segmentDb > -18 ? this.colours.warn : this.colours.text;
        context.fillStyle = s < lit ? hot : Math.floor(held) === s ? hot : this.colours.dim;
        context.fillRect(18 + s * segmentWidth, y, segmentWidth - 1.5, rowHeight);
      }
      const clipping = now - hold.clip < PEAK_HOLD_SECONDS;
      context.fillStyle = clipping ? this.colours.signal : this.colours.dim;
      context.fillRect(width - 9, y, 7, rowHeight);
    });
    context.fillStyle = "rgba(240, 233, 216, 0.55)";
    context.font = "9px ui-monospace, monospace";
    for (const db of [-60, -36, -18, -6, 0]) {
      const x = 18 + ((db - METER_FLOOR_DB) / -METER_FLOOR_DB) * segments * segmentWidth;
      context.fillText(String(db), Math.min(width - 22, x - 6), height - 4);
    }
    this.levels = readings;
    if (this.readout) {
      const format = (value) => (Number.isFinite(value) ? value.toFixed(1) : "–∞");
      const peak = Math.max(readings[0].db, readings[1].db);
      const rms = Math.max(readings[0].rms, readings[1].rms);
      this.readout.textContent = `peak ${format(peak)} dB · rms ${format(rms)} dB`;
    }
  }

  /** The top bar's strip: spectrum as LED columns, then L and R meters. Silent and dim when idle. */
  _strip(spectrum, seconds) {
    const surface = this.surfaces.strip;
    if (!surface?.width) return;
    const { context, width, height } = surface;
    this._clear(surface);
    const meterLeft = width - STRIP_METER_PX;
    const columns = Math.max(8, Math.floor((meterLeft - 12) / STRIP_COLUMN_PX));
    const segments = Math.max(2, Math.floor((height - 4) / STRIP_SEGMENT_PX));
    if (this.stripPeaks.length !== columns) this.stripPeaks = new Float32Array(columns).fill(SPECTRUM_FLOOR_DB);
    const bands = spectrum ? this._bands(spectrum, columns) : null;
    const level = (db) => clamp((db - STRIP_FLOOR_DB) / (STRIP_CEILING_DB - STRIP_FLOOR_DB), 0, 1);
    for (let column = 0; column < columns; column++) {
      const db = bands ? bands[column] : SPECTRUM_FLOOR_DB;
      this.stripPeaks[column] = Math.max(this.stripPeaks[column] - PEAK_FALL_DB_PER_SECOND * seconds, db);
      const lit = Math.round(level(db) * segments);
      const peak = Math.min(segments - 1, Math.round(level(this.stripPeaks[column]) * segments) - 1);
      const x = 2 + column * STRIP_COLUMN_PX;
      for (let segment = 0; segment < segments; segment++) {
        const y = height - 2 - (segment + 1) * STRIP_SEGMENT_PX + 1;
        if (segment < lit) context.fillStyle = segment >= segments - 1 ? this.colours.text : this.colours.signal;
        else context.fillStyle = segment === peak && bands ? this.colours.text : this.colours.dim;
        context.fillRect(x, y, STRIP_COLUMN_PX - 1, STRIP_SEGMENT_PX - 1);
      }
    }

    const rowHeight = Math.max(3, (height - 7) / 2);
    const meterWidth = STRIP_METER_PX - 52;
    const segmentWidth = meterWidth / STRIP_METER_SEGMENTS;
    const readings = bands ? this.levels : null;
    for (let channel = 0; channel < 2; channel++) {
      const reading = readings?.[channel];
      const y = 2 + channel * (rowHeight + 3);
      const lit = reading ? clamp((reading.db - METER_FLOOR_DB) / -METER_FLOOR_DB, 0, 1) * STRIP_METER_SEGMENTS : 0;
      const held = reading ? Math.floor(clamp((reading.held - METER_FLOOR_DB) / -METER_FLOOR_DB, 0, 1) * STRIP_METER_SEGMENTS) : -1;
      for (let s = 0; s < STRIP_METER_SEGMENTS; s++) {
        const segmentDb = METER_FLOOR_DB + (s / STRIP_METER_SEGMENTS) * -METER_FLOOR_DB;
        const hot = segmentDb > -6 ? this.colours.signal : segmentDb > -18 ? this.colours.warn : this.colours.text;
        context.fillStyle = s < lit || s === held ? hot : this.colours.dim;
        context.fillRect(meterLeft + s * segmentWidth, y, segmentWidth - 1, rowHeight);
      }
      context.fillStyle = reading?.clipping ? this.colours.signal : this.colours.dim;
      context.fillRect(meterLeft + meterWidth + 2, y, 4, rowHeight);
    }
    const peak = readings ? Math.max(readings[0].db, readings[1].db) : -Infinity;
    context.fillStyle = bands ? this.colours.text : this.colours.dim;
    context.font = "10px ui-monospace, monospace";
    context.textAlign = "right";
    context.fillText(Number.isFinite(peak) ? `${peak.toFixed(1)}` : "–∞", width - 4, height / 2 + 4);
    context.textAlign = "left";
  }

  _balance(spectrum) {
    const surface = this.surfaces.balance;
    const { context, width, height } = surface;
    this._clear(surface);
    const plot = height - 26;
    const column = width / BALANCE_BANDS.length;
    BALANCE_BANDS.forEach((band, index) => {
      let power = 0;
      for (let bin = this._binFor(band.from); bin < this._binFor(band.to) && bin < spectrum.length; bin++) {
        power += 10 ** (spectrum[bin] / 10);
      }
      const db = 10 * Math.log10(power || 1e-12);
      const value = clamp((db - (SPECTRUM_FLOOR_DB + 20)) / (SPECTRUM_CEILING_DB + 10 - (SPECTRUM_FLOOR_DB + 20)), 0, 1);
      const x = index * column + column * 0.2;
      const w = column * 0.6;
      context.fillStyle = this.colours.dim;
      context.fillRect(x, 6, w, plot);
      context.fillStyle = index === 0 ? this.colours.press : this.colours.signal;
      context.fillRect(x, 6 + plot * (1 - value), w, plot * value);
      context.fillStyle = "rgba(240, 233, 216, 0.75)";
      context.font = "9px ui-monospace, monospace";
      context.fillText(band.name, x, height - 12);
      context.fillText(Number.isFinite(db) ? `${Math.round(db)}` : "–", x, height - 2);
    });
  }
}
