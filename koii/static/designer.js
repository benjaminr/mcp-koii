// The sound designer (module 06): edits a design, has the server render and
// analyse it (the same engine Claude uses over MCP), plays it here or through
// the EP-133's own outputs, explores variations and morphs, keeps a library,
// and uploads the result with its instrument settings.
//
// The sample and kit tabs live in sampler.js and kit.js; this file owns the
// shared pieces (the current design, preview playback, the library list).

import { command } from "./api.js";
import { DesignControls, element, pressedTwice } from "./design-controls.js";
import { drawSpectrogram, drawSpectrum, drawWave } from "./design-draw.js";
import { KitBuilder } from "./kit.js";
import { PreviewOutput } from "./preview-output.js";
import { Sampler } from "./sampler.js";

const RENDER_DELAY_MS = 120;
const LOCK_CHOICES = [
  ["layers.*.params", "engines"],
  ["layers.*.amp", "envelopes"],
  ["layers.*.pitch", "pitch"],
  ["layers.*.filter", "filters"],
  ["effects", "effects"],
];

const $ = (id) => document.getElementById(id);

function formatDb(value) {
  return `${value.toFixed(1)}`;
}

export class SoundDesigner {
  constructor({ toast, onUploaded, getPlayables }) {
    this.toast = toast;
    this.onUploaded = onUploaded;
    this.output = new PreviewOutput();
    this.schema = null;
    this.design = null;
    this.preview = null;        // the last server render: { design, wav, analysis, device, similar }
    this.buffer = null;
    this.variations = [];
    this.library = { designs: [], sources: [] };
    this.renderId = 0;
    this.controls = new DesignControls($("designer-controls"), {
      onChange: () => this.renderSoon(),
      onAudition: ({ layer }) => this.solo(layer),
    });
    this.sampler = new Sampler(this, { getPlayables });
    this.kit = new KitBuilder(this);
    this._wire();
  }

  async start() {
    this.schema = await command("design_schema");
    await this.refreshLibrary();
    this.kit.showStyles(this.schema.kit_styles);
    await this.open(await command("design_preset", { name: "kick" }), { name: "kick" });
    this.fillOutputs();
  }

  // -- wiring ---------------------------------------------------------------------------

