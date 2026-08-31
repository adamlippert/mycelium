import type { SetField, SetupData } from './types';
import { buildFormData } from './types';
import { TextField, CheckboxRow } from './fields';
import TestButton from './TestButton';

export default function StepZilean({ data, set }: { data: SetupData; set: SetField }) {
  const native = data.ZILEAN_MODE === 'native';
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">Zilean</h2>
      <p className="mb-3.5 text-[13px] leading-relaxed text-muted">
        Optional self-hosted torrent index (DMM-based). Faster than Torrentio for content in its
        index, no rate limits. Leave everything blank/off if you don&apos;t want this. &rarr;{' '}
        <a
          href="https://github.com/iPromKnight/zilean"
          target="_blank"
          rel="noreferrer"
          className="text-accent"
        >
          github.com/iPromKnight/zilean
        </a>
      </p>

      <div className="mb-3.5 grid grid-cols-2 gap-2.5">
        <label
          onClick={() => set('ZILEAN_MODE', 'external')}
          className={`flex cursor-pointer flex-col gap-1.5 rounded-lg border-2 p-3.5 ${
            native ? 'border-border bg-transparent' : 'border-accent bg-accent/[0.07]'
          }`}
        >
          <div className="flex items-center gap-2">
            <input
              type="radio"
              name="_zl_mode"
              value="external"
              checked={!native}
              readOnly
              className="accent-accent"
            />
            <span className="text-[13px] font-bold text-body">External service</span>
          </div>
          <span className="text-[11px] leading-relaxed text-muted">
            Point at your own Zilean + Postgres container (or one you already run).
          </span>
        </label>
        <label
          onClick={() => set('ZILEAN_MODE', 'native')}
          className={`flex cursor-pointer flex-col gap-1.5 rounded-lg border-2 p-3.5 ${
            native ? 'border-accent bg-accent/[0.07]' : 'border-border bg-transparent'
          }`}
        >
          <div className="flex items-center gap-2">
            <input
              type="radio"
              name="_zl_mode"
              value="native"
              checked={native}
              readOnly
              className="accent-accent"
            />
            <span className="text-[13px] font-bold text-body">Native (built-in)</span>
          </div>
          <span className="text-[11px] leading-relaxed text-muted">
            No separate container. Mycelium syncs the hashlist itself into a local index.
          </span>
        </label>
      </div>

      {!native ? (
        <div>
          <TextField
            id="ZILEAN_URL"
            label="Zilean URL"
            value={data.ZILEAN_URL}
            onChange={(v) => set('ZILEAN_URL', v)}
            placeholder="http://10.0.0.10:8181"
          />
          <TestButton kind="zilean" label="Test connection" buildFormData={() => buildFormData(data)} />
          <div className="mt-2">
            <CheckboxRow
              id="ZILEAN_ENABLED"
              title="Enable Zilean"
              description="Automatically checked when you enter a URL above."
              checked={data.ZILEAN_ENABLED}
              onChange={(v) => set('ZILEAN_ENABLED', v)}
            />
          </div>
        </div>
      ) : (
        <div className="rounded-md border-l-[3px] border-accent bg-accent/[0.08] px-3.5 py-2.5 text-[12px] text-accent">
          Mycelium will download the community DMM hashlist itself on a schedule - nothing else to
          configure here, just finish the wizard.
          <br />
          <br />
          Already run an external Zilean with an existing index and don&apos;t want to re-scrape
          from scratch? Finish the wizard as-is, then go to <b>Settings &rarr; Zilean native index</b>{' '}
          afterwards and use <b>Import from Postgres</b> to pull your existing hashes straight from
          your external Zilean&apos;s database.
        </div>
      )}
    </div>
  );
}
