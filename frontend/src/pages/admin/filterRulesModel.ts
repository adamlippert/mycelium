// TypeScript port of the pure state half of static/admin/filter_rules.js.
//
// The original file cannot move (the Jinja settings page still loads it,
// and its 34 node tests are pinned byte-unchanged), so this is a
// function-for-function rewrite of the same semantics. It exists so the
// native React admin can reuse the model without a DOM. Behavioural parity
// with the original is proven by filterRulesModel.test.ts, which loads the
// original via createRequire and asserts deep equality against this file
// for a matrix of operations - that test is the referee, not this file.
//
// Deliberately NOT ported: renderPanel, renderCollapsed, syncHiddenInputs,
// initFilterRules. Those are DOM wiring; React replaces them.

export const STATE_NAMES = ['preferred', 'excluded', 'required', 'included'] as const;

export type StateName = (typeof STATE_NAMES)[number];

export type FilterRuleStates = Record<StateName, string[]>;

export interface FilterRuleState {
  category: string;
  options: string[];
  states: FilterRuleStates;
  strict: boolean;
}

/** Raw per-state values as read from the settings API, keyed by lowercase
 * state name (e.g. "preferred"), each a comma string or an already-split
 * array (list-kind settings arrive as arrays). */
export type RawCurrent = Partial<Record<StateName, string | string[] | null | undefined>>;

export function parseList(raw: string | null | undefined): string[] {
  if (!raw) return [];
  return String(raw)
    .split(',')
    .map((v) => v.trim())
    .filter(Boolean);
}

export function serializeList(values: string[]): string {
  return values.join(',');
}

export function buildState(
  category: string,
  options: string[],
  current: RawCurrent,
  strict: boolean,
): FilterRuleState {
  const states = {} as FilterRuleStates;
  STATE_NAMES.forEach((name) => {
    const raw = current[name];
    states[name] = parseList(Array.isArray(raw) ? raw.join(',') : raw);
  });
  return { category, options: options.slice(), states, strict: Boolean(strict) };
}

function _clone(state: FilterRuleState): FilterRuleState {
  const states = {} as FilterRuleStates;
  STATE_NAMES.forEach((name) => {
    states[name] = state.states[name].slice();
  });
  return { ...state, options: state.options.slice(), states };
}

export function assign(
  state: FilterRuleState,
  value: string,
  stateName: StateName | null,
): FilterRuleState {
  // A value holds at most one state per category. Assigning it elsewhere
  // moves it, so a user cannot accidentally build a config where one value
  // is both required and excluded.
  const next = _clone(state);
  STATE_NAMES.forEach((name) => {
    next.states[name] = next.states[name].filter((v) => v !== value);
  });
  if (stateName) next.states[stateName].push(value);
  return next;
}

export function reorder(
  state: FilterRuleState,
  stateName: StateName,
  value: string,
  delta: number,
): FilterRuleState {
  const next = _clone(state);
  const list = next.states[stateName];
  const from = list.indexOf(value);
  if (from === -1) return next;
  const to = from + delta;
  if (to < 0 || to >= list.length) return next; // boundary, not an error
  list.splice(to, 0, list.splice(from, 1)[0]);
  return next;
}

export function assignedValues(state: FilterRuleState): string[] {
  return STATE_NAMES.flatMap((name) => state.states[name]);
}

export function availableFor(state: FilterRuleState): string[] {
  const taken = new Set(assignedValues(state));
  return state.options.filter((v) => !taken.has(v));
}

export function invalidValues(state: FilterRuleState): string[] {
  const known = new Set(state.options);
  return assignedValues(state).filter((v) => !known.has(v));
}

export function isEmpty(state: FilterRuleState): boolean {
  // strict alone is not a rule, so it does not make a category non-empty.
  return STATE_NAMES.every((name) => state.states[name].length === 0);
}

export function toFormFields(state: FilterRuleState, prefix: string): Record<string, string> {
  const fields: Record<string, string> = {};
  STATE_NAMES.forEach((name) => {
    fields[`setting_${prefix}_${name.toUpperCase()}`] = serializeList(state.states[name]);
  });
  fields[`setting_${prefix}_STRICT`] = state.strict ? 'true' : 'false';
  return fields;
}

// Only language needs this. Every other vocabulary is already readable.
export const LANGUAGE_NAMES: Record<string, string> = {
  ar: 'Arabic', bg: 'Bulgarian', cs: 'Czech', da: 'Danish', de: 'German',
  el: 'Greek', en: 'English', es: 'Spanish', fa: 'Persian', fi: 'Finnish',
  fr: 'French', he: 'Hebrew', hi: 'Hindi', hr: 'Croatian', hu: 'Hungarian',
  id: 'Indonesian', is: 'Icelandic', it: 'Italian', ja: 'Japanese', ko: 'Korean',
  lt: 'Lithuanian', ms: 'Malay', multi: 'Multi', nl: 'Dutch', no: 'Norwegian',
  pl: 'Polish', pt: 'Portuguese', ro: 'Romanian', ru: 'Russian',
  sk: 'Slovak', sl: 'Slovenian', sv: 'Swedish', ta: 'Tamil', th: 'Thai',
  tr: 'Turkish', uk: 'Ukrainian', vi: 'Vietnamese', zh: 'Chinese',
};

export function displayValue(category: string, code: string): string {
  if (category !== 'language') return code;
  const name = LANGUAGE_NAMES[code];
  return name ? `${name} (${code})` : code;
}

// How many chips a state row shows before collapsing the rest behind a
// "+N more" control. This is a COUNT, not a row count: see filter_rules.js
// for the full rationale (default SOURCE_EXCLUDED has 8 values and must
// never be truncated out of the box).
export const CHIP_VISIBLE_LIMIT = 10;

export interface VisibleChips {
  shown: string[];
  hidden: number;
}

export function visibleChips(values: string[], expanded: boolean, limit?: number): VisibleChips {
  const cap = limit === undefined ? CHIP_VISIBLE_LIMIT : limit;
  if (expanded || values.length <= cap) return { shown: values.slice(), hidden: 0 };
  return { shown: values.slice(0, cap), hidden: values.length - cap };
}

export const STATE_LABELS: Record<StateName, string> = {
  preferred: 'Preferred',
  excluded: 'Excluded',
  required: 'Required',
  included: 'Included',
};
