// The visualiser page: wires the device view, editor, library, arranger and
// activity feed to the server's commands and live events.

import { command, getState, listen, midiUrl, musicxmlUrl } from "./api.js";
import { BrowserSynth } from "./audio.js";
import { Device, Keys, noteName, noteToPad } from "./device.js";
import { BRUSHES, Grid, renderKey } from "./grid.js";
import { LayoutEditor } from "./layout.js";
import { Arranger, makeDraggable } from "./arranger.js";
import * as model from "./model.js";
import { Notation } from "./notation.js";
import { roleForName, roleForPad, roleForTrack } from "./roles.js";
import { SoundDesigner } from "./designer.js";
import { pressedTwice } from "./design-controls.js";
import { SampleBrowser } from "./samples.js";
import { LiveStrip, permittedDeviceInput } from "./sound.js";

const $ = (selector) => document.querySelector(selector);
const STORAGE_KEY = "koii.editor";
const KEY_STORAGE_KEY = "koii.grid-key";
const LISTEN_STORAGE_KEY = "koii.sound.listen";
const CHECK_DELAY_MS = 250;
const LIVE_DELAY_MS = 300;
const ARRANGEMENT_DELAY_MS = 350;
const HISTORY_LIMIT = 100;
const TYPING_HISTORY_MS = 1500;
const ACTIVITY_LIMIT = 80;
const NAME_PATTERN = /^[A-Za-z][\w-]{0,63}$/;

const state = {
  server: null,          // last /api/state result
  online: false,         // event stream connected
  pass: null,            // the current playback pass (from the server)
  queued: null,          // something waiting for the end of the loop
  brush: "cycle",
  loop: false,
  live: false,
  editorPlaying: false,  // the last thing played came from the editor
  arrangerPlaying: false,  // the arranger's song is what's playing, so it shows the playhead
  activity: [],
};

const editor = {
  name: "",
  text: "",
  model: null,           // what the grid edits
  pattern: null,         // the server's parse of `text`
  history: [],
  future: [],
  checkSequence: 0,
  checkTimer: null,
  liveTimer: null,
  lastTypingSnapshot: 0,
};

const synth = new BrowserSynth();
const device = new Device($("#device"), {
  onPad: auditionPad,
  onTransport: (action) => {
    if (action === "play") return state.pass ? stop() : playEditor();
    const delta = action === "plus" ? 1 : -1;
    return editModel((m) => {
      const bpm = m.bpm + delta;
      if (bpm < 20 || bpm > 300) return false;
      m.bpm = bpm;
    });
  },
});
const keys = new Keys($("#keys"));
const grid = new Grid($("#grid"), {
  getBrush: () => state.brush,
  onEdit: (edited) => commitModel(edited),
  onAudition: (index) => auditionTrack(index),
  onRemove: (index) => editModel((m) => m.tracks.splice(index, 1)),
  onMove: (index, delta) => editModel((m) => {
    const other = index + delta;
    if (other < 0 || other >= m.tracks.length) return false;
    [m.tracks[index], m.tracks[other]] = [m.tracks[other], m.tracks[index]];
  }),
  onRename: (index) => renameTrack(index),
  onNotes: (index, text) => editModel((m) => { m.tracks[index].notes = text; }),
});
const notation = new Notation($("#notation"), $("#notation-legend"));
const samples = new SampleBrowser({
  load: $("#samples-load"), search: $("#samples-search"), summary: $("#samples-summary"),
  memory: $("#memory-fill"), memoryLabel: $("#memory-label"), list: $("#sample-list"),
  title: $("#sample-title"), meta: $("#sample-meta"), wave: $("#sample-wave"),
  play: $("#sample-play"), download: $("#sample-download"),
  backup: $("#backup-btn"), cancel: $("#backup-cancel"), progress: $("#backup-progress"),
  fill: $("#backup-fill"), text: $("#backup-text"),
}, (message, isError) => toast(message, isError));
const designer = new SoundDesigner({
  toast: (message, isError) => toast(message, isError),
  onUploaded: () => samples.listing && samples.load(true),
  getPlayables: () => ({
    current: editor.text.trim(),
    patterns: (state.server?.library.patterns || []).map((pattern) => pattern.name),
    songs: (state.server?.library.songs || []).map((song) => song.name),
  }),
});
const arranger = new Arranger($("#arranger"), {
  getLibrary: () => state.server?.library,
  onChange: (text) => {
    $("#arrangement").value = text;
    previewArrangement();
  },
  onAudition: (name) => playName(name, false),
});
const sound = new LiveStrip($("#strip-canvas"), (status) => {
  $("#strip-toggle").setAttribute("aria-pressed", String(status.listening));
  $("#strip-status").textContent = status.listening ? status.label : "click to listen";
});

