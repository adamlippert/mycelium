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

test("reorder can reach an arbitrary order", () => {
  // The defect this replaces: a control acting on "the last chip" oscillates
  // between two arrangements and can never move the first value at all.
  let s = state({ states: { preferred: ["1080p", "2160p", "720p"],
                            excluded: [], required: [], included: [] } });
  s = fr.reorder(s, "preferred", "720p", -1);
  s = fr.reorder(s, "preferred", "720p", -1);
  assert.deepStrictEqual(s.states.preferred, ["720p", "1080p", "2160p"],
    "a value must be movable all the way to the front");
});

test("every value in the list is independently movable", () => {
  const start = ["a", "b", "c"];
  const s = state({ options: start,
                    states: { preferred: start.slice(),
                              excluded: [], required: [], included: [] } });
  assert.deepStrictEqual(fr.reorder(s, "preferred", "a", 1).states.preferred,
                         ["b", "a", "c"]);
  assert.deepStrictEqual(fr.reorder(s, "preferred", "b", -1).states.preferred,
                         ["b", "a", "c"]);
  assert.deepStrictEqual(fr.reorder(s, "preferred", "c", -1).states.preferred,
                         ["a", "c", "b"]);
});
