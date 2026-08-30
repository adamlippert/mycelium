//
// The filter rules editor. Pure state functions first, DOM wiring below.
// The pure half has no DOM dependency so it can be tested with node --test,
// which is why it lives here rather than inline in templates/ui.html.

"use strict";

const STATE_NAMES = ["preferred", "excluded", "required", "included"];

function parseList(raw) {
  if (!raw) return [];
  return String(raw).split(",").map(v => v.trim()).filter(Boolean);
}

function serializeList(values) {
  return values.join(",");
}

function buildState(category, options, current, strict) {
  const states = {};
  STATE_NAMES.forEach(name => { states[name] = parseList(current[name]); });
  return { category, options: options.slice(), states, strict: Boolean(strict) };
}

function _clone(state) {
  const states = {};
  STATE_NAMES.forEach(name => { states[name] = state.states[name].slice(); });
  return { ...state, options: state.options.slice(), states };
}

function assign(state, value, stateName) {
  // A value holds at most one state per category. Assigning it elsewhere moves
  // it, so a user cannot accidentally build a config where one value is both
  // required and excluded.
  const next = _clone(state);
  STATE_NAMES.forEach(name => {
    next.states[name] = next.states[name].filter(v => v !== value);
  });
  if (stateName) next.states[stateName].push(value);
  return next;
}

function reorder(state, stateName, value, delta) {
  const next = _clone(state);
  const list = next.states[stateName];
  const from = list.indexOf(value);
  if (from === -1) return next;
  const to = from + delta;
  if (to < 0 || to >= list.length) return next;   // boundary, not an error
  list.splice(to, 0, list.splice(from, 1)[0]);
  return next;
}

function assignedValues(state) {
  return STATE_NAMES.flatMap(name => state.states[name]);
}

function availableFor(state) {
  const taken = new Set(assignedValues(state));
  return state.options.filter(v => !taken.has(v));
}

function invalidValues(state) {
  const known = new Set(state.options);
  return assignedValues(state).filter(v => !known.has(v));
}

function isEmpty(state) {
  // strict alone is not a rule, so it does not make a category non-empty.
  return STATE_NAMES.every(name => state.states[name].length === 0);
}

function toFormFields(state, prefix) {
  const fields = {};
  STATE_NAMES.forEach(name => {
    fields[`setting_${prefix}_${name.toUpperCase()}`] =
      serializeList(state.states[name]);
  });
  fields[`setting_${prefix}_STRICT`] = state.strict ? "true" : "false";
  return fields;
}

// Only language needs this. Every other vocabulary is already readable.
const LANGUAGE_NAMES = {
  ar: "Arabic", bg: "Bulgarian", cs: "Czech", da: "Danish", de: "German",
  el: "Greek", en: "English", es: "Spanish", fa: "Persian", fi: "Finnish",
  fr: "French", he: "Hebrew", hi: "Hindi", hr: "Croatian", hu: "Hungarian",
  id: "Indonesian", is: "Icelandic", it: "Italian", ja: "Japanese", ko: "Korean",
  lt: "Lithuanian", ms: "Malay", multi: "Multi", nl: "Dutch", no: "Norwegian",
  pl: "Polish", pt: "Portuguese", ro: "Romanian", ru: "Russian",
  sk: "Slovak", sl: "Slovenian", sv: "Swedish", ta: "Tamil", th: "Thai",
  tr: "Turkish", uk: "Ukrainian", vi: "Vietnamese", zh: "Chinese",
};

function displayValue(category, code) {
  if (category !== "language") return code;
  const name = LANGUAGE_NAMES[code];
  return name ? `${name} (${code})` : code;
}

const STATE_LABELS = {
  preferred: "Preferred", excluded: "Excluded",
  required: "Required", included: "Included",
};

