import type { LibraryDetail } from '../../../../api';
import { Pill, statusLabel, statusToPillState } from '../../../../components/primitives';
import { DrawerCard } from './DrawerCard';

export function RequestsCard({ d }: { d: LibraryDetail; onDone?: () => void }) {
  if (!d.user_requests.length && !d.seerr_request_id) return null;
  return (
    <DrawerCard title="Requests" description="Who asked for this title and what happened to the request.">
      {d.user_requests.map((u) => (
        <div key={u.id} className="rounded border border-border p-2 text-xs">
          <div className="flex items-center justify-between"><span className="font-medium">{u.username}</span><Pill state={statusToPillState(u.status)}>{statusLabel(u.status)}</Pill></div>
          <div className="text-muted">requested {u.created_at}{u.reviewer ? `, ${u.status} by ${u.reviewer} ${u.reviewed_at || ''}` : ''}</div>
          {u.note && <div className="mt-1">{u.note}</div>}
        </div>
      ))}
      {d.seerr_request_id && <div className="text-xs text-muted">Seerr request {d.seerr_request_id}</div>}
    </DrawerCard>
  );
}