// -- small helpers --------------------------------------------------------------

function toast(message, isError = false) {
  const box = $("#toast");
  box.textContent = message;
  box.classList.toggle("error", isError);
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { box.hidden = true; }, isError ? 6000 : 2500);
}

async function run(name, body, { quiet = false } = {}) {
  try {
    return await command(name, body);
  } catch (error) {
    if (!quiet) toast(error.message, true);
    throw error;
  }
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(className, label, title, onClick) {
  const node = element("button", className, label);
  node.type = "button";
  if (title) node.title = title;
  node.addEventListener("click", onClick);
  return node;
}

function saveDraft() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ name: editor.name, text: editor.text }));
  } catch {
    // Storage can be unavailable (private windows); the draft just isn't kept.
  }
}

function loadDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (draft && typeof draft.text === "string" && draft.text.trim()) return draft;
  } catch {
    // Ignore unreadable drafts.
  }
  return null;
}

// -- the editor -----------------------------------------------------------------

function snapshot() {
  editor.history.push(editor.text);
  if (editor.history.length > HISTORY_LIMIT) editor.history.shift();
  editor.future = [];
}

/** Replace the editor text. `source` says where it came from: grid, text, settings or load. */
function setText(text, source) {
  editor.text = text;
  if (source !== "text") $("#text").value = text;
  saveDraft();
  clearTimeout(editor.checkTimer);
  editor.checkTimer = setTimeout(checkText, source === "text" ? CHECK_DELAY_MS : 0);
}

/** Apply a change to a copy of the model; the change can return false to cancel. */
function editModel(change) {
  if (!editor.model) return;
  const edited = model.cloneModel(editor.model);
  if (change(edited) === false) return;
  commitModel(edited);
}

function commitModel(edited) {
  snapshot();
  editor.model = edited;
  grid.render(edited);
  renderSettings();
  setText(model.modelToText(edited), "grid");
}

async function checkText() {
  const sequence = ++editor.checkSequence;
  const text = editor.text;
  try {
    const pattern = await command("check", { text });
    if (sequence !== editor.checkSequence || grid.painting) return;
    editor.pattern = pattern;
    editor.model = model.modelFromPattern(pattern);
    renderEditor();
    showIssues([], pattern.warnings);
    $("#midi-link").href = midiUrl(text);
    $("#musicxml-link").href = musicxmlUrl(text);
    scheduleLive();
  } catch (error) {
    if (sequence !== editor.checkSequence) return;
    showIssues(error.issues?.length ? error.issues : [{ message: error.message }], []);
    $(".editor-panel").classList.add("stale");
  }
}

function renderEditor() {
  $(".editor-panel").classList.remove("stale");
  grid.render(editor.model);
  notation.render(editor.pattern);
  renderSettings();
}

function renderSettings() {
  const current = editor.model;
  if (!current) return;
  $("#bpm").value = current.bpm;
  $("#swing").value = current.swing;
  $("#swing-value").textContent = current.swing === 50 ? "off" : `${current.swing}%`;
  $("#grid-select").value = current.grid;
  if (!state.pass) device.setBpm(current.bpm);
  const bars = model.patternLength(current) / model.stepsPerBar(current);
  $("#bar-count").textContent = Number.isInteger(bars) ? String(bars) : bars.toFixed(2);
}

function showIssues(issues, warnings) {
  const box = $("#issues");
  box.replaceChildren();
  for (const issue of issues) {
    const where = issue.line ? `line ${issue.line}${issue.column ? `, col ${issue.column}` : ""}: ` : "";
    const row = element("div", "issue", where + issue.message);
    if (issue.line) {
      row.title = "Show in the text";
      row.addEventListener("click", () => showLine(issue.line, issue.column));
    }
    box.append(row);
  }
  for (const warning of warnings || []) box.append(element("div", "issue warning", `⚠ ${warning}`));
}

