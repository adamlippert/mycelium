import type { SettingsField, SettingsSection } from '../../../api';

export type FieldValue = string | boolean | string[];
export type Values = Record<string, FieldValue>;

/** Sentinel FieldValue for "the user explicitly cleared this secret". A
 * plain empty string means "untouched, keep the current .env/db value"
 * (see serialize below), so an intentional clear needs its own marker to
 * survive the changed/unchanged comparison and still post an empty value. */
export const SECRET_CLEARED = '__secret_cleared__';

const ARRAY_KINDS = new Set(['multiselect', 'ordered']);

export function initialValue(f: SettingsField): FieldValue {
  if (f.kind === 'bool') return Boolean(f.value);
  if (f.kind === 'secret') return '';
  if (ARRAY_KINDS.has(f.kind)) return Array.isArray(f.value) ? f.value.map(String) : [];
  if (f.kind === 'list') return Array.isArray(f.value) ? f.value.join(',') : String(f.value ?? '');
  if (f.value === null || f.value === undefined) return '';
  return String(f.value);
}

export function initialValues(sections: SettingsSection[]): Values {
  const v: Values = {};
  sections.forEach((s) => s.fields.forEach((f) => {
    if (f.kind !== 'custom') v[f.key] = initialValue(f);
  }));
  return v;
}

export function dependsSatisfied(f: SettingsField, values: Values): boolean {
  if (!f.depends_on) return true;
  const [key, wanted] = f.depends_on.split('=');
  const v = values[key];
  if (wanted === undefined) return Boolean(v);
  return v === wanted;
}

export function isVisible(f: SettingsField, values: Values, advanced: boolean): boolean {
  if (f.advanced && !advanced) return false;
  return dependsSatisfied(f, values);
}

export function matchesQuery(f: SettingsField, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return [f.label, f.key, f.help].some((t) => (t || '').toLowerCase().includes(needle));
}

export function sectionMatches(s: SettingsSection, q: string): boolean {
  if (!q.trim()) return true;
  const needle = q.trim().toLowerCase();
  return s.title.toLowerCase().includes(needle) || s.fields.some((f) => matchesQuery(f, q));
}

export function asString(v: FieldValue | undefined): string {
  if (v === undefined) return '';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (Array.isArray(v)) return v.join(',');
  return v;
}

export function serialize(sections: SettingsSection[], values: Values, initial: Values): Record<string, string> {
  const out: Record<string, string> = {};
  sections.forEach((s) => s.fields.forEach((f) => {
    if (f.kind === 'custom' || f.readonly) return;
    const v = values[f.key];
    if (f.kind === 'secret') {
      // SECRET_CLEARED is an explicit "clear this secret" request: it must
      // still post an empty value even though a plain untouched empty
      // string never does (see below).
      if (v === SECRET_CLEARED) { out[`setting_${f.key}`] = ''; return; }
      if (v === '' || v === undefined) return;
    }
    // Only post what actually changed: posting every field would write an
    // override for every untouched key, freezing today's .env value into
    // the database. A blank still differs from its initial value, so
    // clearing an override to fall back to .env keeps working.
    if (asString(v) === asString(initial[f.key])) return;
    out[`setting_${f.key}`] = asString(v);
  }));
  return out;
}

export function serviceValues(sections: SettingsSection[], service: string, values: Values): Record<string, string> {
  const out: Record<string, string> = {};
  sections.forEach((s) => s.fields.forEach((f) => {
    if (f.test !== service) return;
    const v = values[f.key];
    // A cleared secret must not be sent to the tester as the literal
    // sentinel: that reads as a real value and the tester reports an
    // auth failure instead of "not set".
    out[f.key] = v === SECRET_CLEARED ? '' : asString(v);
  }));
  return out;
}

export function countChanges(sections: SettingsSection[], values: Values, initial: Values): number {
  let n = 0;
  sections.forEach((s) => s.fields.forEach((f) => {
    if (f.kind === 'custom') return;
    if (asString(values[f.key]) !== asString(initial[f.key])) n += 1;
  }));
  return n;
}
