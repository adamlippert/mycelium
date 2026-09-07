import type { SettingsField, SettingsSection, WizardStepDef } from '../../api';
import { FieldList } from '../admin/settings/FieldList';
import type { FieldValue, Values } from '../admin/settings/visibility';

/** One wizard step: its title and intro, then exactly the schema fields it
 * declares, through the same renderer as the Settings page. Test and Load
 * go through the /setup routes, which work before an admin exists. */
export default function WizardStep({
  step, fields, values, onChange,
}: {
  step: WizardStepDef;
  fields: SettingsField[];
  values: Values;
  onChange: (key: string, next: FieldValue) => void;
}) {
  const byKey = new Map(fields.map((f) => [f.key, f]));
  const stepFields = step.keys.map((k) => byKey.get(k)).filter((f): f is SettingsField => Boolean(f));
  const section: SettingsSection = { id: 'wizard', title: '', description: '', icon: '', fields };
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">{step.title}</h2>
      <p className="mb-4 text-[13px] leading-relaxed text-muted">{step.intro}</p>
      <FieldList fields={stepFields} sections={[section]} values={values} onChange={onChange} advanced endpoint="setup" />
    </div>
  );
}

/** Keys on this step that are required and neither typed nor already set. */
export function missingRequired(step: WizardStepDef, fields: SettingsField[], values: Values): SettingsField[] {
  const byKey = new Map(fields.map((f) => [f.key, f]));
  return step.keys
    .map((k) => byKey.get(k))
    .filter((f): f is SettingsField => Boolean(f && f.required))
    .filter((f) => {
      const v = values[f.key];
      const typed = typeof v === 'string' ? v.trim() !== '' : Array.isArray(v) ? v.length > 0 : Boolean(v);
      const alreadySet = f.kind === 'secret' ? f.value === true : false;
      return !typed && !alreadySet;
    });
}