function showLine(line, column) {
  selectTab("text");
  const area = $("#text");
  const lines = area.value.split("\n");
  const start = lines.slice(0, line - 1).reduce((sum, l) => sum + l.length + 1, 0) + Math.max(0, (column || 1) - 1);
  area.focus();
  area.setSelectionRange(start, column ? start + 1 : start + (lines[line - 1] || "").length);
}

function undo() {
  if (!editor.history.length) return;
  editor.future.push(editor.text);
  setText(editor.history.pop(), "load");
}

function redo() {
  if (!editor.future.length) return;
  editor.history.push(editor.text);
  setText(editor.future.pop(), "load");
}

function loadPattern(name, text) {
  snapshot();
  editor.name = name || "";
  $("#pattern-name").value = editor.name;
  setText(text, "load");
}

function targetText(target) {
  if (!target) return null;
  return target.kind === "note" && target.label === String(target.note) ? String(target.note) : target.label;
}

function renameTrack(index) {
  const track = editor.model.tracks[index];
  const name = prompt(`Rename '${track.name}' to:`, track.name);
  if (!name || name === track.name) return;
  if (!/^[A-Za-z0-9][\w.-]*$/.test(name)) return toast("Names use letters, digits, '.', '_' or '-'", true);
  editModel((m) => {
    const aliases = state.server?.kit.aliases || {};
    const target = targetText(track.target);
    // Keep the same sound: unless the new name already means it, map it explicitly.
    if (target && aliases[name.toLowerCase()] !== target) m.maps[name] = target;
    if (m.maps[track.name] && !m.tracks.some((t, i) => i !== index && t.name === track.name)) delete m.maps[track.name];
    m.tracks[index].name = name;
  });
}

function auditionTrack(index) {
  const track = editor.model?.tracks[index];
  if (!track) return;
  if (!state.server?.connection.connected) return previewLocally(track);
  const sound = track.target ? track.target.label : track.name;
  const note = track.target?.kind === "channel" ? (track.notes.split(/\s+/)[0] || "C1").split("+")[0] : undefined;
  run("audition", { sound, note }).catch(() => {});
}

function previewLocally(track) {
  if (!synth.enabled) return toast("Not connected. Connect to the EP-133 or the browser simulator (top right).");
  synth.trigger(roleForTrack(track), 100, track.target?.note ?? 36);
}

function auditionPad(label) {
  if (!state.server?.connection.connected) {
    if (!synth.enabled) return toast("Not connected. Connect to the EP-133 or the browser simulator (top right).");
    const note = padNote(label);
    device.noteOn(note, 100);
    device.noteOff(note);
    return synth.trigger(roleForName(device.aliases[label]) || roleForPad(label), 100, note);
  }
  run("audition", { sound: label }).catch(() => {});
}

function padNote(label) {
  const base = { A: 36, B: 48, C: 60, D: 72 }[label[0]];
  return base + [".", "0", "Enter", "1", "2", "3", "4", "5", "6", "7", "8", "9"].indexOf(label.slice(1));
}

// -- playback ---------------------------------------------------------------------

async function playEditor() {
  if (!editor.text.trim()) return;
  const wasEditor = state.editorPlaying;
  state.editorPlaying = true; // set first: the first pass event can arrive before the reply
  try {
    await run("play", { what: editor.text, loop: state.loop });
  } catch {
    state.editorPlaying = wasEditor; // run() already showed the error
  }
}

async function playName(name, loop) {
  const wasEditor = state.editorPlaying;
  state.editorPlaying = false;
  state.arrangerPlaying = false;
  try {
    await run("play", { what: name, loop });
  } catch {
    state.editorPlaying = wasEditor;
  }
}

async function stop() {
  state.editorPlaying = false;
  await run("stop", {}).catch(() => {});
}

function playingSource() {
  return state.pass?.info?.sections?.[0]?.patterns?.[0]?.source ?? null;
}

