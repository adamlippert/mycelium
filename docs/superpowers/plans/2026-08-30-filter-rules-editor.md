# C2 Filter Rules Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 35 comma-separated text boxes in the admin settings page with seven per-category panels where each value is a chip carrying one state.

**Architecture:** All logic lives in a new `static/admin/filter_rules.js`, because `templates/ui.html` is already 2205 lines with every script inline and no test coverage. The pure state functions have no DOM dependency and are tested with `node --test`, which ships with Node 22 and needs no packages. Chips are a view over hidden `setting_KEY` inputs holding the same comma-separated strings as today, so the existing `/ui/settings` handler is untouched.

**Tech Stack:** Vanilla JavaScript (no framework, no build step), Jinja2, `node --test`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-filter-rules-editor-design.md`

## Global Constraints

- **No em-dashes anywhere**, in code, comments, strings, commit messages, or documentation. Use a spaced hyphen or restructure. Project rule from `CLAUDE.md`.
- **No `Co-Authored-By` lines in commit messages.**
- **Never edit `.env.example`.** It is under a permission deny rule.
- The repository is **public**. No API keys, tokens, passwords, or IP addresses.
- Work on branch `feat/filter-rules-editor`, cut from `feat/inclusive-filter-model` (NOT from `main`; C1 is not merged).
- Python tests: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/ -q`
- JavaScript tests: `node --test tests/js/*.test.js`
- No new runtime dependencies, and no build step. The admin UI is served as a plain Jinja template.

## Key facts, verified against the running code

- `app.py:95` is `Flask(__name__, static_folder="static", static_url_path="/static")`, so `static/admin/filter_rules.js` is served at `/static/admin/filter_rules.js`. Nothing in `templates/ui.html` currently loads a static asset; this is the first.
- `settings.all_for_ui()` already returns, for each of the 35 rule keys: `options` (the full vocabulary), `hot_reload: true`, `kind: "list"`, and the current `value`.
- The renderer in `templates/ui.html` already special-cases a group by id. The `mode` group ends its branch with `return; // skip normal rendering for mode group`. C2 uses that same shape for `filter_rules`.
- `/ui/settings` loops over form keys beginning `setting_` and calls `settings.set(key, value)`. C2 must keep emitting exactly those names.

## The state model

One value belongs to at most one state per category. Assigning a value to a
state moves it out of any other. This is a deliberate narrowing of what the
engine permits: the engine resolves a value that is both `required` and
`excluded` by precedence, but there is no reason to let a user build that
config by accident.

```js
{
  category: "resolution",
  options: ["2160p", "1080p", "720p", "480p", "unknown"],
  states: { preferred: ["1080p"], excluded: ["480p"], required: [], included: [] },
  strict: false,
}
```

## File Structure

| File | Responsibility |
|---|---|
| `static/admin/filter_rules.js` (new) | Everything. Pure state functions first, DOM wiring after, one `initFilterRules(group)` export. |
| `tests/js/filter_rules.test.js` (new) | `node --test`. Covers the pure functions only. |
| `tests/test_filter_rules_ui.py` (new) | Guards the backend contract the JS depends on. |
| `templates/ui.html` | About twelve lines: a script tag and the `filter_rules` branch. |

---

### Task 1: The pure state model

**Files:**
- Create: `static/admin/filter_rules.js`
- Create: `tests/js/filter_rules.test.js`

**Interfaces:**
- Consumes: nothing.
- Produces: `parseList(str) -> string[]`; `serializeList(arr) -> string`;
  `buildState(item4, strictValue) -> State`; `assign(state, value, stateName|null) -> State`;
  `reorder(state, stateName, value, delta) -> State`;
  `availableFor(state) -> string[]`; `invalidValues(state) -> string[]`;
  `isEmpty(state) -> boolean`; `toFormFields(state, prefix) -> Record<string,string>`.
  All are pure: they return a new state and never mutate the argument.

- [ ] **Step 1: Write the failing test**

