// The designer's kit tab: twelve sounds in a style for group A, auditioned
// here and uploaded to twelve slots in a row in the background.

import { command } from "./api.js";
import { element, pressedTwice } from "./design-controls.js";

const $ = (id) => document.getElementById(id);

export class KitBuilder {
  constructor(designer) {
    this.designer = designer;
    this.toast = designer.toast;
    this.style = null;
    this.items = [];
    this.previews = new Map();   // design name -> decoded AudioBuffer
    $("kit-upload").addEventListener("click", () => this.upload());
  }

  showStyles(styles) {
    const bar = $("kit-styles");
    bar.replaceChildren();
    for (const style of styles) {
      const button = element("button", "brush", style);
      button.type = "button";
      button.dataset.style = style;
      button.addEventListener("click", () => this.choose(style));
      bar.append(button);
    }
  }

  show() {
    if (!this.style) this.choose($("kit-styles").querySelector("button")?.dataset.style || "808");
    this.refreshStatus();
  }

  async choose(style) {
    this.style = style;
    for (const button of $("kit-styles").querySelectorAll("button")) {
      button.classList.toggle("active", button.dataset.style === style);
    }
    try {
      this.items = await command("kit", { style });
      this.showPads();
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  showPads() {
    const pads = $("kit-pads");
    pads.replaceChildren();
    for (const item of this.items) {
      const pad = element("button", "kit-pad");
      pad.type = "button";
      pad.title = "Click to hear it, double-click to open it in the designer";
      pad.append(element("span", "kit-pad-label num", item.pad.replace("A", "")), element("span", "kit-pad-name", item.design.name),
                 element("span", "kit-pad-role", item.role));
      pad.addEventListener("click", () => this.audition(item, pad));
      pad.addEventListener("dblclick", () => this.designer.open(item.design));
      pads.append(pad);
    }
  }

  async audition(item, pad) {
    pad.classList.add("hit");
    setTimeout(() => pad.classList.remove("hit"), 160);
    try {
      let buffer = this.previews.get(item.design.name);
      if (!buffer) {
        const preview = await command("design_preview", { design: item.design, similar: false });
        buffer = await this.designer.output.decode(preview.wav);
        this.previews.set(item.design.name, buffer);
      }
      this.designer.output.play(buffer);
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  async upload() {
    if (!this.items.length) return;
    if (!pressedTwice($("kit-upload"), `upload the ${this.style} kit (12 slots)?`)) return;
    try {
      const started = await command("kit_upload", { style: this.style });
      this.toast(started.message.split("\n")[0]);
      this.plan = started.message;
      this.onEvent({ type: "kit", stage: "start", style: started.style, first: started.first, total: started.total });
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  async refreshStatus() {
    try {
      const status = await command("kit_status");
      if (status.running) this.onEvent({ type: "kit", stage: "progress", done: status.done, total: status.total,
                                         first: status.first });
    } catch {
      // Nothing running; nothing to show.
    }
  }

  onEvent(event) {
    const progress = $("kit-progress");
    const text = $("kit-text");
    const fill = $("kit-fill");
    if (event.stage === "start") {
      progress.hidden = false;
      fill.style.width = "0%";
      text.textContent = `uploading to slots ${event.first}–${event.first + event.total - 1}…`;
    } else if (event.stage === "progress") {
      progress.hidden = false;
      fill.style.width = `${(event.done / event.total) * 100}%`;
      text.textContent = `${event.done} of ${event.total} uploaded${event.slot ? ` · ${event.pad} → slot ${event.slot}` : ""}`;
    } else if (event.stage === "done") {
      fill.style.width = "100%";
      text.textContent = `done: slots ${event.first}–${event.first + event.total - 1}. ` +
        "On the EP-133: SOUND, hold each pad, − / + to its slot (pad . gets the first, then 0, ENTER, 1–9).";
      this.designer.onUploaded({});
    } else if (event.stage === "error") {
      text.textContent = `stopped at slot ${event.slot}: ${event.message}`;
    }
  }
}