/** In live mode, a valid edit to the looping editor pattern is queued for the next pass. */
function scheduleLive() {
  if (!state.live || !state.editorPlaying || !state.pass?.loop) return;
  if (playingSource() === editor.text && !state.queued) return;
  clearTimeout(editor.liveTimer);
  editor.liveTimer = setTimeout(() => {
    command("play", { what: editor.text, loop: true }).catch((error) => toast(error.message, true));
  }, LIVE_DELAY_MS);
}

function setLoop(on) {
  state.loop = on;
  $("#loop-btn").setAttribute("aria-pressed", String(on));
}

// -- live events ----------------------------------------------------------------

function onEvent(event) {
  switch (event.type) {
    case "note": return onNote(event, "play");
    case "device_note": return onNote(event, "press");
    case "pass":
      state.pass = event;
      state.queued = null;
      device.setPlaying(true, event.loop ? "LOOP" : "PLAY");
      renderNowPlaying();
      return;
    case "queued":
      state.queued = event;
      renderNowPlaying();
      return;
    case "stopped":
      state.pass = null;
      state.queued = null;
      device.clear();
      device.setPlaying(false);
      device.setCounter("1.1.1");
      device.setBpm(editor.model?.bpm);
      device.setSub("stopped");
      grid.setPlayhead(null);
      notation.setPlayhead(null);
      arranger.setPlayhead(null);
      state.arrangerPlaying = false;
      renderNowPlaying();
      return;
    case "activity": return addActivity(event);
    case "backup": return samples.onBackup(event);
    case "design":
    case "designs":
    case "kit":
      return designer.onEvent(event);
    case "connection":
    case "library":
      return refreshState();
    default:
      return undefined;
  }
}

function onNote(event, kind) {
  const padChannel = state.server?.connection.channel ?? 1;
  const pad = noteToPad(event.note);
  const isPadHit = pad && (kind === "press" || event.channel === padChannel);
  if (isPadHit) {
    if (event.on) {
      device.noteOn(event.note, event.velocity, kind);
      if (kind === "play") synth.trigger(roleForName(device.aliases[pad.label]) || roleForPad(pad.label), event.velocity, event.note);
    } else {
      device.noteOff(event.note);
    }
    return;
  }
  if (event.on) {
    keys.noteOn(event.note);
    device.pitchedNote(noteName(event.note), event.channel, event.velocity);
    synth.trigger(event.note < 52 ? "bass" : "keys", event.velocity, event.note);
  } else {
    keys.noteOff(event.note);
  }
}

/** Where playback is now: section, beat within it, and the editor's step if it's what's playing. */
function playbackPosition() {
  const pass = state.pass;
  const info = pass?.info;
  if (!info?.sections?.length) return null;
  let remaining = Math.max(0, Date.now() / 1000 - pass.started_at);
  const elapsed = remaining;
  let index = 0;
  for (; index < info.order.length - 1; index++) {
    const seconds = info.sections[info.order[index]].seconds;
    if (remaining < seconds) break;
    remaining -= seconds;
  }
  const section = info.sections[info.order[index]];
  return { section, index, beat: (remaining * section.bpm) / 60, elapsed, total: pass.duration };
}

function frame() {
  requestAnimationFrame(frame);
  device.tick();
  const position = playbackPosition();
  arranger.setPlayhead(position && state.arrangerPlaying ? position.elapsed : null);
  if (!position) return;
  const { section, beat, elapsed, total } = position;
  $("#np-fill").style.width = `${Math.min(100, (elapsed / total) * 100)}%`;
  const sixteenth = Math.floor((beat % 1) * 4 + 1e-6) + 1;
  device.setCounter(`${Math.floor(beat / 4) + 1}.${Math.floor(beat % 4) + 1}.${sixteenth}`);
  device.setBpm(section.bpm);

  const shown = section.patterns.find((p) => p.source === editor.text) ||
    (editor.name ? section.patterns.find((p) => p.name === editor.name) : null);
  const step = shown ? Math.floor(beat / shown.step_beats + 1e-6) % shown.length : null;
  grid.setPlayhead(step);
  notation.setPlayhead(step);
}

// -- state, library and activity -----------------------------------------------------

