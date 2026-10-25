// Drawing for the sound designer's screens: waveform (with loop, slices and a
// selection), spectrum and spectrogram, in the same dark screen style as the
// sound module.

const SCREEN = "#0e0d0f";
const SIGNAL = "#ff5a1f";
const FAINT = "rgba(240, 233, 216, 0.08)";
const TEXT = "rgba(240, 233, 216, 0.55)";
const LOOP = "rgba(75, 166, 224, 0.25)";
const LOOP_EDGE = "#4ba6e0";
const SELECTION = "rgba(255, 90, 31, 0.16)";
const MARKER = "#ff4f8b";

/** Size a canvas for its CSS box and return a 2D context in CSS pixels. */
export function prepare(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const { width, height } = canvas.getBoundingClientRect();
  if (!width || !height) return null;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.fillStyle = SCREEN;
  context.fillRect(0, 0, width, height);
  return { context, width, height };
}

function label(context, text, x, y, align = "left") {
  context.fillStyle = TEXT;
  context.font = "10px ui-monospace, Menlo, monospace";
  context.textAlign = align;
  context.fillText(text, x, y);
}

/**
 * Waveform of an AudioBuffer. Options (all in frames): loop {start, end}, markers [frame],
 * selection {start, end}, playhead frame.
 */
export function drawWave(canvas, buffer, { loop, markers = [], selection, playhead } = {}) {
  const screen = prepare(canvas);
  if (!screen) return;
  const { context, width, height } = screen;
  context.fillStyle = FAINT;
  context.fillRect(0, height / 2, width, 1);
  if (!buffer) return;
  const frames = buffer.length;
  const toX = (frame) => (frame / frames) * width;
  if (selection && selection.end > selection.start) {
    context.fillStyle = SELECTION;
    context.fillRect(toX(selection.start), 0, toX(selection.end) - toX(selection.start), height);
  }
  if (loop && loop.start >= 0 && loop.end > loop.start) {
    context.fillStyle = LOOP;
    context.fillRect(toX(loop.start), 0, toX(loop.end) - toX(loop.start), height);
    context.fillStyle = LOOP_EDGE;
    context.fillRect(toX(loop.start), 0, 1, height);
    context.fillRect(toX(loop.end), 0, 1, height);
    label(context, "loop", toX(loop.start) + 4, 12);
  }
  const channels = Array.from({ length: buffer.numberOfChannels }, (_, c) => buffer.getChannelData(c));
  const lane = height / channels.length;
  context.fillStyle = SIGNAL;
  channels.forEach((data, c) => {
    const middle = lane * c + lane / 2;
    const perPixel = Math.max(1, Math.floor(data.length / width));
    for (let x = 0; x < width; x++) {
      let low = 1;
      let high = -1;
      const first = Math.floor((x / width) * data.length);
      for (let i = first; i < Math.min(data.length, first + perPixel); i++) {
        if (data[i] < low) low = data[i];
        if (data[i] > high) high = data[i];
      }
      if (high < low) continue;
      const top = middle - high * (lane / 2 - 3);
      context.fillRect(x, top, 1, Math.max(1, middle - low * (lane / 2 - 3) - top));
    }
  });
  context.fillStyle = MARKER;
  markers.forEach((frame, index) => {
    const x = toX(frame);
    context.fillRect(x, 0, 1, height);
    label(context, String(index + 1), x + 3, height - 4);
  });
  if (playhead !== undefined && playhead !== null) {
    context.fillStyle = "#f0e9d8";
    context.fillRect(toX(playhead), 0, 1, height);
  }
  label(context, `${(frames / buffer.sampleRate).toFixed(3)} s`, width - 6, 12, "right");
}

function frequencyX(hz, [low, high], width) {
  return (Math.log(hz / low) / Math.log(high / low)) * width;
}

/** The whole sound's spectrum: bars per log-spaced band, scaled to the loudest band. */
export function drawSpectrum(canvas, levels, range) {
  const screen = prepare(canvas);
  if (!screen || !levels?.length) return;
  const { context, width, height } = screen;
  const top = Math.max(...levels);
  const floor = top - 72;
  for (const hz of [50, 100, 200, 500, 1000, 2000, 5000, 10000]) {
    const x = frequencyX(hz, range, width);
    context.fillStyle = FAINT;
    context.fillRect(x, 0, 1, height);
    label(context, hz >= 1000 ? `${hz / 1000}k` : String(hz), x + 2, height - 4);
  }
  const barWidth = width / levels.length;
  context.fillStyle = SIGNAL;
  levels.forEach((level, index) => {
    const amount = Math.max(0, (level - floor) / (top - floor));
    const barHeight = amount * (height - 16);
    context.fillRect(index * barWidth + 1, height - 14 - barHeight, Math.max(1, barWidth - 2), barHeight);
  });
  label(context, "72 dB range", width - 6, 12, "right");
}

const HEAT = [[14, 13, 15], [60, 22, 60], [180, 40, 50], [255, 90, 31], [255, 220, 150]];

function heat(amount) {
  const position = Math.min(0.999, Math.max(0, amount)) * (HEAT.length - 1);
  const index = Math.floor(position);
  const mix = position - index;
  const [a, b] = [HEAT[index], HEAT[index + 1]];
  return `rgb(${a.map((value, c) => Math.round(value + (b[c] - value) * mix)).join(",")})`;
}

/** Time across, frequency up (log), colour for level relative to the loudest moment. */
export function drawSpectrogram(canvas, rows, range, seconds) {
  const screen = prepare(canvas);
  if (!screen || !rows?.length) return;
  const { context, width, height } = screen;
  const top = Math.max(...rows.map((row) => Math.max(...row)));
  const columnWidth = width / rows.length;
  const bandHeight = height / rows[0].length;
  rows.forEach((row, x) => {
    row.forEach((level, band) => {
      context.fillStyle = heat((level - (top - 80)) / 80);
      context.fillRect(x * columnWidth, height - (band + 1) * bandHeight, columnWidth + 0.5, bandHeight + 0.5);
    });
  });
  for (const hz of [100, 1000, 10000]) {
    const y = height - (Math.log(hz / range[0]) / Math.log(range[1] / range[0])) * height;
    context.fillStyle = FAINT;
    context.fillRect(0, y, width, 1);
    label(context, hz >= 1000 ? `${hz / 1000}k` : String(hz), 4, y - 3);
  }
  if (seconds) label(context, `${seconds.toFixed(2)} s`, width - 6, height - 4, "right");
}
