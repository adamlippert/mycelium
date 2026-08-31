import type { SetField, SetupData } from './types';
import { TextField, CheckboxRow } from './fields';

export default function StepCatbox({ data, set }: { data: SetupData; set: SetField }) {
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">Catbox lazy mode</h2>
      <p className="mb-5 text-[13px] leading-relaxed text-muted">
        When enabled, torrents only enter TorBox when you press play, and leave after idle time.
        Lets your library grow unlimited while staying within TorBox&apos;s 30-day cache window.
      </p>
      <CheckboxRow
        id="CATBOX_MODE"
        title="Enable Catbox mode"
        description="Recommended once you've verified the basic flow works."
        checked={data.CATBOX_MODE}
        onChange={(v) => set('CATBOX_MODE', v)}
      />
      <div className="mt-3.5">
        <TextField
          id="CATBOX_HOST"
          label="Catbox host (reachable from Jellyfin)"
          value={data.CATBOX_HOST}
          onChange={(v) => set('CATBOX_HOST', v)}
          placeholder="http://10.0.0.10:8088"
          hint="This URL is written into .strm files. Must be reachable from your Jellyfin container."
        />
      </div>
    </div>
  );
}