async function refreshState() {
  try {
    state.server = await getState();
  } catch (error) {
    return toast(`Couldn't load state: ${error.message}`, true);
  }
  if (!state.activity.length) state.server.activity.filter((event) => event.type === "activity").forEach(addActivity);
  if (!state.pass && state.server.pass) onEvent(state.server.pass);
  device.setKit(state.server.kit);
  renderConnection();
  renderLibrary();
  arranger.render();
  renderTrackOptions();
}

function renderConnection() {
  const pill = $("#connection-btn");
  const connection = state.server?.connection;
  pill.classList.toggle("offline", !state.online);
  pill.classList.toggle("connected", Boolean(connection?.connected && !connection.simulated));
  pill.classList.toggle("simulated", Boolean(connection?.simulated));
  let label = "no device";
  if (!state.online) label = "server offline";
  else if (connection?.simulated) label = "simulator";
  else if (connection?.connected) label = `${connection.port} · ch${connection.channel}`;
  $("#connection-label").textContent = label;

  const menu = $("#connection-menu");
  menu.replaceChildren();
  for (const port of state.server?.ports || []) {
    menu.append(button("", `connect ${port}`, null, () => connect(port)));
  }
  if (state.server?.port_error) menu.append(element("div", "menu-note", state.server.port_error));
  menu.append(button("", "browser simulator (no device)", null, () => {
    enableSound(true);
    connect("simulator");
  }));
  if (connection?.connected) menu.append(button("", "disconnect", null, () => run("disconnect", {}).catch(() => {})));
}

async function connect(port) {
  $("#connection-menu").hidden = true;
  await run("connect", { port }).then((message) => toast(message)).catch(() => {});
}

function enableSound(on) {
  if (on) synth.enable();
  else synth.disable();
  $("#sound-btn").classList.toggle("active", on);
}

function renderLibrary() {
  const box = $("#library");
  box.replaceChildren();
  const { patterns, songs } = state.server.library;
  if (!patterns.length && !songs.length) {
    box.append(element("div", "library-empty", "Nothing saved yet. Name a pattern and press Save."));
    return;
  }
  for (const pattern of patterns) {
    const row = element("div", "library-item");
    makeDraggable(row, pattern.name);
    if (pattern.name === editor.name) row.classList.add("current");
    row.append(element("span", "library-kind", "pat"));
    const name = button("library-name", pattern.name, "Open in the editor", () => loadPattern(pattern.name, pattern.text));
    const bars = pattern.beats ? `${+(pattern.beats / 4).toFixed(2)} bar${pattern.beats === 4 ? "" : "s"}` : "error";
    row.append(name, element("span", "library-meta", pattern.error ? "doesn't parse" : `${bars} · ${pattern.bpm}`));
    row.append(
      button("icon", "▶", "Play", () => playName(pattern.name, false)),
      button("icon", "⟳", "Loop", () => playName(pattern.name, true)),
      button("icon", "+", "Add to the song as a new section", () => arranger.addSection([pattern.name])),
      deleteButton(pattern.name),
    );
    box.append(row);
  }
  for (const song of songs) {
    const row = element("div", "library-item");
    makeDraggable(row, song.name);
    row.append(element("span", "library-kind", "song"));
    row.append(button("library-name", song.name, `Open in the arranger: ${song.arrangement}`, () => openSong(song)));
    row.append(element("span", "library-meta", song.bpm ? `${song.bpm}` : ""));
    row.append(
      button("icon", "▶", "Open and play", () => openSong(song).then(() => playArrangement(false))),
      button("icon", "⟳", "Open and loop", () => openSong(song).then(() => playArrangement(true))),
      deleteButton(song.name),
    );
    box.append(row);
  }
}

/** ✕ asks "delete?" first; a second press within a few seconds deletes. */
function deleteButton(name) {
  const node = button("icon", "✕", `Delete '${name}' from the library`, () => {
    if (pressedTwice(node, "delete?")) run("delete", { name }).then(toast).catch(() => {});
  });
  return node;
}

