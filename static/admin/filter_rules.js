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

const _api = { STATE_NAMES, parseList, serializeList, buildState, assign,
               reorder, availableFor, invalidValues, isEmpty, toFormFields,
               displayValue, LANGUAGE_NAMES };

if (typeof module !== "undefined" && module.exports) module.exports = _api;
if (typeof window !== "undefined") window.FilterRules = _api;
