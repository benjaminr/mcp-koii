// A layout you can rearrange. Press "layout" in the top bar to move modules (drag a header,
// or use ← →), resize them (drag the corner: sideways in columns, down in pixels), and hide
// them. Inside modules, parts can be reordered, hidden or made wide, and two-column bodies
// can be split differently. Collapsing a module works at any time. The layout is kept in
// this browser only.
//
// Modules sit on a 12-column grid of 4 px rows. Each module spans as many rows as it is
// tall, so modules of different heights pack together without leaving gaps under the
// shorter ones. A module marked data-fill (the log) also stretches down to line up with
// the bottom of the modules beside it, and its [data-grow] part scrolls inside.

const STORAGE_KEY = "koii.layout.v1";
const COLUMNS = 12;
const ROW_UNIT_PX = 4;
const MIN_SPAN = 2;
const MIN_HEIGHT_PX = 120;
const MIN_SPLIT = 0.2;
const MAX_SPLIT = 0.8;
const NARROW_PX = 800;    // below this, every module is full width
const MEDIUM_PX = 1240;   // below this, modules are half or full width
const SPLIT_FROM_PX = 1100;  // two-column bodies stack below this, so splits don't apply

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function toolButton(label, title, onClick) {
  const button = element("button", "layout-tool", label);
  button.type = "button";
  button.title = title;
  button.setAttribute("aria-label", title);
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    onClick();
  });
  return button;
}

/** The module's name as its header shows it, without the number or the tools. */
function moduleTitle(module) {
  const head = module.querySelector(":scope > .module-head");
  const words = [...head.childNodes].filter((node) => node.nodeType === Node.TEXT_NODE).map((node) => node.textContent);
  return words.join("").trim() || module.dataset.module;
}

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

function emptyLayout() {
  return { order: [], modules: {}, regions: {}, splits: {} };
}

function loadLayout(key) {
  try {
    const saved = JSON.parse(localStorage.getItem(key));
    return saved && typeof saved === "object" ? { ...emptyLayout(), ...saved } : emptyLayout();
  } catch {
    return emptyLayout();
  }
}