function renderTrackOptions() {
  const select = $("#add-track-select");
  const previous = select.value;
  select.replaceChildren();
  const groups = [
    ["Kit names", Object.keys(state.server.kit.aliases).sort()],
    ["Pads", state.server.kit.pads.map((pad) => pad.pad)],
    ["MIDI channel (pitched)", Array.from({ length: 16 }, (_, i) => `ch${i + 1}`)],
  ];
  for (const [label, values] of groups) {
    const group = document.createElement("optgroup");
    group.label = label;
    for (const value of values) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      group.append(option);
    }
    select.append(group);
  }
  if (previous) select.value = previous;
}

/** Open a saved song in the arranger. */
async function openSong(song) {
  $("#arrangement").value = song.arrangement;
  $("#song-name").value = song.name;
  arranger.setText(song.arrangement);
  previewArrangement();
}

/** Ask the server to check the arrangement; its issues show under the grid. */
function previewArrangement() {
  clearTimeout(previewArrangement.timer);
  previewArrangement.timer = setTimeout(async () => {
    const arrangement = $("#arrangement").value.trim();
    const issues = $("#arrangement-issues");
    issues.replaceChildren();
    if (!arrangement) return;
    try {
      await command("arrangement", { arrangement });
    } catch (error) {
      issues.append(element("div", "issue", error.message));
    }
  }, ARRANGEMENT_DELAY_MS);
}

function renderNowPlaying() {
  const label = $("#np-label");
  if (!state.pass) {
    label.textContent = "nothing playing";
    label.classList.remove("playing");
    $("#np-fill").style.width = "0";
    return;
  }
  const what = state.pass.label === "pattern" ? (state.editorPlaying ? "editor pattern" : "pattern") : state.pass.label;
  let text = `${what}${state.pass.loop ? ` · loop ${state.pass.number}` : ""}`;
  if (state.queued) text += ` → next: ${state.queued.label === "pattern" ? "your edit" : state.queued.label}`;
  label.textContent = text;
  label.classList.add("playing");
}

const SOURCE_NAMES = { claude: "claude", browser: "you", device: "device" };

function addActivity(event) {
  state.activity.unshift(event);
  state.activity.length = Math.min(state.activity.length, ACTIVITY_LIMIT);
  const box = $("#activity");
  const item = element("div", `activity-item ${event.source}${event.error ? " error" : ""}`);
  const head = element("div", "activity-head");
  const time = new Date(event.time * 1000).toLocaleTimeString("en-GB");
  head.append(element("span", "activity-time", time), element("span", "activity-source", SOURCE_NAMES[event.source] || event.source),
              element("span", "activity-action", event.action));
  item.append(head);
  const args = event.arguments || {};
  const patternText = [args.text, args.what].find((value) => typeof value === "string" && value.includes(":"));
  const detail = args.name || args.what || args.sound || args.port || args.arrangement;
  if (detail && detail !== patternText) item.append(element("div", "activity-detail", String(detail)));
  if (patternText) {
    item.append(element("div", "activity-detail", patternText.trim().split("\n").slice(0, 4).join("\n")));
    item.append(button("link-btn", "Open in editor", null, () => loadPattern(args.name || "", patternText)));
  }
  const result = event.error || event.result;
  if (result) item.append(element("div", "activity-result", result));
  box.prepend(item);
  while (box.children.length > ACTIVITY_LIMIT) box.lastChild.remove();
}

// -- controls ---------------------------------------------------------------------

function selectTab(name) {
  for (const tab of document.querySelectorAll(".tab")) tab.classList.toggle("active", tab.dataset.tab === name);
  for (const body of ["grid", "text", "notation"]) $(`#tab-${body}`).hidden = body !== name;
}

function renderBrushes() {
  const box = $("#brushes");
  box.replaceChildren();
  for (const brush of BRUSHES) {
    const node = button(`brush${brush.symbol === state.brush ? " active" : ""}`, brush.label, brush.title, () => {
      state.brush = brush.symbol;
      renderBrushes();
    });
    box.append(node);
  }
}

