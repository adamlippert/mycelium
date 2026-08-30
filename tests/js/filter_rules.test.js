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