function _chip(state, stateName, value, isInvalid, reorderable) {
  const chip = document.createElement("span");
  chip.className = "fr-chip" + (isInvalid ? " fr-chip-invalid" : "");
  chip.dataset.value = value;
  chip.dataset.state = stateName;

  if (reorderable) {
    // Arrows live on the chip itself. A single control acting on "the last
    // chip" cannot reach an arbitrary order: repeated clicks just swap the
    // final pair, because "last" is recomputed after every redraw.
    const left = document.createElement("button");
    left.type = "button";
    left.className = "fr-move";
    left.dataset.action = "move-left";
    left.textContent = "<";
    left.title = `Move ${value} earlier in the preference order`;
    chip.appendChild(left);
  }

  const label = document.createElement("span");
  label.className = "fr-chip-label";
  label.textContent = displayValue(state.category, value);
  chip.appendChild(label);

  if (reorderable) {
    const right = document.createElement("button");
    right.type = "button";
    right.className = "fr-move";
    right.dataset.action = "move-right";
    right.textContent = ">";
    right.title = `Move ${value} later in the preference order`;
    chip.appendChild(right);
  }

  if (isInvalid) {
    chip.title = `${value} is not a valid ${state.category} value. It was ` +
                 `probably set in .env before the vocabulary changed. ` +
                 `It matches nothing. Remove it.`;
  }

  const x = document.createElement("button");
  x.type = "button";
  x.className = "fr-chip-remove";
  x.textContent = "x";
  x.dataset.action = "remove";
  chip.appendChild(x);
  return chip;
}

function renderPanel(state, prefix) {
  const invalid = new Set(invalidValues(state));
  const panel = document.createElement("div");
  panel.className = "fr-panel";
  panel.dataset.category = state.category;
  panel.dataset.prefix = prefix;

  const head = document.createElement("div");
  head.className = "fr-panel-head";
  head.innerHTML =
    `<strong>${state.category.replace("_", " ").toUpperCase()}</strong>` +
    `<span class="dim fr-count">${state.options.length} values</span>`;
  const strict = document.createElement("label");
  strict.className = "fr-strict";
  strict.innerHTML =
    `<input type="checkbox" data-action="strict"${state.strict ? " checked" : ""}> strict`;
  strict.title = "Hold this category's rules even when that leaves no " +
                 "candidates at all. Off means the rules relax rather than " +
                 "return nothing.";
  head.appendChild(strict);
  panel.appendChild(head);

  STATE_NAMES.forEach(name => {
    const row = document.createElement("div");
    row.className = "fr-row";
    row.dataset.state = name;

    const label = document.createElement("span");
    label.className = "fr-row-label";
    label.textContent = STATE_LABELS[name];
    row.appendChild(label);

    const chips = document.createElement("span");
    chips.className = "fr-chips";
    const values = state.states[name];
    if (values.length === 0) {
      const none = document.createElement("span");
      none.className = "dim";
      none.textContent = "(none)";
      chips.appendChild(none);
    } else {
      values.forEach(v => chips.appendChild(
        _chip(state, name, v, invalid.has(v), name === "preferred")));
    }
    row.appendChild(chips);

    const add = document.createElement("select");
    add.className = "fr-add";
    add.dataset.action = "add";
    add.innerHTML = `<option value="">+ add</option>` +
      availableFor(state).map(v =>
        `<option value="${v}">${displayValue(state.category, v)}</option>`).join("");
    row.appendChild(add);

    if (name === "included") {
      const warn = document.createElement("span");
      warn.className = "fr-warn";
      warn.textContent = "! overrides every other rule";
      warn.title = "An included value keeps a release no matter what any " +
                   "other rule says, in any category. Marking atmos as " +
                   "included will keep a cam rip that happens to carry Atmos.";
      row.appendChild(warn);
    }

    panel.appendChild(row);
  });

  return panel;
}

function renderCollapsed(state, prefix) {
  const row = document.createElement("div");
  row.className = "fr-collapsed";
  row.dataset.category = state.category;
  row.dataset.prefix = prefix;
  row.innerHTML =
    `<button type="button" data-action="expand" class="fr-expand">&gt;</button>` +
    `<strong>${state.category.replace("_", " ").toUpperCase()}</strong>` +
    `<span class="dim">no rules set</span>` +
    `<span class="dim fr-count">${state.options.length} values</span>`;
  return row;
}

