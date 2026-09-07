import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../../../api';
import type { SettingsField, SettingsSection } from '../../../api';
import { Button, Select } from '../../../components/primitives';
import type { Option } from '../../../components/primitives';
import { serviceValues } from './visibility';
import type { Values } from './visibility';

/** A text input until Load succeeds, then a dropdown of what the service
 * offers with the current value kept even if the service no longer lists it. */
export function Picker({ field, value, onChange, values, sections }: {
  field: SettingsField; value: string; onChange: (next: string) => void; values: Values; sections: SettingsSection[];
}) {
  const [options, setOptions] = useState<Option[] | null>(null);
  const [err, setErr] = useState('');
  const service = (field.picker || '').split('_')[0];
  const mut = useMutation({
    mutationFn: () => api.settingsPicker(field.picker!, serviceValues(sections, service, values)),
    onSuccess: (r) => {
      if (r.ok && r.options) { setOptions(r.options); setErr(r.options.length ? '' : 'nothing to choose from yet'); }
      else setErr(r.error || 'failed');
    },
    onError: (e: Error) => setErr(e.message),
  });
  const shown = options && value && !options.some((o) => o.value === value) ? [{ value, label: value }, ...options] : options;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {shown ? (
        <Select label={field.label} value={value} onChange={onChange} options={shown} placeholder={field.placeholder ?? '(default)'} />
      ) : (
        <input type="text" aria-label={field.label} value={value} placeholder={field.placeholder ?? undefined} onChange={(e) => onChange(e.target.value)}
          className="w-full max-w-xs rounded border border-border bg-bg px-2 py-1 font-mono text-xs" />
      )}
      <Button onClick={() => mut.mutate()} loading={mut.isPending} loadingLabel="Loading..." aria-label={`Load ${field.label}`}>Load</Button>
      {err && <span className="text-xs text-danger">{err}</span>}
    </div>
  );
}
