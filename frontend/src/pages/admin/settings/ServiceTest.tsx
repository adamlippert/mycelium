import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../../../api';
import type { SettingsSection } from '../../../api';
import { Button } from '../../../components/primitives';
import type { Endpoint } from './FieldList';
import { serviceValues } from './visibility';
import type { Values } from './visibility';

export function ServiceTest({ service, label, sections, values, endpoint = 'settings' }: {
  service: string; label: string; sections: SettingsSection[]; values: Values; endpoint?: Endpoint;
}) {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const mut = useMutation({
    mutationFn: () => (endpoint === 'setup' ? api.setupTest : api.settingsTest)(service, serviceValues(sections, service, values)),
    onSuccess: (r) => setMsg({ ok: r.ok, text: r.message }),
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  });
  return (
    <div className="flex flex-wrap items-center gap-2 py-2">
      <Button onClick={() => mut.mutate()} loading={mut.isPending} loadingLabel="Testing...">{`Test ${label}`}</Button>
      {msg && <span className={`text-xs ${msg.ok ? 'text-ok' : 'text-danger'}`}>{msg.text}</span>}
    </div>
  );
}
