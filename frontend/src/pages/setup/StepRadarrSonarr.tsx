import type { SetField, SetupData } from './types';
import { buildFormData } from './types';
import { TextField } from './fields';
import TestButton from './TestButton';

export default function StepRadarrSonarr({ data, set }: { data: SetupData; set: SetField }) {
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">Radarr &amp; Sonarr</h2>
      <p className="mb-5 text-[13px] leading-relaxed text-muted">
        Optional bulk import of your existing Radarr/Sonarr libraries into Mycelium. API key:{' '}
        <a
          href="https://wiki.servarr.com/radarr/settings#security"
          target="_blank"
          rel="noreferrer"
          className="text-accent"
        >
          Radarr &rarr; Settings &rarr; General &rarr; Security
        </a>{' '}
        - same path in Sonarr.
      </p>
      <TextField
        id="RADARR_URL"
        label="Radarr URL"
        value={data.RADARR_URL}
        onChange={(v) => set('RADARR_URL', v)}
        placeholder="http://10.0.0.10:7878"
      />
      <TextField
        id="RADARR_API_KEY"
        label="Radarr API key"
        type="password"
        value={data.RADARR_API_KEY}
        onChange={(v) => set('RADARR_API_KEY', v)}
        placeholder="optional"
      />
      <TestButton kind="radarr" label="Test Radarr" buildFormData={() => buildFormData(data)} />
      <div className="mt-3.5">
        <TextField
          id="SONARR_URL"
          label="Sonarr URL"
          value={data.SONARR_URL}
          onChange={(v) => set('SONARR_URL', v)}
          placeholder="http://10.0.0.10:8989"
        />
      </div>
      <TextField
        id="SONARR_API_KEY"
        label="Sonarr API key"
        type="password"
        value={data.SONARR_API_KEY}
        onChange={(v) => set('SONARR_API_KEY', v)}
        placeholder="optional"
      />
      <TestButton kind="sonarr" label="Test Sonarr" buildFormData={() => buildFormData(data)} />
    </div>
  );
}
