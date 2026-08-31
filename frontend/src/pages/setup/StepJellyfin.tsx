import type { SetField, SetupData } from './types';
import { buildFormData } from './types';
import { TextField } from './fields';
import TestButton from './TestButton';

export default function StepJellyfin({ data, set }: { data: SetupData; set: SetField }) {
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">Jellyfin</h2>
      <p className="mb-5 text-[13px] leading-relaxed text-muted">
        Optional but recommended. Mycelium triggers library scans after adding new content. &rarr;{' '}
        <a
          href="https://jellyfin.org/docs/general/server/api/"
          target="_blank"
          rel="noreferrer"
          className="text-accent"
        >
          Jellyfin &rarr; Dashboard &rarr; API Keys
        </a>
      </p>
      <TextField
        id="JELLYFIN_URL"
        label="Jellyfin URL"
        value={data.JELLYFIN_URL}
        onChange={(v) => set('JELLYFIN_URL', v)}
        placeholder="http://10.0.0.10:8096"
      />
      <TextField
        id="JELLYFIN_API_KEY"
        label="Jellyfin API key"
        type="password"
        value={data.JELLYFIN_API_KEY}
        onChange={(v) => set('JELLYFIN_API_KEY', v)}
        placeholder="optional"
      />
      <TestButton kind="jellyfin" label="Test connection" buildFormData={() => buildFormData(data)} />
    </div>
  );
}
