import type { SetField, SetupData } from './types';
import { buildFormData } from './types';
import { TextField } from './fields';
import TestButton from './TestButton';

export default function StepTorbox({ data, set }: { data: SetupData; set: SetField }) {
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">TorBox</h2>
      <p className="mb-5 text-[13px] leading-relaxed text-muted">
        Your TorBox API key. Without this Mycelium can&apos;t do anything. &rarr;{' '}
        <a href="https://torbox.app/settings" target="_blank" rel="noreferrer" className="text-accent">
          torbox.app/settings
        </a>
      </p>
      <TextField
        id="TORBOX_API_KEY"
        label="TorBox API key"
        required
        type="password"
        value={data.TORBOX_API_KEY}
        onChange={(v) => set('TORBOX_API_KEY', v)}
        placeholder="your-torbox-api-key"
      />
      <TestButton kind="torbox" label="Test connection" buildFormData={() => buildFormData(data)} />
    </div>
  );
}
