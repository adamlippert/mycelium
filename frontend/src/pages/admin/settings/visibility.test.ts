import { describe, it, expect } from 'vitest';
import type { SettingsField, SettingsSection } from '../../../api';
import {
  countChanges, dependsSatisfied, initialValue, initialValues, isVisible, matchesQuery,
  sectionMatches, serialize, serviceValues,
} from './visibility';

const f = (over: Partial<SettingsField>): SettingsField => ({
  key: 'K', label: 'Key', help: 'help', kind: 'str', options: null, placeholder: null, unit: null,
  min: null, max: null, advanced: false, depends_on: null, test: null, picker: null, component: null,
  readonly: false, value: '', overridden: false, hot_reload: true, ...over,
});
const section = (fields: SettingsField[]): SettingsSection => ({ id: 's', title: 'Sec', description: 'd', icon: 'x', fields });

describe('initial values', () => {
  it('turns lists into arrays, bools into booleans and secrets into empty strings', () => {
    expect(initialValue(f({ kind: 'multiselect', value: ['en', 'nl'] }))).toEqual(['en', 'nl']);
    expect(initialValue(f({ kind: 'bool', value: 1 }))).toBe(true);
    expect(initialValue(f({ kind: 'secret', value: true }))).toBe('');
    expect(initialValue(f({ kind: 'int', value: 7 }))).toBe('7');
    expect(initialValue(f({ kind: 'list', value: ['2160p:40'] }))).toBe('2160p:40');
  });
});

describe('visibility', () => {
  const values = { CATBOX_MODE: true, ZILEAN_MODE: 'native' };
  it('follows a bool dependency and a select value dependency', () => {
    expect(dependsSatisfied(f({ depends_on: 'CATBOX_MODE' }), values)).toBe(true);
    expect(dependsSatisfied(f({ depends_on: 'CATBOX_MODE' }), { CATBOX_MODE: false })).toBe(false);
    expect(dependsSatisfied(f({ depends_on: 'ZILEAN_MODE=native' }), values)).toBe(true);
    expect(dependsSatisfied(f({ depends_on: 'ZILEAN_MODE=external' }), values)).toBe(false);
  });
  it('hides advanced fields in simple mode', () => {
    expect(isVisible(f({ advanced: true }), values, false)).toBe(false);
    expect(isVisible(f({ advanced: true }), values, true)).toBe(true);
    expect(isVisible(f({ advanced: true, depends_on: 'CATBOX_MODE' }), { CATBOX_MODE: false }, true)).toBe(false);
  });
});

describe('search', () => {
  it('matches label, key and help, case-insensitively', () => {
    const x = f({ key: 'TORBOX_API_KEY', label: 'TorBox API key', help: 'From TorBox settings.' });
    expect(matchesQuery(x, 'torbox')).toBe(true);
    expect(matchesQuery(x, 'API_KEY')).toBe(true);
    expect(matchesQuery(x, 'settings')).toBe(true);
    expect(matchesQuery(x, 'jellyfin')).toBe(false);
    expect(matchesQuery(x, '')).toBe(true);
    expect(sectionMatches(section([x]), 'jelly')).toBe(false);
    expect(sectionMatches(section([x]), 'torb')).toBe(true);
  });
});

describe('serialize', () => {
  const sections = [section([
    f({ key: 'A', kind: 'bool' }), f({ key: 'B', kind: 'multiselect' }), f({ key: 'S', kind: 'secret' }),
    f({ key: 'T', kind: 'secret' }), f({ key: '__X', kind: 'custom', component: 'X' }),
  ])];
  it('posts setting_ fields, joins arrays, skips untouched secrets and custom cards', () => {
    expect(serialize(sections, { A: false, B: ['en', 'nl'], S: '', T: 'new' })).toEqual({
      setting_A: 'false', setting_B: 'en,nl', setting_T: 'new',
    });
  });
  it('collects the values of one service and counts changes', () => {
    const s = [section([f({ key: 'RADARR_URL', test: 'radarr' }), f({ key: 'RADARR_API_KEY', kind: 'secret', test: 'radarr' }), f({ key: 'OTHER' })])];
    expect(serviceValues(s, 'radarr', { RADARR_URL: 'http://r', RADARR_API_KEY: '', OTHER: 'x' })).toEqual({ RADARR_URL: 'http://r', RADARR_API_KEY: '' });
    const initial = initialValues(s);
    expect(countChanges(s, { ...initial, RADARR_URL: 'http://r' }, initial)).toBe(1);
    expect(countChanges(s, initial, initial)).toBe(0);
  });
});
