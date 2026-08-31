import type { SetField, SetupData } from './types';
import { buildFormData } from './types';
import { TextField } from './fields';
import TestButton from './TestButton';

export default function StepSeerr({ data, set }: { data: SetupData; set: SetField }) {
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">Seerr</h2>
      <p className="mb-5 text-[13px] leading-relaxed text-muted">
        Optional but recommended. Used to resolve IMDB IDs and sync approved movies. &rarr;{' '}
        <a
          href="https://docs.jellyseerr.dev/using-jellyseerr/settings/general"
          target="_blank"
          rel="noreferrer"
          className="text-accent"
        >
          Jellyseerr &rarr; Settings &rarr; General &rarr; API Key
        </a>
      </p>
      <TextField
        id="SEERR_URL"
        label="Seerr URL"
        value={data.SEERR_URL}
        onChange={(v) => set('SEERR_URL', v)}
        placeholder="http://10.0.0.10:5055"
      />
      <TextField
        id="SEERR_API_KEY"
        label="Seerr API key"
        type="password"
        value={data.SEERR_API_KEY}
        onChange={(v) => set('SEERR_API_KEY', v)}
        placeholder="optional"
      />
      <TestButton kind="seerr" label="Test connection" buildFormData={() => buildFormData(data)} />
      <div className="mt-3.5">
        <TextField
          id="TMDB_API_KEY"
          label="TMDB API read access token"
          type="password"
          value={data.TMDB_API_KEY}
          onChange={(v) => set('TMDB_API_KEY', v)}
          placeholder="optional - starts with 'ey...'"
          hint={
            <>
              Used for poster lookups and metadata enrichment. &rarr;{' '}
              <a
                href="https://www.themoviedb.org/settings/api"
                target="_blank"
                rel="noreferrer"
                className="text-accent"
              >
                themoviedb.org/settings/api
              </a>
            </>
          }
        />
      </div>
    </div>
  );
}
