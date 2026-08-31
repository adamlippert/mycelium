// Equivalence test: the TS port (filterRulesModel.ts) must behave exactly
// like the shipped, byte-frozen static/admin/filter_rules.js. That file
// cannot move (the Jinja settings page still loads it) and its own 34
// node tests stay untouched, so this is the referee for the port: any
// mismatch here means the port is wrong, never the original.
import { createRequire } from 'node:module';
import { describe, it, expect } from 'vitest';
import * as ported from './filterRulesModel';

const require = createRequire(import.meta.url);
const legacy = require('../../../../static/admin/filter_rules.js');

const OPTIONS = ['2160p', '1080p', '720p', '480p', 'unknown'];

function baseState(overrides: Record<string, unknown> = {}) {
  return {
    category: 'resolution',
    options: OPTIONS,
    states: { preferred: [], excluded: [], required: [], included: [] },
    strict: false,
    ...overrides,
  };
}

describe('filterRulesModel equivalence with static/admin/filter_rules.js', () => {
  it('parseList matches for a comma list with spaces and trailing comma', () => {
    expect(ported.parseList('1080p, 2160p ,')).toEqual(legacy.parseList('1080p, 2160p ,'));
  });

  it('parseList matches for an empty string', () => {
    expect(ported.parseList('')).toEqual(legacy.parseList(''));
  });

  it('buildState -> assign into each of the four states -> toFormFields matches', () => {
    const current = { preferred: '', excluded: '', required: '', included: '' };
    for (const stateName of ['preferred', 'excluded', 'required', 'included'] as const) {
      const legacyState = legacy.buildState('resolution', OPTIONS, current, false);
      const portedState = ported.buildState('resolution', OPTIONS, current, false);
      const legacyAssigned = legacy.assign(legacyState, '1080p', stateName);
      const portedAssigned = ported.assign(portedState, '1080p', stateName);
      expect(portedAssigned).toEqual(legacyAssigned);
      expect(ported.toFormFields(portedAssigned, 'RESOLUTION')).toEqual(
        legacy.toFormFields(legacyAssigned, 'RESOLUTION'),
      );
    }
  });

  it('reorder up (delta -1) matches, including the no-op boundary', () => {
    const s = baseState({
      states: { preferred: ['2160p', '1080p', '720p'], excluded: [], required: [], included: [] },
    });
    expect(ported.reorder(s as any, 'preferred', '1080p', -1)).toEqual(
      legacy.reorder(s, 'preferred', '1080p', -1),
    );
    // boundary: first item can't move up further
    expect(ported.reorder(s as any, 'preferred', '2160p', -1)).toEqual(
      legacy.reorder(s, 'preferred', '2160p', -1),
    );
  });

  it('reorder down (delta +1) matches, including the no-op boundary', () => {
    const s = baseState({
      states: { preferred: ['2160p', '1080p', '720p'], excluded: [], required: [], included: [] },
    });
    expect(ported.reorder(s as any, 'preferred', '1080p', 1)).toEqual(
      legacy.reorder(s, 'preferred', '1080p', 1),
    );
    // boundary: last item can't move down further
    expect(ported.reorder(s as any, 'preferred', '720p', 1)).toEqual(
      legacy.reorder(s, 'preferred', '720p', 1),
    );
  });

  it('availableFor and invalidValues match with overlapping assignments', () => {
    let legacyState = legacy.assign(baseState(), '1080p', 'preferred');
    legacyState = legacy.assign(legacyState, '480p', 'excluded');
    legacyState = legacy.assign(legacyState, '4k', 'required'); // invalid: not in OPTIONS

    let portedState = ported.assign(baseState() as any, '1080p', 'preferred');
    portedState = ported.assign(portedState, '480p', 'excluded');
    portedState = ported.assign(portedState, '4k', 'required');

    expect(ported.availableFor(portedState)).toEqual(legacy.availableFor(legacyState));
    expect(ported.invalidValues(portedState)).toEqual(legacy.invalidValues(legacyState));
  });

  it('visibleChips matches under the limit', () => {
    const values = ['a', 'b', 'c'];
    expect(ported.visibleChips(values, false)).toEqual(legacy.visibleChips(values, false));
  });

  it('visibleChips matches over the limit', () => {
    const values = Array.from({ length: legacy.CHIP_VISIBLE_LIMIT + 3 }, (_, i) => `v${i}`);
    expect(ported.visibleChips(values, false)).toEqual(legacy.visibleChips(values, false));
    expect(ported.visibleChips(values, true)).toEqual(legacy.visibleChips(values, true));
  });

  it('displayValue matches for a language code', () => {
    expect(ported.displayValue('language', 'de')).toEqual(legacy.displayValue('language', 'de'));
    expect(ported.displayValue('language', 'zz')).toEqual(legacy.displayValue('language', 'zz'));
  });

  it('displayValue matches for a plain (non-language) value', () => {
    expect(ported.displayValue('resolution', '2160p')).toEqual(
      legacy.displayValue('resolution', '2160p'),
    );
  });

  it('exposes the same CHIP_VISIBLE_LIMIT constant', () => {
    expect(ported.CHIP_VISIBLE_LIMIT).toEqual(legacy.CHIP_VISIBLE_LIMIT);
  });

  it('exposes the same STATE_NAMES and STATE_LABELS', () => {
    expect(ported.STATE_NAMES).toEqual(legacy.STATE_NAMES);
    expect(ported.STATE_LABELS).toEqual(legacy.STATE_LABELS);
  });

  it('exposes the same LANGUAGE_NAMES vocabulary', () => {
    expect(ported.LANGUAGE_NAMES).toEqual(legacy.LANGUAGE_NAMES);
  });
});
