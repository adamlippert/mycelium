import { useEffect, useMemo, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api, csrfToken } from '../api';
import type { SetupSchema, SettingsSection } from '../api';
import { initialValues, serialize } from './admin/settings/visibility';
import type { FieldValue, Values } from './admin/settings/visibility';
import StepRail from './setup/StepRail';
import WizardStep, { missingRequired } from './setup/WizardStep';
import StepDone from './setup/StepDone';
import StepAccount, { EMPTY_ACCOUNT } from './setup/StepAccount';
import type { Account } from './setup/StepAccount';

/** Pre-auth, chrome-less setup wizard driven by GET /setup/schema: the
 * steps and their fields come from the settings schema, pre-filled with the
 * current values, so a re-run shows what is configured today.
 *
 * This page is mounted outside the app's QueryClientProvider (see App.tsx,
 * and the tests, which render <Setup /> bare), but FieldList's ServiceTest
 * and Picker cards use useMutation. So the wizard body gets its own
 * QueryClient here rather than relying on one from above. */
export default function Setup() {
  const [queryClient] = useState(() => new QueryClient());
  const [schema, setSchema] = useState<SetupSchema | null>(null);
  const [loadError, setLoadError] = useState('');
  const [values, setValues] = useState<Values>({});
  const [initial, setInitial] = useState<Values>({});
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [account, setAccount] = useState<Account>(EMPTY_ACCOUNT);

  useEffect(() => {
    api.setupSchema().then((s) => {
      const section: SettingsSection = { id: 'wizard', title: '', description: '', icon: '', fields: s.fields };
      const v = initialValues([section]);
      setSchema(s);
      setValues(v);
      setInitial(v);
    }).catch((e: Error) => setLoadError(e.message));
  }, []);

  const section: SettingsSection = useMemo(
    () => ({ id: 'wizard', title: '', description: '', icon: '', fields: schema?.fields || [] }),
    [schema],
  );
  const isLite = Boolean(values.LITE_MODE);
  const steps = useMemo(() => (schema?.steps || []).filter((s) => !isLite || s.lite), [schema, isLite]);
  const needsAccount = Boolean(schema?.needs_first_admin);
  const accountStep = needsAccount ? steps.length : -1;
  const doneStep = needsAccount ? steps.length + 1 : steps.length;
  const isDone = step === doneStep;
  const current = steps[step];
  const missing = current && schema ? missingRequired(current, schema.fields, values) : [];

  const onChange = (key: string, next: FieldValue) => setValues((p) => ({ ...p, [key]: next }));

  function accountProblem(): string | null {
    if (!needsAccount) return null;
    if (!account.username.trim()) return 'Choose a username.';
    if (account.password.length < 4) return 'Password must be at least 4 characters.';
    if (account.password !== account.confirm) return 'The passwords do not match.';
    return null;
  }

  async function finish() {
    const problem = accountProblem();
    if (problem) {
      window.alert(problem);
      return;
    }
    setSaving(true);
    try {
      const fd = new FormData();
      Object.entries(serialize([section], values, initial)).forEach(([k, v]) => fd.append(k.replace(/^setting_/, ''), v));
      const r = await fetch('/setup/save', { method: 'POST', body: fd, headers: { 'X-CSRFToken': csrfToken() } });
      if (!r.ok) throw new Error('save failed');
      if (needsAccount) {
        // Settings are saved but setup is deliberately not marked complete
        // until this succeeds: creating the first admin is what completes it.
        await api.createUser({ username: account.username.trim(), password: account.password, role: 'admin' });
      }
      window.location.href = '/ui';
    } catch (e: any) {
      setSaving(false);
      window.alert('Save failed: ' + e.message);
    }
  }

  function goNext() {
    if (isDone) {
      finish();
      return;
    }
    setStep((s) => Math.min(s + 1, doneStep));
  }

  function goBack() {
    setStep((s) => Math.max(s - 1, 0));
  }

  async function skipWizard() {
    if (!window.confirm('Skip the wizard? You can configure everything via Settings tab later.')) return;
    await fetch('/setup/skip', { method: 'POST', headers: { 'X-CSRFToken': csrfToken() } });
    window.location.href = '/ui';
  }

  // Lite can shrink the step list from under the current index.
  useEffect(() => {
    if (step > doneStep) setStep(doneStep);
  }, [step, doneStep]);

  if (loadError) return <p className="p-6 text-sm text-danger">Could not load the setup wizard: {loadError}</p>;
  if (!schema) return <p className="p-6 text-sm text-muted">Loading...</p>;

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="w-full max-w-[640px] overflow-hidden rounded-xl border border-border bg-card shadow-2xl">
          <div className="border-b border-border px-7 pb-4 pt-6">
            <h1 className="font-mono text-xl font-bold text-body">
              myc<span className="text-accent-light">3</span>l<span className="text-accent-light">1</span>um setup
            </h1>
            <p className="mt-1 text-xs text-muted">
              One-time wizard to wire up the basics. You can change everything later in the Settings tab.
            </p>
            <div className="mt-3.5">
              <StepRail steps={steps} current={step} />
            </div>
          </div>

          <div className="min-h-[280px] px-7 py-6">
            {current && <WizardStep step={current} fields={schema.fields} values={values} onChange={onChange} />}
            {needsAccount && step === accountStep && <StepAccount account={account} setAccount={setAccount} />}
            {isDone && <StepDone />}
          </div>

          <div className="flex items-center justify-between border-t border-border bg-card-raised px-7 py-4">
            <button type="button" onClick={skipWizard} className="text-sm text-muted hover:text-body">Skip wizard</button>
            <div className="flex items-center gap-2.5">
              {step > 0 && (
                <button type="button" onClick={goBack} className="text-sm text-muted hover:text-body">Back</button>
              )}
              {missing.length > 0 && <span className="text-[11px] text-warn">{missing[0].label} is required.</span>}
              <button
                type="button"
                onClick={goNext}
                disabled={saving || missing.length > 0}
                className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? 'Saving...' : isDone ? 'Finish' : 'Continue'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </QueryClientProvider>
  );
}
