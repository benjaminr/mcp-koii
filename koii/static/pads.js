// Pad settings: read and change a pad on the EP-133 itself (its sound slot, MIDI channel,
// play mode and level), live over USB. Clicking a pad on the simulated device selects it
// here. Only the settings you change are written, and the server checks the device kept them.

import { command } from "./api.js";

const GROUPS = ["A", "B", "C", "D"];
const KEYS = [".", "0", "Enter", "1", "2", "3", "4", "5", "6", "7", "8", "9"];
const READ_DELAY_MS = 350;   // clicking pads quickly reads only the last one
// Each group drawn like the EP-133's keypad, top row first.
const KEYPAD_ROWS = [["7", "8", "9"], ["4", "5", "6"], ["1", "2", "3"], [".", "0", "Enter"]];
const MODE_MARK = { key: "K", legato: "L" };

const $ = (id) => document.getElementById(id);

export class PadPanel {
  /** toast(message, isError) shows a note; run(name, body) runs a logged command. */
  constructor({ toast, run }) {
    this.toast = toast;
    this.run = run;
    this.current = null;   // the selected pad's settings as last read from the device
    this.pads = new Map(); // every pad's settings, for the map
    const select = $("pad-select");
    for (const group of GROUPS) {
      const options = document.createElement("optgroup");
      options.label = `group ${group}`;
      for (const key of KEYS) options.append(new Option(`${group}${key}`, `${group}${key}`));
      select.append(options);
    }
    const channel = $("pad-channel");
    channel.append(new Option("none", "none"));
    for (let n = 1; n <= 16; n++) channel.append(new Option(`ch ${n}`, String(n)));
    const project = $("project-select");
    for (let n = 1; n <= 9; n++) project.append(new Option(String(n), String(n)));
    project.addEventListener("change", () => this.openProject(Number(project.value)));
    select.addEventListener("change", () => this.read());
    $("pad-read").addEventListener("click", () => this.read());
    $("pad-apply").addEventListener("click", () => this.apply());
    $("pad-undo").addEventListener("click", () => this.undo());
    $("pad-level").addEventListener("input", () => { $("pad-level-value").textContent = $("pad-level").value; });
  }

  /** Read all 48 pads of the open project and draw the map. */
  async loadMap() {
    try {
      const result = await command("pads", {});
      this.pads = new Map(result.pads.map((pad) => [pad.pad, pad]));
      $("project-select").value = String(result.project);
      this.drawMap();
    } catch (error) {
      $("pad-grid").replaceChildren(Object.assign(document.createElement("p"), {
        className: "hint", textContent: `Couldn't read the pads: ${error.message}`,
      }));
    }
  }

  drawMap() {
    const selected = $("pad-select").value;
    const groups = GROUPS.map((group) => {
      const box = document.createElement("div");
      box.className = "pad-map-group";
      const title = document.createElement("div");
      title.className = "pad-map-title";
      title.textContent = group;
      box.append(title);
      for (const row of KEYPAD_ROWS) {
        for (const key of row) box.append(this.mapCell(`${group}${key}`, selected));
      }
      return box;
    });
    $("pad-grid").replaceChildren(...groups);
  }

  mapCell(label, selected) {
    const pad = this.pads.get(label) || { pad: label };
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = `pad-map-cell${pad.sound ? "" : " empty"}${label === selected ? " selected" : ""}${pad.channel ? " pitched" : ""}`;
    const key = label.slice(1) === "Enter" ? "ENT" : label.slice(1);
    const name = pad.sound ? (pad.name || `slot ${pad.sound}`) : "empty";
    cell.title = pad.sound
      ? `${label}: ${name} (slot ${pad.sound})${pad.channel ? `, channel ${pad.channel}` : ""}, ${pad.mode}, level ${pad.level}`
      : `${label}: empty`;
    const top = document.createElement("span");
    top.className = "pad-map-key num";
    top.textContent = key;
    const tags = document.createElement("span");
    tags.className = "pad-map-tags num";
    tags.textContent = [pad.channel ? `ch${pad.channel}` : "", MODE_MARK[pad.mode] || ""].filter(Boolean).join(" ");
    const sound = document.createElement("span");
    sound.className = "pad-map-name";
    sound.textContent = name;
    cell.append(top, tags, sound);
    cell.addEventListener("click", () => {
      $("pad-select").value = label;
      if (this.pads.has(label)) this.show(this.pads.get(label));
      this.read();
    });
    return cell;
  }