```js
// tests/js/filter_rules.test.js
const test = require("node:test");
const assert = require("node:assert");
const fr = require("../../static/admin/filter_rules.js");

const OPTIONS = ["2160p", "1080p", "720p", "480p", "unknown"];

function state(overrides = {}) {
  return {
    category: "resolution",
    options: OPTIONS,
    states: { preferred: [], excluded: [], required: [], included: [] },
    strict: false,
    ...overrides,
  };
}

test("parseList splits, trims and drops empties", () => {
  assert.deepStrictEqual(fr.parseList("1080p, 2160p ,"), ["1080p", "2160p"]);
  assert.deepStrictEqual(fr.parseList(""), []);
  assert.deepStrictEqual(fr.parseList(null), []);
});

test("serializeList round-trips through parseList", () => {
  const values = ["1080p", "2160p", "720p"];
  assert.deepStrictEqual(fr.parseList(fr.serializeList(values)), values);
});

test("assign puts a value into a state", () => {
  const s = fr.assign(state(), "1080p", "preferred");
  assert.deepStrictEqual(s.states.preferred, ["1080p"]);
});

test("assign moves a value rather than duplicating it", () => {
  let s = fr.assign(state(), "1080p", "preferred");
  s = fr.assign(s, "1080p", "excluded");
  assert.deepStrictEqual(s.states.preferred, [], "left behind in the old state");
  assert.deepStrictEqual(s.states.excluded, ["1080p"]);
});

test("assign with a null state removes the value entirely", () => {
  let s = fr.assign(state(), "1080p", "preferred");
  s = fr.assign(s, "1080p", null);
  assert.deepStrictEqual(s.states.preferred, []);
});

test("assign does not mutate the input state", () => {
  const original = state();
  fr.assign(original, "1080p", "preferred");
  assert.deepStrictEqual(original.states.preferred, [],
    "the caller's state was mutated");
});

test("assign appends, preserving order", () => {
  let s = fr.assign(state(), "2160p", "preferred");
  s = fr.assign(s, "1080p", "preferred");
  assert.deepStrictEqual(s.states.preferred, ["2160p", "1080p"]);
});

test("reorder moves a value within its state", () => {
  let s = state({ states: { preferred: ["2160p", "1080p", "720p"],
                            excluded: [], required: [], included: [] } });
  s = fr.reorder(s, "preferred", "1080p", -1);
  assert.deepStrictEqual(s.states.preferred, ["1080p", "2160p", "720p"]);
});

test("reorder at a boundary is a no-op, not an error", () => {
  const s = state({ states: { preferred: ["2160p", "1080p"],
                              excluded: [], required: [], included: [] } });
  assert.deepStrictEqual(fr.reorder(s, "preferred", "2160p", -1).states.preferred,
                         ["2160p", "1080p"]);
  assert.deepStrictEqual(fr.reorder(s, "preferred", "1080p", 1).states.preferred,
                         ["2160p", "1080p"]);
});

test("availableFor excludes values already assigned anywhere in the category", () => {
  let s = fr.assign(state(), "1080p", "preferred");
  s = fr.assign(s, "480p", "excluded");
  assert.deepStrictEqual(fr.availableFor(s), ["2160p", "720p", "unknown"]);
});

test("invalidValues finds a stored value absent from the vocabulary", () => {
  const s = state({ states: { preferred: ["1080p", "4k"],
                              excluded: [], required: [], included: [] } });
  assert.deepStrictEqual(fr.invalidValues(s), ["4k"]);
});

test("an invalid value is never offered by availableFor", () => {
  const s = state({ states: { preferred: ["4k"],
                              excluded: [], required: [], included: [] } });
  assert.ok(!fr.availableFor(s).includes("4k"));
});

test("isEmpty is true only when every state is empty", () => {
  assert.ok(fr.isEmpty(state()));
  assert.ok(!fr.isEmpty(fr.assign(state(), "1080p", "preferred")));
});

test("isEmpty ignores strict, which is not a rule on its own", () => {
  assert.ok(fr.isEmpty(state({ strict: true })));
});

test("toFormFields emits exactly the setting_ names the save endpoint reads", () => {
  const s = fr.assign(state(), "1080p", "preferred");
  const fields = fr.toFormFields(s, "RESOLUTION");
  assert.deepStrictEqual(fields, {
    setting_RESOLUTION_PREFERRED: "1080p",
    setting_RESOLUTION_EXCLUDED: "",
    setting_RESOLUTION_REQUIRED: "",
    setting_RESOLUTION_INCLUDED: "",
    setting_RESOLUTION_STRICT: "false",
  });
});

test("toFormFields preserves preferred order", () => {
  let s = fr.assign(state(), "2160p", "preferred");
  s = fr.assign(s, "1080p", "preferred");
  assert.strictEqual(fr.toFormFields(s, "RESOLUTION").setting_RESOLUTION_PREFERRED,
                     "2160p,1080p");
});

test("toFormFields keeps an invalid value rather than silently dropping it", () => {
  const s = state({ states: { preferred: ["4k"],
                              excluded: [], required: [], included: [] } });
  assert.strictEqual(fr.toFormFields(s, "RESOLUTION").setting_RESOLUTION_PREFERRED,
                     "4k");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test tests/js/*.test.js`
