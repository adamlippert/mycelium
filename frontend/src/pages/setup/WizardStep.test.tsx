import { describe, it, expect } from 'vitest';
import type { SettingsField, WizardStepDef } from '../../api';
import { SECRET_CLEARED } from '../admin/settings/visibility';
import { missingRequired } from './WizardStep';

const f = (over: Partial<SettingsField>): SettingsField => ({
  key: 'K', label: 'Key', help: 'help', kind: 'str', options: null, placeholder: null, unit: null,
  min: null, max: null, advanced: false, depends_on: null, test: null, picker: null, component: null,
  readonly: false, required: false, value: '', overridden: false, hot_reload: true, ...over,
});

const step: WizardStepDef = { id: 'step', title: 'Step', intro: '', keys: ['TORBOX_API_KEY'], lite: false };

describe('missingRequired', () => {
  it('treats the cleared-secret sentinel as untyped, not as filling the field', () => {
    const secretField = f({ key: 'TORBOX_API_KEY', kind: 'secret', required: true, value: false });
    expect(missingRequired(step, [secretField], { TORBOX_API_KEY: SECRET_CLEARED })).toEqual([secretField]);
  });

  it('is satisfied by a typed value', () => {
    const secretField = f({ key: 'TORBOX_API_KEY', kind: 'secret', required: true, value: false });
    expect(missingRequired(step, [secretField], { TORBOX_API_KEY: 'a-real-key' })).toEqual([]);
  });
});