export class LayoutEditor {
  /**
   * page: the element whose children are the modules ([data-module], with data-span for the
   * default width). bar: the bar shown while editing. toggle: the button that starts editing.
   * Each view has its own editor: key is where its layout is kept, and isActive() says whether
   * it's the view on screen (reset and the hidden list only act on that one).
   */
  constructor({ page, bar, toggle, key = STORAGE_KEY, isActive = () => true }) {
    this.page = page;
    this.bar = bar;
    this.toggle = toggle;
    this.key = key;
    this.isActive = isActive;
    this.editing = false;
    this.saved = loadLayout(key);
    this.modules = [...page.querySelectorAll(":scope > [data-module]")];
    this.defaults = new Map(this.modules.map((module, index) => [module.dataset.module, {
      order: index, span: Number(module.dataset.span) || COLUMNS,
    }]));
    this.dragging = null;

    const measure = new ResizeObserver((entries) => {
      entries.forEach((entry) => this._fitRows(entry.target));
      this._fill();
    });
    for (const module of this.modules) {
      this._addModuleTools(module);
      measure.observe(module);
    }
    for (const container of page.querySelectorAll("[data-regions]")) this._addRegionTools(container);
    for (const container of page.querySelectorAll("[data-split]")) this._addSplitHandle(container);

    toggle.addEventListener("click", () => this.setEditing(!this.editing));
    bar.querySelector("[data-layout=done]").addEventListener("click", () => this.setEditing(false));
    bar.querySelector("[data-layout=reset]").addEventListener("click", () => {
      if (this.isActive()) this.reset();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.editing) this.setEditing(false);
    });
    document.addEventListener("pointermove", (event) => this._dragMove(event));
    document.addEventListener("pointerup", () => this._dragEnd());
    document.addEventListener("pointercancel", () => this._dragEnd());
    window.addEventListener("resize", () => this.apply());
    this.apply();
    page.classList.add("packed");
  }

  setEditing(on) {
    this.editing = on;
    document.body.classList.toggle("layout-editing", on);
    this.toggle.setAttribute("aria-pressed", String(on));
    this.bar.hidden = !on;
    this._renderHidden();
  }

  reset() {
    this.saved = emptyLayout();
    this._save();
    for (const container of this.page.querySelectorAll("[data-split]")) container.style.gridTemplateColumns = "";
    this.apply();
  }

  // -- applying the saved layout ------------------------------------------------------

  apply() {
    const order = this._order();
    for (const module of this.modules) {
      const id = module.dataset.module;
      const settings = this._moduleSettings(id);
      module.style.order = String(order.indexOf(id));
      module.style.setProperty("--span", this._effectiveSpan(settings.span));
      module.style.height = settings.height ? `${settings.height}px` : "";
      module.classList.toggle("sized", Boolean(settings.height));
      module.classList.toggle("collapsed", Boolean(settings.collapsed));
      module.hidden = Boolean(settings.hidden);
      const collapse = module.querySelector(":scope > .module-head .collapse-tool");
      collapse.textContent = settings.collapsed ? "▸" : "▾";
      collapse.title = settings.collapsed ? "Expand" : "Collapse";
      this._fitRows(module);
    }
    for (const container of this.page.querySelectorAll("[data-regions]")) this._applyRegions(container);
    for (const container of this.page.querySelectorAll("[data-split]")) this._applySplit(container);
    this._renderHidden();
    this._fill();
  }

  /**
   * Stretch data-fill modules down to the lowest bottom of the modules beside them that
   * start no lower, so a short log doesn't leave a gap next to a tall device panel.
   * Modules given a height by hand, collapsed ones, and narrow screens are left alone.
   */
  _fill() {
    for (const module of this.modules.filter((candidate) => candidate.hasAttribute("data-fill"))) {
      const settings = this._moduleSettings(module.dataset.module);
      const allowed = !module.hidden && !settings.height && !settings.collapsed && window.innerWidth >= MEDIUM_PX;
      const wasFilled = module.classList.contains("filled");
      if (wasFilled) {
        module.style.height = "";
        module.classList.remove("filled");
      }
      if (!allowed) {
        if (wasFilled) this._fitRows(module);
        continue;
      }
      const own = module.getBoundingClientRect();
      let bottom = own.bottom;
      for (const other of this.modules) {
        if (other === module || other.hidden) continue;
        const rect = other.getBoundingClientRect();
        const beside = rect.right <= own.left + 1 || rect.left >= own.right - 1;
        if (beside && rect.top <= own.top + 1) bottom = Math.max(bottom, rect.bottom);
      }
      if (bottom > own.bottom + 2) {
        module.style.height = `${Math.round(bottom - own.top)}px`;
        module.classList.add("filled");
      }
      this._fitRows(module);
    }
  }

  _order() {
    const ids = this.modules.map((module) => module.dataset.module);
    const known = (this.saved.order || []).filter((id) => ids.includes(id));
    const missing = ids.filter((id) => !known.includes(id))
      .sort((a, b) => this.defaults.get(a).order - this.defaults.get(b).order);
    // Modules added since the layout was saved go in at their default place.
    for (const id of missing) known.splice(Math.min(this.defaults.get(id).order, known.length), 0, id);
    return known;
  }

  _moduleSettings(id) {
    return { span: this.defaults.get(id).span, ...(this.saved.modules[id] || {}) };
  }

  _changeModule(id, change) {
    this.saved.modules[id] = { ...(this.saved.modules[id] || {}), ...change };
    this._save();
    this.apply();
  }

  _effectiveSpan(span) {
    const width = window.innerWidth;
    if (width < NARROW_PX) return COLUMNS;
    if (width < MEDIUM_PX) return span <= COLUMNS / 2 ? COLUMNS / 2 : COLUMNS;
    return span;
  }

  /** Give a module as many grid rows as it is tall, plus the gap below it. */
  _fitRows(module) {
    if (module.hidden) return;
    const gap = parseFloat(getComputedStyle(module).marginBottom) || 0;
    const rows = Math.ceil((module.getBoundingClientRect().height + gap) / ROW_UNIT_PX);
    if (module.style.getPropertyValue("--rows") !== String(rows)) module.style.setProperty("--rows", rows);
  }

  _save() {
    try {
      localStorage.setItem(this.key, JSON.stringify(this.saved));
    } catch {
      // Private windows can refuse storage; the layout still works until the page reloads.
    }
  }

  // -- module tools ---------------------------------------------------------------------

  _addModuleTools(module) {
    const id = module.dataset.module;
    const head = module.querySelector(":scope > .module-head");
    const tools = element("span", "module-tools");
    const editTools = element("span", "layout-only");
    editTools.append(
      toolButton("←", "Move earlier", () => this._move(id, -1)),
      toolButton("→", "Move later", () => this._move(id, 1)),
      toolButton("−", "Narrower", () => this._resizeBy(id, -1)),
      toolButton("+", "Wider", () => this._resizeBy(id, 1)),
      toolButton("hide", "Hide this module", () => this._changeModule(id, { hidden: true })),
    );
    const collapse = toolButton("▾", "Collapse", () =>
      this._changeModule(id, { collapsed: !this._moduleSettings(id).collapsed }));
    collapse.classList.add("collapse-tool");
    tools.append(editTools, collapse);
    head.append(tools);

    head.addEventListener("pointerdown", (event) => this._startMove(event, module));
    const handle = element("div", "resize-handle layout-only");
    handle.title = "Drag to resize · double-click to fit the content";
    handle.addEventListener("pointerdown", (event) => this._startResize(event, module));
    handle.addEventListener("dblclick", () => this._changeModule(id, { height: null }));
    module.append(handle);
  }

  _move(id, delta) {
    const order = this._order();
    const visible = order.filter((other) => !this._moduleSettings(other).hidden);
    const from = visible.indexOf(id);
    const to = clamp(from + delta, 0, visible.length - 1);
    if (from === to) return;
    const neighbour = visible[to];
    order.splice(order.indexOf(id), 1);
    order.splice(order.indexOf(neighbour) + (delta > 0 ? 1 : 0), 0, id);
    this.saved.order = order;
    this._save();
    this.apply();
  }

  _resizeBy(id, delta) {
    const span = clamp(this._moduleSettings(id).span + delta, MIN_SPAN, COLUMNS);
    this._changeModule(id, { span });
  }

  _columnWidth() {
    const style = getComputedStyle(this.page);
    const gap = parseFloat(style.columnGap) || 0;
    const inner = this.page.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    return { column: (inner - gap * (COLUMNS - 1)) / COLUMNS, gap };
  }

  // -- dragging: moving and resizing -------------------------------------------------------

  _startMove(event, module) {
    if (!this.editing || event.button !== 0 || event.target.closest("button, input, select, a")) return;
    event.preventDefault();
    module.classList.add("moving");
    this.dragging = { kind: "move", module, target: null, after: false };
  }

  _startResize(event, module) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = module.getBoundingClientRect();
    this.dragging = {
      kind: "resize", module, x: event.clientX, y: event.clientY,
      width: rect.width, height: rect.height, heightChanged: false,
    };
    module.classList.add("resizing");
  }

  _dragMove(event) {
    const drag = this.dragging;
    if (!drag) return;
    if (drag.kind === "move") this._moveOver(event, drag);
    else if (drag.kind === "resize") this._resizeTo(event, drag);
    else if (drag.kind === "split") this._splitTo(event, drag);
  }

  _moveOver(event, drag) {
    const target = this.modules.find((module) => {
      if (module === drag.module || module.hidden) return false;
      const rect = module.getBoundingClientRect();
      return event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
    });
    if (!target) return;
    const rect = target.getBoundingClientRect();
    // Full-width modules stack, so above or below; narrower ones sit side by side.
    const fullWidth = rect.width > this.page.clientWidth * 0.75;
    const after = fullWidth ? event.clientY > rect.top + rect.height / 2 : event.clientX > rect.left + rect.width / 2;
    drag.target?.classList.remove("drop-before", "drop-after");
    target.classList.add(after ? "drop-after" : "drop-before");
    target.classList.toggle("drop-vertical", fullWidth);
    Object.assign(drag, { target, after });
  }

  _resizeTo(event, drag) {
    const { column, gap } = this._columnWidth();
    const id = drag.module.dataset.module;
    const span = clamp(Math.round((drag.width + event.clientX - drag.x + gap) / (column + gap)), MIN_SPAN, COLUMNS);
    const dy = event.clientY - drag.y;
    if (Math.abs(dy) > 6) drag.heightChanged = true;
    const settings = this.saved.modules[id] = { ...(this.saved.modules[id] || {}), span };
    if (drag.heightChanged) settings.height = Math.round(Math.max(MIN_HEIGHT_PX, drag.height + dy));
    this.apply();
  }

  _dragEnd() {
    const drag = this.dragging;
    if (!drag) return;
    this.dragging = null;
    drag.module?.classList.remove("moving", "resizing");
    if (drag.kind === "move" && drag.target) {
      drag.target.classList.remove("drop-before", "drop-after", "drop-vertical");
      const order = this._order();
      const id = drag.module.dataset.module;
      order.splice(order.indexOf(id), 1);
      order.splice(order.indexOf(drag.target.dataset.module) + (drag.after ? 1 : 0), 0, id);
      this.saved.order = order;
      this.apply();
    }
    if (drag.kind === "split") drag.container.classList.remove("splitting");
    this._save();
  }

  // -- parts inside modules ------------------------------------------------------------------

  _regionSettings(container) {
    const saved = this.saved.regions[container.dataset.regions] || {};
    const markedWide = [...container.querySelectorAll(":scope > [data-region][data-wide]")].map((part) => part.dataset.region);
    return { order: saved.order || [], hidden: saved.hidden || [], wide: saved.wide || markedWide };
  }

  _changeRegions(container, change) {
    this.saved.regions[container.dataset.regions] = { ...this._regionSettings(container), ...change };
    this._save();
    this.apply();
  }

  _regionOrder(container) {
    const names = [...container.querySelectorAll(":scope > [data-region]")].map((part) => part.dataset.region);
    const saved = this._regionSettings(container).order.filter((name) => names.includes(name));
    return [...saved, ...names.filter((name) => !saved.includes(name))];
  }

  _addRegionTools(container) {
    const wideAllowed = container.hasAttribute("data-regions-wide");
    for (const part of container.querySelectorAll(":scope > [data-region]")) {
      const name = part.dataset.region;
      const tools = element("span", "region-tools layout-only");
      tools.append(element("span", "region-name", part.dataset.regionLabel || name));
      tools.append(
        toolButton("↑", "Move earlier", () => this._moveRegion(container, name, -1)),
        toolButton("↓", "Move later", () => this._moveRegion(container, name, 1)),
      );
      if (wideAllowed) {
        tools.append(toolButton("↔", "Full width or normal", () => {
          const { wide } = this._regionSettings(container);
          this._changeRegions(container, { wide: wide.includes(name) ? wide.filter((other) => other !== name) : [...wide, name] });
        }));
      }
      tools.append(toolButton("hide", "Hide this part", () =>
        this._changeRegions(container, { hidden: [...this._regionSettings(container).hidden, name] })));
      part.classList.add("region");
      part.prepend(tools);
    }
  }

  _moveRegion(container, name, delta) {
    const order = this._regionOrder(container);
    const from = order.indexOf(name);
    const to = clamp(from + delta, 0, order.length - 1);
    order.splice(from, 1);
    order.splice(to, 0, name);
    this._changeRegions(container, { order });
  }

  _applyRegions(container) {
    const order = this._regionOrder(container);
    const { hidden, wide } = this._regionSettings(container);
    for (const part of container.querySelectorAll(":scope > [data-region]")) {
      const name = part.dataset.region;
      part.style.order = String(order.indexOf(name));
      part.classList.toggle("region-hidden", hidden.includes(name));
      if (container.hasAttribute("data-regions-wide")) part.classList.toggle("region-wide", wide.includes(name));
    }
  }

  // -- two-column splits -----------------------------------------------------------------

  _addSplitHandle(container) {
    const handle = element("div", "split-handle layout-only");
    handle.title = "Drag to change the split · double-click to reset";
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      container.classList.add("splitting");
      this.dragging = { kind: "split", container };
    });
    handle.addEventListener("dblclick", () => {
      delete this.saved.splits[container.dataset.split];
      this._save();
      this.apply();
    });
    container.append(handle);
  }

  _splitTo(event, drag) {
    const rect = drag.container.getBoundingClientRect();
    this.saved.splits[drag.container.dataset.split] = clamp((event.clientX - rect.left) / rect.width, MIN_SPLIT, MAX_SPLIT);
    this.apply();
  }

  _applySplit(container) {
    const fraction = this.saved.splits[container.dataset.split];
    const applies = fraction && window.innerWidth >= SPLIT_FROM_PX;
    container.style.gridTemplateColumns = applies
      ? `minmax(0, ${fraction.toFixed(3)}fr) minmax(0, ${(1 - fraction).toFixed(3)}fr)` : "";
    const handle = container.querySelector(":scope > .split-handle");
    const first = container.querySelector(":scope > :not(.split-handle)");
    handle.hidden = window.innerWidth < SPLIT_FROM_PX || !first;
    if (first) {
      const gap = parseFloat(getComputedStyle(container).columnGap) || 0;
      handle.style.left = `${first.offsetLeft + first.offsetWidth + gap / 2}px`;
    }
  }

  // -- what's hidden ---------------------------------------------------------------------

  /** The view has just come on screen: measure it again and show its hidden list. */
  show() {
    this.apply();
  }

  _renderHidden() {
    if (!this.isActive()) return;
    const list = this.bar.querySelector("[data-layout=hidden]");
    list.replaceChildren();
    for (const module of this.modules) {
      if (!this._moduleSettings(module.dataset.module).hidden) continue;
      const name = moduleTitle(module);
      list.append(toolButton(`+ ${name}`, `Show ${name} again`, () => this._changeModule(module.dataset.module, { hidden: false })));
    }
    for (const container of this.page.querySelectorAll("[data-regions]")) {
      for (const name of this._regionSettings(container).hidden) {
        const part = container.querySelector(`:scope > [data-region="${name}"]`);
        if (!part) continue;
        const label = part.dataset.regionLabel || name;
        list.append(toolButton(`+ ${label}`, `Show ${label} again`, () =>
          this._changeRegions(container, { hidden: this._regionSettings(container).hidden.filter((other) => other !== name) })));
      }
    }
    list.hidden = !list.childElementCount;
  }
}
