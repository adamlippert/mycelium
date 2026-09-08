import { useState } from 'react';
import { api } from '../../../api';
import type { AdminRequestRow } from '../../../api';
import { Button } from '../../../components/primitives';
import { ActionButton } from '../library/cards/DrawerCard';

export function RowActions({ row, overQuota, onDone }: { row: AdminRequestRow; overQuota: boolean; onDone: () => void }) {
  const [denying, setDenying] = useState(false);
  const [note, setNote] = useState('');
  if (row.status === 'approved') return null;
  const approve = () => api.approveRequest(row.id).then((r) => ({ ok: r.ok, message: r.ok ? 'approved' : 'approve failed' }));
  const deny = () => api.denyRequest(row.id, note.trim() || undefined).then((r) => ({ ok: r.ok, message: r.ok ? 'denied' : 'deny failed' }));
  if (denying) {
    return (
      <span className="inline-flex items-center gap-1">
        <input aria-label="Reason" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reason (optional)"
          className="w-40 rounded border border-border bg-bg px-2 py-1 text-xs" />
        <ActionButton label="Confirm" variant="primary" run={deny} onDone={() => { setDenying(false); setNote(''); onDone(); }} />
        <Button variant="ghost" onClick={() => { setDenying(false); setNote(''); }}>Cancel</Button>
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {row.status === 'denied' && (
        <ActionButton label="Reopen" run={() => api.reopenRequest(row.id)} onDone={onDone} />
      )}
      <ActionButton label="Approve" variant="primary" run={approve} onDone={onDone} />
      {overQuota && <span className="text-[10px] text-warn" title="This user is at the monthly quota; approving still works">over quota</span>}
      {row.status === 'pending' && <Button onClick={() => setDenying(true)}>Deny</Button>}
    </span>
  );
}
