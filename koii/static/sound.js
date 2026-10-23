// The live strip in the top bar: what the EP-133's USB audio input (or the browser
// simulator's voices) is playing, as LED columns of spectrum and stereo meters. It only
// listens: nothing is played back, so you never hear anything twice.

const LOWEST_HZ = 25;
const HIGHEST_HZ = 18000;
const METER_FLOOR_DB = -60;
const CLIP_LEVEL = 0.995;
const PEAK_HOLD_SECONDS = 1.2;
const PEAK_FALL_DB_PER_SECOND = 24;
const DEVICE_LABEL = /ep-?133|k\.?o/i;
const STORAGE_KEY = "koii.sound.input";
const STRIP_COLUMN_PX = 5;
const STRIP_SEGMENT_PX = 4;
const STRIP_FLOOR_DB = -90;      // the range the columns show: quiet sounds still light a segment
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
    return true;
  }
}

export class LiveStrip {
  /** canvas: where to draw. onChange(status) hears when listening starts or stops. */
  constructor(canvas, onChange) {
    this.surface = new Surface(canvas, () => {
      if (!this.running) this._draw(null, 0);
    });
    this.onChange = onChange;
    this.running = false;
    this.peaks = new Float32Array(0);
    this.meterPeaks = [{ db: -Infinity, held: 0, clip: 0 }, { db: -Infinity, held: 0, clip: 0 }];
    this.lastFrame = performance.now();
    this.colours = {
      screen: colour("--screen") || "#0e0d0f",
      text: colour("--screen-text") || "#f0e9d8",
      signal: colour("--signal") || "#ff5a1f",
      warn: colour("--warn") || "#efb02e",
      dim: "#2a2724",
    };
    this._draw(null, 0);
  }

  // -- sources -----------------------------------------------------------------------

  /** Listen to an audio input; picks the EP-133 when it can see one. */
  async listenToInput(deviceId) {
    const { stream } = await openDeviceInput(deviceId);
    const track = stream.getAudioTracks()[0];
    const context = new AudioContext({ latencyHint: "interactive" });
    // Started without a click, the browser may hold the context until the first one.
    if (context.state === "suspended") {
      const resume = () => context.resume();
      document.addEventListener("pointerdown", resume, { once: true });
      document.addEventListener("keydown", resume, { once: true });
    }
    const source = context.createMediaStreamSource(stream);
    const channels = track.getSettings().channelCount || 2;
    this._connect(context, source, { owned: true, stream, label: track.label || "audio input", channels });
  }

  /** Listen to the browser simulator's voices (no permission needed). */
  listenToNode(context, node, label) {
    this._connect(context, node, { owned: false, label, channels: 2 });
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
    this._draw(null, 0);
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
    if (!this.graph) return { listening: false, label: null };
    return { listening: true, label: this.graph.label };
  }

  // -- measuring ---------------------------------------------------------------------

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
    this._draw({ spectrum, levels: this._levels(time, seconds) }, seconds);
  }

  /** Peak level per channel, with a peak hold that falls back and a clip light. */
  _levels(time, seconds) {
    const now = performance.now() / 1000;
    return time.map((samples, channel) => {
      let peak = 0;
      for (const sample of samples) peak = Math.max(peak, Math.abs(sample));
      const db = toDb(peak);
      const hold = this.meterPeaks[channel];
      if (db >= hold.db) {
        hold.db = db;
        hold.held = now;
      } else if (now - hold.held > PEAK_HOLD_SECONDS) {
        hold.db -= PEAK_FALL_DB_PER_SECOND * seconds;
      }
      if (peak >= CLIP_LEVEL) hold.clip = now;
      return { db, held: hold.db, clipping: now - hold.clip < PEAK_HOLD_SECONDS };
    });
  }

  _binFor(frequency) {
    return Math.round((frequency / (this.graph.context.sampleRate / 2)) * this.graph.spectrum.length);
  }

  /** The loudest bin in each of `count` bands, spaced evenly on a log scale. */
  _bands(spectrum, count) {
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

  // -- drawing -----------------------------------------------------------------------

  /** LED columns of spectrum, then L and R meters and the peak. reading is null when idle. */
  _draw(reading, seconds) {
    const surface = this.surface;
    if (!surface.width) return;
    const { context, width, height } = surface;
    context.fillStyle = this.colours.screen;
    context.fillRect(0, 0, width, height);
    const meterLeft = width - STRIP_METER_PX;
    const columns = Math.max(8, Math.floor((meterLeft - 12) / STRIP_COLUMN_PX));
    const segments = Math.max(2, Math.floor((height - 4) / STRIP_SEGMENT_PX));
    if (this.peaks.length !== columns) this.peaks = new Float32Array(columns).fill(STRIP_FLOOR_DB);
    const bands = reading ? this._bands(reading.spectrum, columns) : null;
    const level = (db) => clamp((db - STRIP_FLOOR_DB) / (STRIP_CEILING_DB - STRIP_FLOOR_DB), 0, 1);
    for (let column = 0; column < columns; column++) {
      const db = bands ? bands[column] : STRIP_FLOOR_DB;
      this.peaks[column] = Math.max(this.peaks[column] - PEAK_FALL_DB_PER_SECOND * seconds, db);
      const lit = Math.round(level(db) * segments);
      const peak = Math.min(segments - 1, Math.round(level(this.peaks[column]) * segments) - 1);
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
    const levels = reading?.levels;
    for (let channel = 0; channel < 2; channel++) {
      const meter = levels?.[channel];
      const y = 2 + channel * (rowHeight + 3);
      const lit = meter ? clamp((meter.db - METER_FLOOR_DB) / -METER_FLOOR_DB, 0, 1) * STRIP_METER_SEGMENTS : 0;
      const held = meter ? Math.floor(clamp((meter.held - METER_FLOOR_DB) / -METER_FLOOR_DB, 0, 1) * STRIP_METER_SEGMENTS) : -1;
      for (let s = 0; s < STRIP_METER_SEGMENTS; s++) {
        const segmentDb = METER_FLOOR_DB + (s / STRIP_METER_SEGMENTS) * -METER_FLOOR_DB;
        const hot = segmentDb > -6 ? this.colours.signal : segmentDb > -18 ? this.colours.warn : this.colours.text;
        context.fillStyle = s < lit || s === held ? hot : this.colours.dim;
        context.fillRect(meterLeft + s * segmentWidth, y, segmentWidth - 1, rowHeight);
      }
      context.fillStyle = meter?.clipping ? this.colours.signal : this.colours.dim;
      context.fillRect(meterLeft + meterWidth + 2, y, 4, rowHeight);
    }
    const peak = levels ? Math.max(levels[0].db, levels[1].db) : -Infinity;
    context.fillStyle = levels ? this.colours.text : this.colours.dim;
    context.font = "10px ui-monospace, monospace";
    context.textAlign = "right";
    context.fillText(Number.isFinite(peak) ? `${peak.toFixed(1)}` : "–∞", width - 4, height / 2 + 4);
    context.textAlign = "left";
  }
}
