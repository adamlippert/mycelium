import type { LibraryDetail } from '../../../../api';
import { Pill, statusLabel, statusToPillState } from '../../../../components/primitives';
import { ACTIONS } from '../actions';
import { ActionButton, DrawerCard, Row } from './DrawerCard';

export function StatusCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  const r = d.request;
  return (
    <DrawerCard title="Status" description="Where this title stands and what is scheduled for it.">
      <Row label="Status"><Pill state={statusToPillState(r.status)}>{statusLabel(r.status)}</Pill></Row>
      {r.error && <Row label="Last error">{r.error}</Row>}
      <Row label="Changed">{r.updated_at}</Row>
      {r.status === 'pending' && <p className="text-xs text-muted">The processor has this title now.</p>}
      {d.retry && (
        <>
          <Row label="Retry queue">attempt {d.retry.attempt}, next at {d.retry.next_retry_at}</Row>
          <div className="flex gap-2">
            <ActionButton label="Retry now" run={() => ACTIONS.retryNow(d)} onDone={onDone} />
            <ActionButton label="Drop from queue" run={() => ACTIONS.dropRetry(d)} onDone={onDone} />
          </div>
        </>
      )}
      {d.wanted_movie && <Row label="Wanted">{d.wanted_movie.reason || 'no release yet'}, {d.wanted_movie.attempts} attempts, last {d.wanted_movie.last_checked || 'never'}</Row>}
    </DrawerCard>
  );
}
