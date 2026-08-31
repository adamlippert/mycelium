import { useState } from 'react';
import { csrfToken } from '../api';
import type { SetField, SetupData } from './setup/types';
import { DEFAULT_SETUP_DATA, buildFormData } from './setup/types';
import StepRail from './setup/StepRail';
import StepWelcome from './setup/StepWelcome';
import StepTorbox from './setup/StepTorbox';
import StepJellyfin from './setup/StepJellyfin';
import StepSeerr from './setup/StepSeerr';
import StepPreferences from './setup/StepPreferences';
import StepCatbox from './setup/StepCatbox';
import StepNotifications from './setup/StepNotifications';
import StepTrakt from './setup/StepTrakt';
import StepOpenSubtitles from './setup/StepOpenSubtitles';
import StepZilean from './setup/StepZilean';
import StepRadarrSonarr from './setup/StepRadarrSonarr';
import StepDone from './setup/StepDone';

// Mirrors templates/setup.html's script constants exactly.
const STEPS = 12;
const LITE_SKIP_FROM = 6; // after Notifications (step 6), jump to Done in Lite
const LITE_SKIP_TO = 11; // Done step

/** Pre-auth, chrome-less setup wizard - ports templates/setup.html's twelve
 * data-step panes (ten configuration steps bookended by Welcome and Done) to
 * React. See task-3-report.md for the full field-by-field inventory this was
 * ported against and the deviations from the brief's paraphrase. */
export default function Setup() {
  const [step, setStep] = useState(0);
  const [data, setData] = useState<SetupData>(DEFAULT_SETUP_DATA);
  const [saving, setSaving] = useState(false);

  const set: SetField = (key, value) => setData((d) => ({ ...d, [key]: value }));

  const isLite = data.LITE_MODE;
  const isDone = step === STEPS - 1;

  async function finish() {
    setSaving(true);
    try {
      const r = await fetch('/setup/save', {
        method: 'POST',
        body: buildFormData(data),
        headers: { 'X-CSRFToken': csrfToken() },
      });
      if (!r.ok) throw new Error('save failed');
      window.location.href = '/ui';
    } catch (e: any) {
      setSaving(false);
      window.alert('Save failed: ' + e.message);
    }
  }

  function goNext() {
    if (step === 1 && !data.TORBOX_API_KEY.trim()) {
      window.alert('TorBox API key is required.');
      return;
    }
    if (isDone) {
      finish();
      return;
    }
    // Auto-enable Zilean when a URL was entered, exactly like setup.html's goNext().
    if (step === 9 && data.ZILEAN_URL.trim()) {
      set('ZILEAN_ENABLED', true);
    }
    let next = step + 1;
    // Skip Full-only steps (7-10) when Lite mode is active.
    if (isLite && next > LITE_SKIP_FROM && next <= LITE_SKIP_TO - 1) {
      next = LITE_SKIP_TO;
    }
    setStep(next);
  }

  function goBack() {
    if (step === 0) return;
    let prev = step - 1;
    if (isLite && prev > LITE_SKIP_FROM && prev <= LITE_SKIP_TO - 1) {
      prev = LITE_SKIP_FROM;
    }
    setStep(prev);
  }

  async function skipWizard() {
    if (!window.confirm('Skip the wizard? You can configure everything via Settings tab later.')) {
      return;
    }
    await fetch('/setup/skip', { method: 'POST', headers: { 'X-CSRFToken': csrfToken() } });
    window.location.href = '/ui';
  }

  return (
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
            <StepRail step={step} lite={isLite} />
          </div>
        </div>

        <div className="min-h-[280px] px-7 py-6">
          {step === 0 && <StepWelcome data={data} set={set} />}
          {step === 1 && <StepTorbox data={data} set={set} />}
          {step === 2 && <StepJellyfin data={data} set={set} />}
          {step === 3 && <StepSeerr data={data} set={set} />}
          {step === 4 && <StepPreferences data={data} set={set} />}
          {step === 5 && <StepCatbox data={data} set={set} />}
          {step === 6 && <StepNotifications data={data} set={set} />}
          {step === 7 && <StepTrakt data={data} set={set} />}
          {step === 8 && <StepOpenSubtitles data={data} set={set} />}
          {step === 9 && <StepZilean data={data} set={set} />}
          {step === 10 && <StepRadarrSonarr data={data} set={set} />}
          {step === 11 && <StepDone />}
        </div>

        <div className="flex items-center justify-between border-t border-border bg-card-raised px-7 py-4">
          <button type="button" onClick={skipWizard} className="text-sm text-muted hover:text-body">
            Skip wizard
          </button>
          <div className="flex items-center gap-2.5">
            {step > 0 && (
              <button type="button" onClick={goBack} className="text-sm text-muted hover:text-body">
                Back
              </button>
            )}
            <span className="text-[11px] text-muted/60">Autosaved</span>
            <button
              type="button"
              onClick={goNext}
              disabled={saving}
              className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent/90
                         disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? 'Saving...' : isDone ? 'Finish' : 'Continue'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
