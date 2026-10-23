// A small Web Audio drum machine and bass synth, so the visualiser can be heard
// without a device (simulator mode). It approximates the role of each pad; it
// doesn't try to sound like the EP-133's samples.

const midiToHz = (note) => 440 * 2 ** ((note - 69) / 12);

export class BrowserSynth {
  constructor() {
    this.context = null;
    this.enabled = false;
  }

  /** Must be called from a user gesture (a click), as browsers require. */
  enable() {
    if (!this.context) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      this.context = new AudioContext();
      this.master = this.context.createDynamicsCompressor();
      this.output = this.context.createGain();
      this.output.gain.value = 0.7;
      this.output.connect(this.master).connect(this.context.destination);
      this.noise = this._noiseBuffer();
    }
    this.context.resume();
    this.enabled = true;
  }

  disable() {
    this.enabled = false;
  }

  /** Where the sound visualiser can listen in: the synth's context and its final node. */
  tap() {
    return this.context ? { context: this.context, node: this.master } : null;
  }

  _noiseBuffer() {
    const length = this.context.sampleRate;
    const buffer = this.context.createBuffer(1, length, this.context.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < length; i++) data[i] = Math.random() * 2 - 1;
    return buffer;
  }

  _envelope(level, decay, start) {
    const gain = this.context.createGain();
    gain.gain.setValueAtTime(level, start);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + decay);
    gain.connect(this.output);
    return gain;
  }

  _noise(filterType, frequency, level, decay, start, q = 0.8) {
    const source = this.context.createBufferSource();
    source.buffer = this.noise;
    const filter = this.context.createBiquadFilter();
    filter.type = filterType;
    filter.frequency.value = frequency;
    filter.Q.value = q;
    source.connect(filter).connect(this._envelope(level, decay, start));
    source.start(start);
    source.stop(start + decay + 0.05);
  }

  _tone(type, from, to, level, decay, start, glide = decay) {
    const oscillator = this.context.createOscillator();
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(from, start);
    if (to !== from) oscillator.frequency.exponentialRampToValueAtTime(to, start + glide);
    oscillator.connect(this._envelope(level, decay, start));
    oscillator.start(start);
    oscillator.stop(start + decay + 0.05);
  }

  /** role: kick, snare, clap, rim, hat, openhat, ride, crash, perc, tom, bass, keys or other. */
  trigger(role, velocity, note) {
    if (!this.enabled || !this.context) return;
    const now = this.context.currentTime + 0.005;
    const level = Math.max(0.05, (velocity / 127) ** 1.3);
    switch (role) {
      case "kick":
        this._tone("sine", 155, 46, level, 0.42, now, 0.09);
        break;
      case "snare":
        this._noise("bandpass", 1900, level * 0.9, 0.2, now, 0.7);
        this._tone("triangle", 200, 170, level * 0.5, 0.11, now);
        break;
      case "clap":
        for (const offset of [0, 0.011, 0.023]) this._noise("bandpass", 1300, level * 0.7, 0.03, now + offset, 1.2);
        this._noise("bandpass", 1200, level * 0.6, 0.18, now + 0.03, 1);
        break;
      case "rim":
        this._tone("square", 1750, 1700, level * 0.25, 0.035, now);
        this._noise("bandpass", 3000, level * 0.4, 0.03, now, 2);
        break;
      case "hat":
        this._noise("highpass", 8000, level * 0.5, 0.055, now);
        break;
      case "openhat":
        this._noise("highpass", 7500, level * 0.45, 0.36, now);
        break;
      case "ride":
        this._noise("highpass", 6200, level * 0.25, 0.9, now);
        this._tone("square", 3150, 3150, level * 0.04, 0.5, now);
        this._tone("square", 4730, 4730, level * 0.03, 0.4, now);
        break;
      case "crash":
        this._noise("highpass", 4200, level * 0.5, 1.5, now);
        break;
      case "tom":
        this._tone("sine", 190, 105, level, 0.32, now, 0.25);
        break;
      case "perc":
        this._tone("sine", 430, 260, level * 0.8, 0.17, now, 0.08);
        break;
      case "bass":
        this._bass(note ?? 36, level, now);
        break;
      case "keys":
        this._tone("triangle", midiToHz(note ?? 60), midiToHz(note ?? 60), level * 0.35, 0.7, now);
        this._tone("triangle", midiToHz(note ?? 60) * 1.004, midiToHz(note ?? 60) * 1.004, level * 0.25, 0.7, now);
        break;
      default:
        this._tone("triangle", midiToHz(note ?? 60), midiToHz(note ?? 60), level * 0.3, 0.2, now);
    }
  }

  _bass(note, level, start) {
    const oscillator = this.context.createOscillator();
    oscillator.type = "sawtooth";
    oscillator.frequency.value = midiToHz(note);
    const filter = this.context.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.setValueAtTime(1100, start);
    filter.frequency.exponentialRampToValueAtTime(220, start + 0.3);
    oscillator.connect(filter).connect(this._envelope(level * 0.6, 0.5, start));
    oscillator.start(start);
    oscillator.stop(start + 0.55);
  }
}
