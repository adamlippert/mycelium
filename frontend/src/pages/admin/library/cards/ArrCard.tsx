import type { LibraryDetail } from '../../../../api';
import { ACTIONS } from '../actions';
import { ActionButton, DrawerCard, Row } from './DrawerCard';

export function ArrCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  return (
    <DrawerCard title="Arr mirror" description="Whether Radarr or Sonarr knows this title.">
      <Row label="Mirrored">{d.arr.mirrored_at ? `since ${d.arr.mirrored_at}` : 'no'}</Row>
      <div className="flex gap-2">
        <ActionButton label="Mirror now" run={() => ACTIONS.mirror(d)} onDone={onDone} />
        {d.arr.mirrored_at && <ActionButton label="Remove from arr" run={() => ACTIONS.unmirror(d)} onDone={onDone} />}
      </div>
    </DrawerCard>
  );
}
