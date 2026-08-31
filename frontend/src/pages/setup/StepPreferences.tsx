import type { SetField, SetupData } from './types';
import { TextField, CheckboxRow } from './fields';

export default function StepPreferences({ data, set }: { data: SetupData; set: SetField }) {
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">Quality &amp; language</h2>
      <p className="mb-5 text-[13px] leading-relaxed text-muted">
        How should Mycelium rank candidates? You can tweak these per-show later via the Overrides
        tab.
      </p>
      <TextField
        id="QUALITY_PREFERENCE"
        label="Quality preference (in order)"
        value={data.QUALITY_PREFERENCE}
        onChange={(v) => set('QUALITY_PREFERENCE', v)}
        hint="Comma-separated. Mycelium tries each in order until one is cached on TorBox."
      />
      <TextField
        id="AUDIO_LANGUAGE_PREFERENCE"
        label="Audio language preference"
        value={data.AUDIO_LANGUAGE_PREFERENCE}
        onChange={(v) => set('AUDIO_LANGUAGE_PREFERENCE', v)}
        placeholder="nl,en (leave empty for no preference)"
        hint={
          <>
            Boosts releases with matching audio. Use ISO codes like{' '}
            <code className="rounded bg-card-raised px-1.5 py-px font-mono text-[12px] text-accent">nl</code>,{' '}
            <code className="rounded bg-card-raised px-1.5 py-px font-mono text-[12px] text-accent">en</code>,{' '}
            <code className="rounded bg-card-raised px-1.5 py-px font-mono text-[12px] text-accent">multi</code>.
          </>
        }
      />
      <CheckboxRow
        id="PREFER_HEVC"
        title="Prefer HEVC / x265 encodes"
        description="~40% smaller files at similar quality."
        checked={data.PREFER_HEVC}
        onChange={(v) => set('PREFER_HEVC', v)}
      />
      <CheckboxRow
        id="ALLOW_4K"
        title="Allow 4K releases"
        description="Large files, only sensible on fast LAN."
        checked={data.ALLOW_4K}
        onChange={(v) => set('ALLOW_4K', v)}
      />
    </div>
  );
}