function bindControls() {
  $("#play-btn").addEventListener("click", playEditor);
  $("#stop-btn").addEventListener("click", stop);
  $("#loop-btn").addEventListener("click", () => setLoop(!state.loop));
  $("#live-toggle").addEventListener("change", (event) => {
    state.live = event.target.checked;
    if (state.live) {
      setLoop(true);
      toast("Live edit: play the pattern, then every change switches in at the end of the loop");
    }
  });
  $("#sound-btn").addEventListener("click", () => enableSound(!synth.enabled));
  $("#connection-btn").addEventListener("click", (event) => {
    event.stopPropagation();
    const menu = $("#connection-menu");
    menu.hidden = !menu.hidden;
    $("#connection-btn").setAttribute("aria-expanded", String(!menu.hidden));
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".connection")) $("#connection-menu").hidden = true;
  });

  for (const tab of document.querySelectorAll(".tab")) tab.addEventListener("click", () => selectTab(tab.dataset.tab));

  $("#text").addEventListener("input", (event) => {
    const now = Date.now();
    if (now - editor.lastTypingSnapshot > TYPING_HISTORY_MS) snapshot();
    editor.lastTypingSnapshot = now;
    setText(event.target.value, "text");
  });
  $("#pattern-name").addEventListener("input", (event) => {
    editor.name = event.target.value.trim();
    saveDraft();
  });
  $("#save-btn").addEventListener("click", async () => {
    const name = $("#pattern-name").value.trim();
    if (!NAME_PATTERN.test(name)) return toast("Give the pattern a name first (letters, digits, _ or -).", true);
    editor.name = name;
    await run("save_pattern", { name, text: editor.text }).then(() => toast(`Saved '${name}'`)).catch(() => {});
  });
  $("#new-btn").addEventListener("click", () => loadPattern("", model.modelToText(model.emptyModel())));
  $("#undo-btn").addEventListener("click", undo);
  $("#redo-btn").addEventListener("click", redo);

  $("#bpm").addEventListener("change", (event) => {
    const bpm = Math.round(Number(event.target.value));
    if (!(bpm >= 20 && bpm <= 300)) return toast("BPM must be 20–300", true);
    editModel((m) => { m.bpm = bpm; });
  });
  $("#swing").addEventListener("input", (event) => {
    $("#swing-value").textContent = event.target.value === "50" ? "off" : `${event.target.value}%`;
  });
  $("#swing").addEventListener("change", (event) => editModel((m) => { m.swing = Number(event.target.value); }));
  $("#grid-select").addEventListener("change", (event) => editModel((m) => { m.grid = event.target.value; }));
  $("#bar-plus").addEventListener("click", () => editModel((m) => {
    model.setBars(m, Math.ceil(model.patternLength(m) / model.stepsPerBar(m)) + 1);
  }));
  $("#bar-minus").addEventListener("click", () => editModel((m) => {
    const bars = Math.ceil(model.patternLength(m) / model.stepsPerBar(m));
    if (bars <= 1) return false;
    model.setBars(m, bars - 1);
  }));
  $("#add-track-btn").addEventListener("click", () => {
    const value = $("#add-track-select").value;
    if (value) editModel((m) => model.addTrack(m, value, value.startsWith("ch")));
  });

  $("#strip-toggle").addEventListener("click", toggleListening);
  // Choosing a source is a request to listen to it.
  $("#strip-source").addEventListener("change", startListening);
  $("#arrangement").addEventListener("input", () => {
    arranger.setText($("#arrangement").value);
    previewArrangement();
  });
  $("#arr-clear").addEventListener("click", () => {
    $("#arrangement").value = "";
    $("#song-name").value = "";
    arranger.clear();
    $("#arrangement-issues").replaceChildren();
  });
  $("#arr-play").addEventListener("click", () => playArrangement(false));
  $("#arr-loop").addEventListener("click", () => playArrangement(true));
  $("#song-save").addEventListener("click", async () => {
    const name = $("#song-name").value.trim();
    const arrangement = $("#arrangement").value.trim();
    if (!NAME_PATTERN.test(name)) return toast("Give the song a name first.", true);
    if (!arrangement) return toast("Write an arrangement first, e.g. 'intro x2, verse x4'.", true);
    await run("save_song", { name, arrangement }).then(() => toast(`Saved song '${name}'`)).catch(() => {});
  });

  document.addEventListener("keydown", (event) => {
    const typing = event.target.closest("input, textarea, select");
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z" && !typing) {
      event.preventDefault();
      return event.shiftKey ? redo() : undo();
    }
    if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.code === "Space") {
      event.preventDefault();
      return state.pass ? stop() : playEditor();
    }
    if (event.key === "Escape") return stop();
    if (event.key.toLowerCase() === "l") return setLoop(!state.loop);
    return undefined;
  });
}