  _wire() {
    for (const tab of document.querySelectorAll("[data-designer-tab]")) {
      tab.addEventListener("click", () => this.showTab(tab.dataset.designerTab));
    }
    $("designer-start").addEventListener("change", (event) => this.startFrom(event.target.value));
    $("designer-save").addEventListener("click", () => this.save());
    $("designer-delete").addEventListener("click", () => this.deleteSaved());
    $("designer-name").addEventListener("input", () => {
      if (this.design) this.design.name = $("designer-name").value.trim() || "new sound";
    });
    $("designer-play").addEventListener("click", () => this.play());
    $("designer-stop").addEventListener("click", () => this.output.stop());
    $("designer-hold").addEventListener("click", () => {
      const hold = $("designer-hold").getAttribute("aria-pressed") !== "true";
      $("designer-hold").setAttribute("aria-pressed", String(hold));
      if (!hold) this.output.stop();
      else this.play();
    });
    $("designer-output").addEventListener("change", (event) => this.output.useOutput(event.target.value)
      .catch((error) => this.toast(`Couldn't use that output: ${error.message}`, true)));
    $("designer-upload").addEventListener("click", () => this.upload());
    $("vary-amount").addEventListener("input", () => {
      $("vary-amount-value").textContent = (Number($("vary-amount").value) / 100).toFixed(2);
    });
    $("vary-btn").addEventListener("click", () => this.vary());
    $("morph-amount").addEventListener("input", () => {
      $("morph-value").textContent = (Number($("morph-amount").value) / 100).toFixed(2);
    });
    $("morph-btn").addEventListener("click", () => this.morph());
    const locks = $("vary-locks");
    locks.append(element("span", "param-name", "keep"));
    for (const [path, label] of LOCK_CHOICES) {
      const box = element("label", "lock");
      const input = element("input");
      input.type = "checkbox";
      input.value = path;
      box.append(input, ` ${label}`);
      locks.append(box);
    }
    new ResizeObserver(() => this.draw()).observe($("designer-wave"));
    document.addEventListener("keydown", (event) => {
      const typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName || "");
      if (event.code === "Space" && !typing && this.visible("design")) {
        event.preventDefault();
        this.play();
      }
    });
  }

  visible(tab) {
    return !$(`designer-page-${tab}`).hidden && $("designer-page-design").closest("section").getBoundingClientRect().top
      < window.innerHeight;
  }

  showTab(name) {
    for (const tab of document.querySelectorAll("[data-designer-tab]")) {
      tab.classList.toggle("active", tab.dataset.designerTab === name);
    }
    for (const page of ["design", "sample", "kit"]) $(`designer-page-${page}`).hidden = page !== name;
    if (name === "sample") this.sampler.show();
    if (name === "kit") this.kit.show();
    if (name === "design") this.draw();
  }

  // -- the library and starting points ---------------------------------------------------------

  async refreshLibrary() {
    this.library = await command("design_library");
    this.controls.sources = this.library.sources;
    this.fillStartMenu();
    this.fillMorphTargets();
    this.sampler.showSources(this.library.sources);
  }

  fillStartMenu() {
    const select = $("designer-start");
    select.replaceChildren(new Option("start from…", ""));
    const blank = element("optgroup");
    blank.label = "new";
    blank.append(new Option("empty design", "new:"));
    select.append(blank);
    for (const [category, names] of Object.entries(this.schema.presets)) {
      const group = element("optgroup");
      group.label = `presets · ${category}`;
      for (const name of names) group.append(new Option(name, `preset:${name}`));
      select.append(group);
    }
    if (this.library.designs.length) {
      const group = element("optgroup");
      group.label = "saved";
      for (const saved of this.library.designs) {
        const slots = saved.slots.length ? ` · slot ${saved.slots.join(", ")}` : "";
        group.append(new Option(`${saved.name}${slots}`, `saved:${saved.name}`));
      }
      select.append(group);
    }
  }

  fillMorphTargets() {
    const select = $("morph-target");
    const current = select.value;
    select.replaceChildren();
    for (const [category, names] of Object.entries(this.schema.presets)) {
      const group = element("optgroup");
      group.label = category;
      for (const name of names) group.append(new Option(name, `preset:${name}`));
      select.append(group);
    }
    if (this.library.designs.length) {
      const group = element("optgroup");
      group.label = "saved";
      for (const saved of this.library.designs) group.append(new Option(saved.name, `saved:${saved.name}`));
      select.append(group);
    }
    if (current) select.value = current;
  }

  async startFrom(value) {
    $("designer-start").value = "";
    if (!value) return;
    const [kind, name] = [value.slice(0, value.indexOf(":")), value.slice(value.indexOf(":") + 1)];
    try {
      const design = await this.resolve(kind, name);
      await this.open(design, { saved: kind === "saved" ? name : null });
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  async resolve(kind, name) {
    if (kind === "preset") return command("design_preset", { name });
    if (kind === "saved") return command("design_get", { name });
    return command("design_new");
  }

  /** Make a design the current one (from a preset, the library, Claude or the sampler). */
  async open(design, { saved = null } = {}) {
    this.design = structuredClone(design);
    this.saved = saved;
    $("designer-name").value = this.design.name;
    $("designer-delete").hidden = !saved;
    this.controls.show(this.schema, this.design);
    this.showTab("design");
    await this.render();
  }

  async save() {
    if (!this.design) return;
    try {
      const name = await command("design_save", { design: this.design, name: $("designer-name").value.trim() || undefined });
      this.saved = name;
      $("designer-delete").hidden = false;
      await this.refreshLibrary();
      this.toast(`Saved “${name}”.`);
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  async deleteSaved() {
    if (!this.saved) return;
    try {
      await command("design_delete", { name: this.saved });
      this.toast(`Removed “${this.saved}” from the library.`);
      this.saved = null;
      $("designer-delete").hidden = true;
      await this.refreshLibrary();
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  // -- rendering ---------------------------------------------------------------------------

  renderSoon() {
    clearTimeout(this.renderTimer);
    this.renderTimer = setTimeout(() => this.render(), RENDER_DELAY_MS);
  }

  async render() {
    if (!this.design) return;
    const id = ++this.renderId;
    $("designer-status").textContent = "rendering…";
    try {
      const preview = await command("design_preview", { design: this.design });
      if (id !== this.renderId) return;   // a newer edit has already been sent
      this.preview = preview;
      this.buffer = await this.output.decode(preview.wav);
      $("designer-status").textContent = "";
      this.draw();
      this.showFacts();
      // The device's fingerprints are still being worked out; ask again when they're likely ready.
      if (preview.fingerprints.building) {
        clearTimeout(this.similarTimer);
        this.similarTimer = setTimeout(() => this.render(), 3000);
      }
      if ($("designer-hold").getAttribute("aria-pressed") === "true") this.play();
    } catch (error) {
      if (id !== this.renderId) return;
      $("designer-status").textContent = "";
      this.toast(error.message, true);
    }
  }

  draw() {
    if (!this.preview) return;
    const settings = this.preview.device.settings;
    const loop = settings["sound.loopstart"] >= 0
      ? { start: settings["sound.loopstart"], end: settings["sound.loopend"] } : null;
    drawWave($("designer-wave"), this.buffer, { loop, playhead: this.output.position() });
    const analysis = this.preview.analysis;
    drawSpectrum($("designer-spectrum"), analysis.spectrum, analysis.spectrum_range);
    drawSpectrogram($("designer-spectrogram"), analysis.spectrogram, analysis.spectrogram_range, analysis.seconds);
  }

  showFacts() {
    const { analysis, device, similar, fingerprints } = this.preview;
    const pitch = analysis.pitch;
    const pitched = pitch.frequency && pitch.confidence > 0.7;
    const settings = device.settings;
    const facts = [
      ["length", `${analysis.seconds.toFixed(3)} s`],
      ["pitch", pitched ? `${pitch.name} ${pitch.cents >= 0 ? "+" : ""}${Math.round(pitch.cents)}¢` : "unpitched"],
      ["loudness", `${formatDb(analysis.lufs)} LUFS`],
      ["peak", `${formatDb(analysis.peak_db)} dB`],
      ["brightness", `${Math.round(analysis.brightness)} Hz`],
      ["attack", `${Math.round(analysis.attack * 1000)} ms`],
      ["decay", `${analysis.decay.toFixed(2)} s`],
      ["mode", settings["sound.playmode"]],
      ["size", `${(device.bytes / 1024).toFixed(0)} KB`],
      ["upload", `≈ ${Math.max(1, Math.round(device.upload_seconds))} s`],
      ["channels", analysis.channels === 2 ? "stereo" : "mono"],
      ["root", settings["sound.rootnote"]],
    ];
    $("designer-facts").replaceChildren(...facts.flatMap(([name, value]) =>
      [element("dt", "", name), element("dd", "num", String(value))]));
    $("designer-notes").replaceChildren(...device.notes.map((note) => element("li", "", note)));
    const similarText = similar.length
      ? `closest on the device: ${similar.map((s) => `${s.slot} ${s.name}`).join(" · ")}`
      : fingerprints.building ? "comparing with the device's sounds…" : fingerprints.ready ? "" : "back up the device to compare with its sounds";
    $("designer-similar").textContent = similarText;
  }

  // -- playback ----------------------------------------------------------------------------

  play() {
    if (!this.buffer) return;
    const hold = $("designer-hold").getAttribute("aria-pressed") === "true";
    const settings = this.preview.device.settings;
    const loop = hold && settings["sound.loopstart"] >= 0
      ? { start: settings["sound.loopstart"], end: settings["sound.loopend"] } : null;
    this.output.play(this.buffer, { loop });
    this.animate();
  }

  animate() {
    cancelAnimationFrame(this.frame);
    const step = () => {
      this.draw();
      if (this.output.playing) this.frame = requestAnimationFrame(step);
    };
    this.frame = requestAnimationFrame(step);
  }

  async solo(layerIndex) {
    const single = { ...structuredClone(this.design), layers: [structuredClone(this.design.layers[layerIndex])] };
    single.instrument = { ...single.instrument, loop: "off" };
    try {
      const preview = await command("design_preview", { design: single, similar: false });
      this.output.play(await this.output.decode(preview.wav));
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  async fillOutputs() {
    const select = $("designer-output");
    const outputs = await this.output.outputs();
    select.replaceChildren(new Option("this computer", ""));
    for (const output of outputs) {
      if (!output.id) continue;
      select.append(new Option(output.isDevice ? `EP-133 · ${output.label}` : output.label, output.id));
    }
    select.disabled = !this.output.canChooseOutput;
    select.title = this.output.canChooseOutput
      ? "Play previews through the EP-133's own output to hear them as they'll sound on the device"
      : "This browser can't choose an output (Chrome and Edge can)";
    select.value = this.output.sinkId;
    if (select.value !== this.output.sinkId) select.value = "";
  }

  // -- exploring ---------------------------------------------------------------------------

  locks() {
    return [...document.querySelectorAll("#vary-locks input:checked")].map((input) => input.value);
  }

  async vary() {
    if (!this.design) return;
    const button = $("vary-btn");
    button.disabled = true;
    try {
      this.variations = await command("design_vary", {
        design: this.design, amount: Number($("vary-amount").value) / 100, locks: this.locks(), count: 6,
      });
      this.showVariations();
    } catch (error) {
      this.toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  showVariations() {
    const results = $("vary-results");
    results.replaceChildren();
    this.variations.forEach((variation, index) => {
      const tile = element("div", "vary-tile");
      const play = element("button", "btn small", `▶ ${index + 1}`);
      play.type = "button";
      play.addEventListener("click", async () => {
        try {
          const preview = await command("design_preview", { design: variation, similar: false });
          this.output.play(await this.output.decode(preview.wav));
        } catch (error) {
          this.toast(error.message, true);
        }
      });
      const use = element("button", "btn small ghost", "use");
      use.type = "button";
      use.title = "Make this the current sound (the original stays in “morph to”)";
      use.addEventListener("click", () => this.open(variation));
      tile.append(play, use);
      results.append(tile);
    });
  }

  async morph() {
    const value = $("morph-target").value;
    if (!value || !this.design) return;
    const [kind, name] = [value.slice(0, value.indexOf(":")), value.slice(value.indexOf(":") + 1)];
    try {
      const target = await this.resolve(kind, name);
      const morphed = await command("design_morph", { a: this.design, b: target, t: Number($("morph-amount").value) / 100 });
      await this.open(morphed);
    } catch (error) {
      this.toast(error.message, true);
    }
  }

  // -- uploading ---------------------------------------------------------------------------

  async upload() {
    if (!this.design) return;
    const slotInput = $("designer-slot");
    const button = $("designer-upload");
    const where = Number(slotInput.value) ? `slot ${Number(slotInput.value)}` : "the next free slot";
    if (!pressedTwice(button, `upload “${this.design.name}” to ${where}?`)) return;
    button.disabled = true;
    button.textContent = "uploading…";
    try {
      const result = await command("design_upload", { design: this.design, slot: Number(slotInput.value) || undefined });
      this.toast(result.message);
      slotInput.value = "";
      await this.refreshLibrary();
      this.onUploaded(result);
    } catch (error) {
      this.toast(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "⤒ upload to device";
    }
  }

  // -- events from the server ------------------------------------------------------------------

  onEvent(event) {
    if (event.type === "design" && event.design) {
      this.open(event.design).then(() => this.toast(`Claude opened “${event.design.name}” in the designer.`));
    } else if (event.type === "designs") {
      this.refreshLibrary();
    } else if (event.type === "kit") {
      this.kit.onEvent(event);
    }
  }
}