  /** Show which project is open on the device (quietly: the device may not be connected yet). */
  async readProject() {
    try {
      const { project } = await command("project", {});
      $("project-select").value = String(project);
    } catch {
      // Not connected over USB yet; the picker keeps its last value.
    }
  }

  async openProject(project) {
    this.status(`opening project ${project} on the EP-133…`);
    try {
      const result = await this.run("project_open", { project });
      this.toast(result.message);
      this.current = null;
      await this.loadMap();
      await this.read();
    } catch (error) {
      this.status(`project not changed: ${error.message}`, true);
      this.readProject();
    }
  }

  /** Select a pad (e.g. one clicked on the simulated device) and read it soon after. */
  select(label) {
    $("pad-select").value = label;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.read(), READ_DELAY_MS);
  }

  async read() {
    const pad = $("pad-select").value;
    this.status(`reading ${pad}…`);
    try {
      const result = await command("pads", { pad });
      this.show(result.pads[0], result.project);
    } catch (error) {
      this.status(`couldn't read ${pad}: ${error.message}`, true);
    }
  }

  show(settings, project) {
    this.current = settings;
    if (settings?.pad) {
      this.pads.set(settings.pad, { ...this.pads.get(settings.pad), ...settings });
      this.drawMap();
    }
    $("pad-sound").value = settings.sound ?? "";
    $("pad-channel").value = settings.channel ? String(settings.channel) : "none";
    $("pad-mode").value = settings.mode ?? "oneshot";
    $("pad-level").value = settings.level ?? 100;
    $("pad-level-value").textContent = $("pad-level").value;
    const what = settings.sound ? `sound ${settings.sound}` : "empty";
    this.status(`${settings.pad} in project ${project ?? "?"}: ${what}${settings.channel ? ` on ch ${settings.channel}` : ""}`);
  }

  /** Only what differs from the device's own values is sent. */
  changes() {
    const current = this.current || {};
    const wanted = {
      sound: $("pad-sound").value ? Number($("pad-sound").value) : null,
      channel: $("pad-channel").value === "none" ? null : Number($("pad-channel").value),
      mode: $("pad-mode").value,
      level: Number($("pad-level").value),
    };
    const changes = {};
    if (wanted.sound && wanted.sound !== current.sound) changes.sound = wanted.sound;
    if (wanted.channel !== (current.channel ?? null)) changes.channel = wanted.channel ?? "none";
    if (wanted.sound || current.sound) {
      if (wanted.mode !== current.mode) changes.mode = wanted.mode;
      if (wanted.level !== current.level) changes.level = wanted.level;
    }
    return changes;
  }

  async apply() {
    const pad = $("pad-select").value;
    if (!this.current || this.current.pad !== pad) return this.read();
    const settings = this.changes();
    if (!Object.keys(settings).length) return this.status(`${pad} is already set like that`);
    this.status(`writing ${pad}…`);
    try {
      const result = await this.run("pad_set", { pad, settings });
      this.show(result.after, result.project);
      this.toast(result.message.split("\n")[0]);
    } catch (error) {
      this.status(`${pad} not changed: ${error.message}`, true);
    }
  }

  async undo() {
    try {
      const result = await this.run("pad_undo", {});
      this.toast(result.message);
      if (result.pad === $("pad-select").value) this.show(result.after);
    } catch (error) {
      this.status(error.message, true);
    }
  }

  /** A pad or project changed elsewhere (by Claude, say). */
  onEvent(event) {
    if (event.type === "project") {
      $("project-select").value = String(event.project);
      this.loadMap();
      return;
    }
    if (event.pad === $("pad-select").value) this.show(event.settings, event.project);
  }

  status(text, isError = false) {
    const node = $("pad-status");
    node.textContent = text;
    node.classList.toggle("failed", isError);
  }
}