// -- sound -----------------------------------------------------------------------------

/** Listening is on by default; stopping it by hand keeps it off on later visits. */
function toggleListening() {
  const listen = !sound.running;
  try {
    localStorage.setItem(LISTEN_STORAGE_KEY, listen ? "on" : "off");
  } catch {
    // Not remembered; listening still starts and stops.
  }
  if (listen) startListening();
  else sound.stop();
}

/**
 * Start listening to the EP-133 without asking: only when the browser already may use
 * audio inputs and the EP-133's is there. Otherwise the strip offers a click. Tries again
 * when audio devices change, e.g. when the EP-133 is plugged in.
 */
async function listenIfAllowed() {
  let choice = null;
  try {
    choice = localStorage.getItem(LISTEN_STORAGE_KEY);
  } catch {
    choice = null;
  }
  if (choice === "off" || sound.running || $("#strip-source").value !== "device") return;
  const { permission, device } = await permittedDeviceInput();
  if (device) {
    await sound.listenToInput(device.deviceId).catch((error) => {
      $("#strip-status").textContent = `couldn't listen: ${error.message}`;
    });
    return;
  }
  $("#strip-status").textContent = permission === "granted" ? "EP-133 audio not found"
    : permission === "denied" ? "audio input blocked in site settings" : "click to listen";
}

async function startListening() {
  const source = $("#strip-source").value;
  try {
    if (source === "simulator") {
      enableSound(true);
      const tap = synth.tap();
      sound.listenToNode(tap.context, tap.node, "browser simulator voices");
    } else {
      await sound.listenToInput();
    }
  } catch (error) {
    const denied = error.name === "NotAllowedError";
    toast(denied ? "The browser wasn't allowed to use the audio input. Allow it in the address bar's site settings, then try again."
                 : `Couldn't listen: ${error.message}`, true);
  }
}

async function playArrangement(loop) {
  const arrangement = $("#arrangement").value.trim();
  if (!arrangement) return toast("Add a pattern to the arranger first: drag one in, or press + on it.", true);
  await playName(arrangement, loop);
  state.arrangerPlaying = true;
}

// -- start ------------------------------------------------------------------------

/** The grid's key: open or closed, remembered in this browser. */
function setupKey() {
  const key = $("#grid-key");
  const toggle = $("#key-btn");
  renderKey(key);
  const show = (open) => {
    key.hidden = !open;
    toggle.setAttribute("aria-pressed", String(open));
    try {
      localStorage.setItem(KEY_STORAGE_KEY, open ? "open" : "closed");
    } catch {
      // Storage can be refused in private windows; the key still opens and closes.
    }
  };
  let remembered = null;
  try {
    remembered = localStorage.getItem(KEY_STORAGE_KEY);
  } catch {
    remembered = null;
  }
  show(remembered !== "closed");   // open until someone closes it
  toggle.addEventListener("click", () => show(key.hidden));
}

/** Things that stick below the top bar need its height, which changes as it wraps. */
function trackTopBarHeight() {
  const bar = $(".topbar");
  new ResizeObserver(() => {
    document.documentElement.style.setProperty("--topbar-height", `${bar.offsetHeight}px`);
  }).observe(bar);
}

function start() {
  trackTopBarHeight();
  new LayoutEditor({ page: $(".layout"), bar: $("#layout-bar"), toggle: $("#layout-btn") });
  setupKey();
  renderBrushes();
  bindControls();
  const draft = loadDraft();
  editor.name = draft?.name || "";
  $("#pattern-name").value = editor.name;
  setText(draft?.text || model.modelToText(model.emptyModel()), "load");
  listen(onEvent, (online) => {
    const changed = online !== state.online;
    state.online = online;
    if (online && changed) refreshState();
    else renderConnection();
  });
  requestAnimationFrame(frame);
  designer.start().catch((error) => toast(`The sound designer couldn't start: ${error.message}`, true));
  listenIfAllowed();
  navigator.mediaDevices?.addEventListener?.("devicechange", () => listenIfAllowed());
}

start();
