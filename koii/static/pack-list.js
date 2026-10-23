// Sample packs: install a demo or kit into a project (samples, pads, patterns and songs in one
// go), or remove its samples to free space on the EP-133. Installing runs on the server in the
// background; progress arrives as "pack" events.

import { command } from "./api.js";
import { element, pressedTwice } from "./design-controls.js";
import { FIRST_EMPTY_PROJECT, PROJECT_COUNT } from "./pads.js";

const $ = (id) => document.getElementById(id);
// The projects that start empty, highest first: where a new pack goes by default.
const EMPTY_PROJECTS = Array.from({ length: PROJECT_COUNT - FIRST_EMPTY_PROJECT + 1 }, (_, i) => PROJECT_COUNT - i);

function megabytes(bytes) {
  return `${(bytes / 1e6).toFixed(1)} MB`;
}

export class PackList {
  /** toast(message, isError) shows a note; run(name, body) runs a logged command. */
  constructor({ toast, run }) {
    this.toast = toast;
    this.run = run;
    this.busy = false;
  }

  async refresh() {
    try {
      const { packs, status } = await command("packs", {});
      this.busy = Boolean(status.running);
      this.render(packs);
      if (status.running) this.showProgress(status);
    } catch (error) {
      $("pack-list").replaceChildren(element("p", "hint", `Couldn't list packs: ${error.message}`));
    }
  }

  render(packs) {
    const list = $("pack-list");
    if (!packs.length) {
      list.replaceChildren(element("p", "hint", "No packs yet. Packs live in ~/.koii/packs; Claude can make one from a demo."));
      return;
    }
    // Which project each installed pack occupies, so a new install doesn't land on one by default.
    this.occupied = new Map(packs.filter((pack) => pack.installed).map((pack) => [pack.installed.project, pack]));
    list.replaceChildren(...packs.map((pack) => this.card(pack)));
  }

  card(pack) {
    const card = element("div", `pack-card${pack.installed ? " installed" : ""}`);
    const head = element("div", "pack-head");
    head.append(element("span", "pack-title", pack.title));
    head.append(element("span", "pack-state", pack.installed ? `in project ${pack.installed.project}` : "not on the device"));
    card.append(head);
    if (pack.description) card.append(element("p", "pack-description", pack.description));
    const songs = pack.songs.length ? `songs: ${pack.songs.join(", ")}` : "no songs";
    card.append(element("div", "pack-meta num", `${pack.samples} samples · ${megabytes(pack.bytes)} · ${pack.patterns} patterns · ${songs}`));
    if (pack.credits.length) {
      const credits = element("details", "pack-credits");
      credits.append(element("summary", "", "sources"));
      for (const credit of pack.credits) {
        const line = element("div", "pack-credit");
        const link = element("a", "", credit.what);
        link.href = credit.source;
        link.target = "_blank";
        link.rel = "noopener";
        line.append(link, ` · ${credit.licence}`);
        credits.append(line);
      }
      card.append(credits);
    }

    const controls = element("div", "row pack-controls");
    const project = element("select", "pack-project");
    project.setAttribute("aria-label", `Project to install ${pack.title} into`);
    for (let n = 1; n <= PROJECT_COUNT; n++) {
      project.append(new Option(`project ${n}${n >= FIRST_EMPTY_PROJECT ? " (starts empty)" : ""}`, String(n)));
    }
    const free = EMPTY_PROJECTS.find((n) => !this.occupied.has(n)) ?? EMPTY_PROJECTS[0];
    project.value = String(pack.installed?.project ?? free);
    const install = element("button", "btn primary small", pack.installed ? "reinstall" : "⤒ install");
    install.type = "button";
    install.title = "Upload its samples (reusing any already there), fill the project's pads, add its patterns and songs";
    install.addEventListener("click", () => this.install(pack, Number(project.value), install));
    controls.append(project, install);
    if (pack.installed) {
      const remove = element("button", "btn ghost small", "remove samples");
      remove.type = "button";
      remove.title = `Delete its ${pack.samples} samples from the EP-133 (${megabytes(pack.bytes)}) and empty their pads; songs stay`;
      remove.addEventListener("click", () => {
        if (pressedTwice(remove, "remove?")) this.remove(pack);
      });
      controls.append(remove);
    }
    card.append(controls);
    return card;
  }

  async install(pack, project, button) {
    if (this.busy) return this.toast("Wait for the pack that's loading to finish.", true);
    // Ask for a second press before replacing another pack's pads, or pads that may be your own.
    const other = this.occupied.get(project);
    if (other && other.name !== pack.name && !pressedTwice(button, `replace ${other.title}?`)) {
      return this.toast(`Project ${project} holds ${other.title}: press again to replace its pads.`);
    }
    if (!other && project < FIRST_EMPTY_PROJECT && !pressedTwice(button, `into ${project}?`)) {
      return this.toast(`Project ${project} may already have sounds on its pads: press again to replace them.`);
    }
    try {
      const result = await this.run("pack_install", { name: pack.name, project });
      this.busy = true;
      this.showProgress(result);
    } catch {
      // run() showed the error
    }
  }

  async remove(pack) {
    try {
      const result = await this.run("pack_remove", { name: pack.name });
      this.busy = true;
      this.showProgress(result);
    } catch {
      // run() showed the error
    }
  }

  showProgress(status) {
    $("pack-progress").hidden = false;
    const fraction = status.total ? status.done / status.total : 0;
    $("pack-fill").style.width = `${Math.round(fraction * 100)}%`;
    const detail = status.detail ? ` · ${status.detail}` : "";
    $("pack-text").textContent = `${status.pack}: ${status.stage}${status.total ? ` ${status.done}/${status.total}` : ""}${detail}`;
    $("pack-text").classList.toggle("failed", status.stage === "failed");
  }

  onEvent(event) {
    this.showProgress(event);
    if (event.running) return;
    this.busy = false;
    if (event.stage === "failed") this.toast(`Pack: ${event.error}`, true);
    else if (event.message) this.toast(event.message);
    this.refresh();
  }
}
