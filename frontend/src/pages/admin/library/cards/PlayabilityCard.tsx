import type { LibraryDetail } from '../../../../api';
import { ACTIONS } from '../actions';
import { ActionButton, DrawerCard, Row } from './DrawerCard';

export function PlayabilityCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  if (!d.playability.length) return null;
  return (
    <DrawerCard title="Playability" description="What happened the last times someone pressed play.">
      {d.playability.map((p) => (
        <div key={p.content_key} className="rounded border border-border p-2 text-xs">
          <Row label="Key">{p.content_key}</Row>
          <Row label="State">{p.status}{p.consecutive_failures ? `, ${p.consecutive_failures} failures in a row` : ''}</Row>
          {p.last_ok_provider && <Row label="Last ok">{p.last_ok_provider} at {p.last_ok_at}</Row>}
          {p.last_fail_reason && <Row label="Last failure">{p.last_fail_reason}</Row>}
        </div>
      ))}
      <div className="flex gap-2">
        <ActionButton label="Re-resolve" run={() => ACTIONS.reresolve(d)} onDone={onDone} />
        <ActionButton label="Reset" run={() => ACTIONS.resetPlayability(d)} onDone={onDone} />
      </div>
    </DrawerCard>
  );
}
