import type { SetField, SetupData } from './types';
import { buildFormData } from './types';
import { TextField } from './fields';
import TestButton from './TestButton';

export default function StepTrakt({ data, set }: { data: SetupData; set: SetField }) {
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">Trakt</h2>
      <p className="mb-5 text-[13px] leading-relaxed text-muted">
        Trakt scrobbles your watch progress from the web player - keeps your history, ratings and
        watchlist in sync. &rarr;{' '}
        <a
          href="https://trakt.tv/oauth/applications/new"
          target="_blank"
          rel="noreferrer"
          className="text-accent"
        >
          trakt.tv/oauth/applications/new
        </a>
      </p>
      <TextField
        id="TRAKT_CLIENT_ID"
        label="Client ID"
        value={data.TRAKT_CLIENT_ID}
        onChange={(v) => set('TRAKT_CLIENT_ID', v)}
        placeholder="optional"
      />
      <TextField
        id="TRAKT_CLIENT_SECRET"
        label="Client Secret"
        type="password"
        value={data.TRAKT_CLIENT_SECRET}
        onChange={(v) => set('TRAKT_CLIENT_SECRET', v)}
        placeholder="optional"
        hint="After saving, connect your personal Trakt account via the profile menu in the SPA."
      />
      <TestButton kind="trakt" label="Test Client ID" buildFormData={() => buildFormData(data)} />
    </div>
  );
}