function syncHiddenInputs(state, prefix, form) {
  // Rewrites every field for this category from one state object. Mutating
  // fields individually is how a chip view and its hidden inputs drift apart.
  const fields = toFormFields(state, prefix);
  Object.keys(fields).forEach(name => {
    const input = form.querySelector(`[name="${name}"]`);
    if (input) input.value = fields[name];
  });
}

function initFilterRules(group, container) {
  const form = document.getElementById("settings-form");
  const byPrefix = {};

  // all_for_ui sends 35 flat keys. Fold them into seven category states.
  group.items.forEach(item => {
    const m = item.key.match(/^(.*)_(PREFERRED|EXCLUDED|REQUIRED|INCLUDED|STRICT)$/);
    if (!m) return;
    const [, prefix, suffix] = m;
    byPrefix[prefix] = byPrefix[prefix] || { current: {}, options: [], strict: false };
    if (suffix === "STRICT") {
      byPrefix[prefix].strict = Boolean(item.value);
    } else {
      byPrefix[prefix].current[suffix.toLowerCase()] =
        Array.isArray(item.value) ? item.value.join(",") : item.value;
      if (item.options && item.options.length) byPrefix[prefix].options = item.options;
    }
  });

  const states = {};
  Object.keys(byPrefix).forEach(prefix => {
    const raw = byPrefix[prefix];
    states[prefix] = buildState(prefix.toLowerCase(), raw.options, raw.current, raw.strict);
  });

  function hidden(name, value) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    return input;
  }

  function draw() {
    container.innerHTML = "";
    Object.keys(states).forEach(prefix => {
      const state = states[prefix];
      const expanded = container.dataset[`open_${prefix}`] === "1" || !isEmpty(state);
      const node = expanded ? renderPanel(state, prefix) : renderCollapsed(state, prefix);
      container.appendChild(node);
      // The hidden inputs live outside the redrawn node so a redraw cannot
      // destroy them mid-edit.
      Object.entries(toFormFields(state, prefix)).forEach(([name, value]) => {
        let input = form.querySelector(`[name="${name}"]`);
        if (!input) { input = hidden(name, value); form.appendChild(input); }
        else { input.value = value; }
      });
    });
  }

  container.addEventListener("click", ev => {
    const action = ev.target.dataset && ev.target.dataset.action;
    if (!action) return;
    const holder = ev.target.closest("[data-prefix]");
    if (!holder) return;
    const prefix = holder.dataset.prefix;

    if (action === "expand") {
      container.dataset[`open_${prefix}`] = "1";
    } else if (action === "remove") {
      const chip = ev.target.closest(".fr-chip");
      states[prefix] = assign(states[prefix], chip.dataset.value, null);
    } else if (action === "move-left" || action === "move-right") {
      const chip = ev.target.closest(".fr-chip");
      states[prefix] = reorder(states[prefix], "preferred", chip.dataset.value,
                               action === "move-left" ? -1 : 1);
    } else {
      return;
    }
    syncHiddenInputs(states[prefix], prefix, form);
    draw();
    form.dispatchEvent(new Event("input"));
  });

  container.addEventListener("change", ev => {
    const action = ev.target.dataset && ev.target.dataset.action;
    if (!action) return;
    const holder = ev.target.closest("[data-prefix]");
    if (!holder) return;
    const prefix = holder.dataset.prefix;

    if (action === "add" && ev.target.value) {
      const row = ev.target.closest("[data-state]");
      states[prefix] = assign(states[prefix], ev.target.value, row.dataset.state);
    } else if (action === "strict") {
      states[prefix] = { ...states[prefix], strict: ev.target.checked };
    } else {
      return;
    }
    syncHiddenInputs(states[prefix], prefix, form);
    draw();
    form.dispatchEvent(new Event("input"));
  });

  draw();
}

const _api = { STATE_NAMES, parseList, serializeList, buildState, assign,
               reorder, availableFor, invalidValues, isEmpty, toFormFields,
               displayValue, LANGUAGE_NAMES, STATE_LABELS, renderPanel,
               renderCollapsed, syncHiddenInputs, initFilterRules };

if (typeof module !== "undefined" && module.exports) module.exports = _api;
if (typeof window !== "undefined") window.FilterRules = _api;
