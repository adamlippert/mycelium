import type { SetField, SetupData } from './types';
import { buildFormData } from './types';
import { TextField } from './fields';
import TestButton from './TestButton';

export default function StepOpenSubtitles({ data, set }: { data: SetupData; set: SetField }) {
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">OpenSubtitles</h2>
      <p className="mb-5 text-[13px] leading-relaxed text-muted">
        Provides subtitle search in the web player. Free tier gives 500 downloads/day, VIP gives
        1 000. &rarr;{' '}
        <a
          href="https://www.opensubtitles.com/consumers"
          target="_blank"
          rel="noreferrer"
          className="text-accent"
        >
          opensubtitles.com/consumers
        </a>
      </p>
      <TextField
        id="OPENSUBTITLES_API_KEY"
        label="API key"
        type="password"
        value={data.OPENSUBTITLES_API_KEY}
        onChange={(v) => set('OPENSUBTITLES_API_KEY', v)}
        placeholder="optional"
      />
      <TestButton kind="opensubtitles" label="Test API key" buildFormData={() => buildFormData(data)} />
      <div className="mt-3.5">
        <TextField
          id="OPENSUBTITLES_LANGUAGES"
          label="Subtitle languages"
          value={data.OPENSUBTITLES_LANGUAGES}
          onChange={(v) => set('OPENSUBTITLES_LANGUAGES', v)}
          placeholder="nl,en"
          hint={
            <>
              Comma-separated ISO codes. Tried in order -{' '}
              <code className="rounded bg-card-raised px-1.5 py-px font-mono text-[12px] text-accent">
                nl,en
              </code>{' '}
              prefers Dutch, falls back to English.
            </>
          }
        />
      </div>
    </div>
  );
}