Expected: FAIL, `Cannot find module '../../static/admin/filter_rules.js'`

- [ ] **Step 3: Write the minimal implementation**

```js
// static/admin/filter_rules.js
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

const _api = { STATE_NAMES, parseList, serializeList, buildState, assign,
               reorder, availableFor, invalidValues, isEmpty, toFormFields };

if (typeof module !== "undefined" && module.exports) module.exports = _api;
if (typeof window !== "undefined") window.FilterRules = _api;
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test tests/js/*.test.js`
Expected: PASS, 17 tests

- [ ] **Step 5: Verify the move semantics test has teeth**

Change `assign` so it appends without first removing the value from other
states, confirm with grep that the edit landed, and re-run.
`assign moves a value rather than duplicating it` MUST fail. If it passes, the
test is not pinning the behaviour and you should report that rather than
proceeding. Restore and confirm green.

- [ ] **Step 6: Confirm pytest still ignores the JS directory**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/ -q`
Expected: PASS, the same count as before this task. pytest collects only
`test_*.py`, so `tests/js/*.js` is invisible to it, but confirm rather than
assume.

- [ ] **Step 7: Commit**

```bash
git add static/admin/filter_rules.js tests/js/filter_rules.test.js
git commit -m "feat(ui): pure state model for the filter rules editor"
```

---

### Task 2: Language display names

**Files:**
- Modify: `static/admin/filter_rules.js`
- Modify: `tests/js/filter_rules.test.js`

**Interfaces:**
- Consumes: nothing from Task 1 beyond the module itself.
- Produces: `displayValue(category, code) -> string`.

The language vocabulary is 35 ISO codes. A picker showing `ar, bg, cs, da, de`
is a puzzle. Every other category's values are already self-describing
(`2160p`, `webdl`, `atmos`), so only language needs a name map.

- [ ] **Step 1: Write the failing test**

```js
// append to tests/js/filter_rules.test.js

test("displayValue names a language code", () => {
  assert.strictEqual(fr.displayValue("language", "de"), "German (de)");
  assert.strictEqual(fr.displayValue("language", "en"), "English (en)");
});

test("displayValue falls back to the bare code for an unmapped language", () => {
  assert.strictEqual(fr.displayValue("language", "zz"), "zz");
});

test("displayValue leaves other categories untouched", () => {
  assert.strictEqual(fr.displayValue("resolution", "2160p"), "2160p");
  assert.strictEqual(fr.displayValue("source", "webdl"), "webdl");
  assert.strictEqual(fr.displayValue("language", "multi"), "Multi (multi)");
});

test("every language code the backend can emit has a name", () => {
  // Mirrors streams.LANGUAGE_CODES. A code without a name is not an error,
  // it just displays bare, but the common ones should read properly.
  const codes = ["ar","bg","cs","da","de","el","en","es","fa","fi","fr","he",
                 "hi","hr","hu","id","it","ja","ko","lt","multi","nl","no",
                 "pl","pt","ro","ru","sk","sl","sv","ta","th","tr","uk","zh"];
  const unnamed = codes.filter(c => fr.displayValue("language", c) === c);
  assert.deepStrictEqual(unnamed, [], `unnamed language codes: ${unnamed}`);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test tests/js/*.test.js`
Expected: FAIL, `fr.displayValue is not a function`

- [ ] **Step 3: Write the minimal implementation**

```js
// add to static/admin/filter_rules.js, above the _api object

// Only language needs this. Every other vocabulary is already readable.
const LANGUAGE_NAMES = {
  ar: "Arabic", bg: "Bulgarian", cs: "Czech", da: "Danish", de: "German",
  el: "Greek", en: "English", es: "Spanish", fa: "Persian", fi: "Finnish",
  fr: "French", he: "Hebrew", hi: "Hindi", hr: "Croatian", hu: "Hungarian",
  id: "Indonesian", it: "Italian", ja: "Japanese", ko: "Korean",
  lt: "Lithuanian", multi: "Multi", nl: "Dutch", no: "Norwegian",
  pl: "Polish", pt: "Portuguese", ro: "Romanian", ru: "Russian",
  sk: "Slovak", sl: "Slovenian", sv: "Swedish", ta: "Tamil", th: "Thai",
  tr: "Turkish", uk: "Ukrainian", zh: "Chinese",
};

function displayValue(category, code) {
  if (category !== "language") return code;
  const name = LANGUAGE_NAMES[code];
  return name ? `${name} (${code})` : code;
}
```

Add `displayValue` and `LANGUAGE_NAMES` to the `_api` object.

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test tests/js/*.test.js`
Expected: PASS, 21 tests

- [ ] **Step 5: Cross-check the map against the real backend vocabulary**

Run:

```bash
TORBOX_API_KEY=test ./.venv-sdd/bin/python -c "
import streams, json; print(json.dumps(list(streams.LANGUAGE_CODES)))"
```

Compare that list against `LANGUAGE_NAMES`. Every code the backend can emit
must have a name. If the backend has a code your map lacks, add it. Paste both
lists into your report.

- [ ] **Step 6: Commit**

```bash
git add static/admin/filter_rules.js tests/js/filter_rules.test.js
git commit -m "feat(ui): readable names for language codes"
```

---

### Task 3: Rendering the panels

**Files:**
- Modify: `static/admin/filter_rules.js`

**Interfaces:**
- Consumes: everything from Tasks 1 and 2.
- Produces: `renderPanel(state, prefix) -> HTMLElement`;
  `renderCollapsed(state, prefix) -> HTMLElement`.

This task is DOM output with no interaction yet. Buttons render but do nothing;
Task 4 wires them.

- [ ] **Step 1: Write the rendering code**

```js
// add to static/admin/filter_rules.js

const STATE_LABELS = {
  preferred: "Preferred", excluded: "Excluded",
  required: "Required", included: "Included",
};

function _chip(state, stateName, value, isInvalid) {
  const chip = document.createElement("span");
  chip.className = "fr-chip" + (isInvalid ? " fr-chip-invalid" : "");
  chip.dataset.value = value;
  chip.dataset.state = stateName;
  chip.textContent = displayValue(state.category, value);
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
      values.forEach(v => chips.appendChild(_chip(state, name, v, invalid.has(v))));
    }
    row.appendChild(chips);

    const add = document.createElement("select");
    add.className = "fr-add";
    add.dataset.action = "add";
    add.innerHTML = `<option value="">+ add</option>` +
      availableFor(state).map(v =>
        `<option value="${v}">${displayValue(state.category, v)}</option>`).join("");
    row.appendChild(add);

    // Order is load-bearing only for preferred. Offering reorder on a
    // membership test would imply a semantics that does not exist.
    if (name === "preferred") {
      const up = document.createElement("button");
      up.type = "button"; up.textContent = "up";
      up.className = "fr-move"; up.dataset.action = "up";
      const down = document.createElement("button");
      down.type = "button"; down.textContent = "down";
      down.className = "fr-move"; down.dataset.action = "down";
      row.appendChild(up); row.appendChild(down);
    }

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
```

Add `renderPanel`, `renderCollapsed` and `STATE_LABELS` to `_api`.

- [ ] **Step 2: Verify the rendering by hand**

There is no DOM test harness in this repo and this task does not add one.
Verify by rendering to a string in Node with a minimal stub, or by loading the
page later in Task 5. Confirm at minimum:
- a panel with rules shows chips, and one with none shows "(none)" four times
- the `up`/`down` buttons appear ONLY on the preferred row
- the warning appears ONLY on the included row
- an invalid value gets `fr-chip-invalid` and a title explaining itself

Paste what you checked into your report. Do not claim coverage you do not have.

- [ ] **Step 3: Commit**

```bash
git add static/admin/filter_rules.js
git commit -m "feat(ui): render filter rule panels and chips"
```

---

### Task 4: Interaction and hidden input sync

**Files:**
- Modify: `static/admin/filter_rules.js`
- Modify: `tests/js/filter_rules.test.js`

**Interfaces:**
- Consumes: everything from Tasks 1 to 3.
- Produces: `initFilterRules(group, container) -> void`; `syncHiddenInputs(state, prefix, form) -> void`.

The chips are a view. The hidden inputs are the truth the server reads. One
function rewrites all five inputs for a category from one state object, rather
than mutating them individually, so the two representations cannot drift.

- [ ] **Step 1: Write the failing test**

```js
// append to tests/js/filter_rules.test.js

test("syncHiddenInputs writes every field for the category from one state", () => {
  // A minimal form stub. This is the seam between the tested pure half and
  // the untested DOM half, so it is worth pinning even without a real DOM.
  const written = {};
  const form = {
    querySelector(sel) {
      const name = sel.match(/name="([^"]+)"/)[1];
      return { set value(v) { written[name] = v; }, get value() { return written[name]; } };
    },
  };
  let s = fr.assign(state(), "2160p", "preferred");
  s = fr.assign(s, "1080p", "preferred");
  s = fr.assign(s, "480p", "excluded");
  fr.syncHiddenInputs(s, "RESOLUTION", form);

  assert.strictEqual(written.setting_RESOLUTION_PREFERRED, "2160p,1080p");
  assert.strictEqual(written.setting_RESOLUTION_EXCLUDED, "480p");
  assert.strictEqual(written.setting_RESOLUTION_REQUIRED, "");
  assert.strictEqual(written.setting_RESOLUTION_INCLUDED, "");
  assert.strictEqual(written.setting_RESOLUTION_STRICT, "false");
});

test("syncHiddenInputs clears a state that has been emptied", () => {
  const written = {};
  const form = {
    querySelector(sel) {
      const name = sel.match(/name="([^"]+)"/)[1];
      return { set value(v) { written[name] = v; }, get value() { return written[name]; } };
    },
  };
  let s = fr.assign(state(), "1080p", "preferred");
  fr.syncHiddenInputs(s, "RESOLUTION", form);
  assert.strictEqual(written.setting_RESOLUTION_PREFERRED, "1080p");

  s = fr.assign(s, "1080p", null);
  fr.syncHiddenInputs(s, "RESOLUTION", form);
  assert.strictEqual(written.setting_RESOLUTION_PREFERRED, "",
    "an emptied state must clear its field, not leave the old value behind");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node --test tests/js/*.test.js`
Expected: FAIL, `fr.syncHiddenInputs is not a function`

- [ ] **Step 3: Write the implementation**

```js
// add to static/admin/filter_rules.js

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
    const row = ev.target.closest("[data-state]");

    if (action === "expand") {
      container.dataset[`open_${prefix}`] = "1";
    } else if (action === "remove") {
      const chip = ev.target.closest(".fr-chip");
      states[prefix] = assign(states[prefix], chip.dataset.value, null);
    } else if (action === "up" || action === "down") {
      const chips = row.querySelectorAll(".fr-chip");
      const last = chips.length ? chips[chips.length - 1].dataset.value : null;
      if (last) {
        states[prefix] = reorder(states[prefix], "preferred", last,
                                 action === "up" ? -1 : 1);
      }
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
```

Add `syncHiddenInputs` and `initFilterRules` to `_api`.

**Note on the reorder control:** the `up`/`down` buttons act on the LAST chip in
the preferred row, which is a deliberate simplification for a first version.
Per-chip reorder handles would be better and are a reasonable follow-up; say so
in your report if you think it should be done now instead.

- [ ] **Step 4: Run the test to verify it passes**

Run: `node --test tests/js/*.test.js`
Expected: PASS, 23 tests

- [ ] **Step 5: Verify the emptied-field test has teeth**

Change `syncHiddenInputs` to skip empty values (`if (input && fields[name])`),
confirm with grep, and re-run. `syncHiddenInputs clears a state that has been
emptied` MUST fail. That mutation is the realistic bug: a stale value left in a
hidden field means removing your last excluded value silently does nothing.
Restore and confirm green.

- [ ] **Step 6: Commit**

```bash
git add static/admin/filter_rules.js tests/js/filter_rules.test.js
git commit -m "feat(ui): wire chip interactions to the hidden setting inputs"
```

---

### Task 5: Template integration

**Files:**
- Modify: `templates/ui.html`

**Interfaces:**
- Consumes: `initFilterRules(group, container)` from Task 4.
- Produces: no code interface.

- [ ] **Step 1: Add the stylesheet and script**

In the `<head>` or alongside the existing inline styles in `templates/ui.html`,
add the chip styles. Match the existing variable names (`--panel2` and friends
are already used in that file):

```html
<style>
  .fr-panel { border-bottom:1px solid var(--panel2); padding:10px 0 }
  .fr-panel-head { display:flex; align-items:center; gap:10px; margin-bottom:6px }
  .fr-count { font-size:11px }
  .fr-strict { margin-left:auto; font-size:11px }
  .fr-row { display:flex; align-items:flex-start; gap:8px; margin:4px 0; font-size:12px }
  .fr-row-label { width:80px; flex:none; padding-top:3px }
  .fr-chips { flex:1; display:flex; flex-wrap:wrap; gap:4px }
  .fr-chip { display:inline-flex; align-items:center; gap:4px; padding:2px 6px;
             border:1px solid var(--panel2); border-radius:10px }
  .fr-chip-invalid { text-decoration:line-through; opacity:.6 }
  .fr-chip-remove { border:0; background:none; cursor:pointer; padding:0 }
  .fr-move { font-size:11px; padding:1px 5px }
  .fr-warn { font-size:11px }
  .fr-collapsed { display:flex; align-items:center; gap:10px;
                  padding:8px 0; border-bottom:1px solid var(--panel2) }
</style>
<script src="/static/admin/filter_rules.js"></script>
```

The script tag is the first static asset this template loads. `app.py:95`
configures `static_url_path="/static"`, so the path resolves without any route
being added.

- [ ] **Step 2: Branch the renderer for the filter_rules group**

In the settings renderer, immediately before the `// Normal groups` comment,
add a branch in the same shape the `mode` group already uses:

```javascript
        // The 35 rule keys render as seven category panels instead of 35 text
        // boxes. The panels write to hidden setting_ inputs, so /ui/settings
        // is unchanged and a script failure degrades to the normal rows.
        if (g.id === 'filter_rules' && window.FilterRules) {
          const card = document.createElement('div');
          card.className = 'card';
          card.style.marginBottom = '12px';
          card.innerHTML = `<div class="card-title">${g.title}</div>`;
          const host = document.createElement('div');
          card.appendChild(host);
          root.appendChild(card);
          window.FilterRules.initFilterRules(g, host);
          return; // skip normal rendering for the filter rules group
        }
```

The `&& window.FilterRules` guard is the fallback: if the script fails to load,
the group renders as the current 35 text boxes rather than an empty card.

- [ ] **Step 3: Verify in the running app**

Start the app against a scratch database and open the settings page:

```bash
DB_PATH=/tmp/c2ui.db TORBOX_API_KEY=test ./.venv-sdd/bin/python -c "import db; db.init()"
DB_PATH=/tmp/c2ui.db TORBOX_API_KEY=test python3 app.py
```

Note the second command uses the SYSTEM python, not `.venv-sdd`. That virtualenv
is for the test suite and lacks `apscheduler`, which `app.py` imports at startup.
If the system python also lacks the runtime dependencies, skip the live check and
say so in your report rather than reporting a verification you did not perform.

Confirm by hand, and report what you saw:
- seven categories render, three of them collapsed after a fresh migration
- adding a chip updates the hidden input (check with devtools)
- saving persists, and reloading shows the same chips
- deliberately breaking the script tag path falls back to the 35 text boxes

- [ ] **Step 4: Commit**

```bash
git add templates/ui.html
git commit -m "feat(ui): render the filter rules group as category panels"
```

---

### Task 6: Backend contract tests and docs

**Files:**
- Create: `tests/test_filter_rules_ui.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `settings.all_for_ui()`.
- Produces: no code interface.

The JS depends on the shape `all_for_ui()` returns. Nothing currently guards
that contract, so a later change to `settings.py` could break the editor with
every Python test still green.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_filter_rules_ui.py
import os, sys
os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import settings as _s


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setattr(_s.db, "get_all_settings", lambda: {})
    return _s.all_for_ui()


def _group(ui):
    return next(g for g in ui if g["id"] == "filter_rules")


def test_the_filter_rules_group_exists_with_all_thirty_five_keys(ui):
    assert len(_group(ui)["items"]) == 35


def test_every_list_key_carries_its_vocabulary(ui):
    """The editor renders a dropdown from options. A key without them would
    render an empty picker with no way to add a value."""
    missing = [i["key"] for i in _group(ui)["items"]
               if i["kind"] == "list" and not i["options"]]
    assert missing == []


def test_every_rule_key_is_hot_reloadable(ui):
    """The editor saves without a restart. A key marked otherwise would make
    the UI tell the user to restart for a change that takes effect at once."""
    assert all(i["hot_reload"] for i in _group(ui)["items"])


def test_key_names_match_what_the_editor_writes(ui):
    """The editor writes hidden inputs named setting_<KEY>. If these names
    drift, saving silently stops working while every test still passes."""
    keys = {i["key"] for i in _group(ui)["items"]}
    for prefix in ("RESOLUTION", "SOURCE", "ENCODE", "VISUAL_TAG",
                   "AUDIO_TAG", "AUDIO_CHANNELS", "LANGUAGE"):
        for state in ("PREFERRED", "EXCLUDED", "REQUIRED", "INCLUDED"):
            assert f"{prefix}_{state}" in keys
        assert f"{prefix}_STRICT" in keys


def test_strict_keys_are_bools_and_state_keys_are_lists(ui):
    for item in _group(ui)["items"]:
        expected = "bool" if item["key"].endswith("_STRICT") else "list"
        assert item["kind"] == expected, item["key"]


def test_the_save_endpoint_still_reads_the_setting_prefix():
    """The editor's hidden inputs are named setting_<KEY> because that is what
    /ui/settings parses. This pins the prefix so a rename cannot pass silently.

    app.py is read as TEXT rather than imported: importing it pulls in
    apscheduler, which is not installed in the test environment, and no other
    test imports app either.
    """
    import pathlib
    import re

    source = pathlib.Path(__file__).resolve().parent.parent.joinpath("app.py").read_text()
    match = re.search(r"def ui_save_settings.*?(?=\ndef |\n@app)", source, re.S)
    assert match, "ui_save_settings not found in app.py"
    assert 'startswith("setting_")' in match.group(0), (
        "the save endpoint no longer filters on the setting_ prefix; the "
        "rules editor writes hidden inputs with that prefix and would "
        "silently stop saving")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_rules_ui.py -q`
Expected: FAIL, the file does not exist yet, then PASS once written if the
backend already satisfies the contract. If any assertion fails, that is a real
backend gap: report it rather than weakening the test.

- [ ] **Step 3: Run the whole suite**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 4: Update the CHANGELOG**

Add to the existing `## [Unreleased]` entry: the settings page now renders the
35 rule keys as seven category panels with per-value chips; each category's
vocabulary is offered as a dropdown so an invalid value cannot be typed; a value
stored from `.env` that is not in the vocabulary is shown struck through with an
explanation, where it previously warned once at startup and was then invisible;
`preferred` is the only state with reorder controls, because it is the only one
where order changes behaviour; and `included` carries a permanent warning that it
overrides every other rule in every category.

State plainly that the editor writes the same settings as before, so `.env` and
the API are unaffected.

- [ ] **Step 5: Commit**

```bash
git add tests/test_filter_rules_ui.py CHANGELOG.md
git commit -m "test(ui): pin the backend contract the rules editor depends on"
```

---

## Self-Review

**Spec coverage.** Chips layout (Task 3), collapse of empty categories (Tasks 3
and 4), reorder on preferred only (Tasks 3 and 4), the included warning (Task 3),
hidden-input data flow with no new endpoint (Tasks 4 and 5), invalid values
surfaced (Tasks 1 and 3), language display names (Task 2), the file split with
its testing rationale (Task 1), backend contract tests (Task 6). The spec's
"what C2 is not" section needs no task.

**Placeholder scan.** No TBD, TODO, or "add error handling" steps. Every code
step carries its code.

**Type consistency.** `state` has `category`, `options`, `states`, `strict`
throughout. `assign(state, value, stateName|null)`, `reorder(state, stateName,
value, delta)`, `toFormFields(state, prefix)`, `syncHiddenInputs(state, prefix,
form)` and `displayValue(category, code)` keep their signatures across Tasks 1
to 5. `STATE_NAMES` is defined in Task 1 and used in Tasks 3 and 4.

**Known gaps, stated rather than hidden.** Task 3's rendering has no automated
test, because no DOM harness exists in this repo and this plan does not add one.
Task 4's `up`/`down` acts on the last preferred chip rather than a selected one,
which is a first-version simplification the task flags for the implementer to
challenge. Both are noted in the tasks themselves, not only here.
