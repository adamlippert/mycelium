import type { LibraryDetail } from '../../../../api';
import { ACTIONS } from '../actions';
import { ActionButton, Copy, DrawerCard } from './DrawerCard';

export function HashesCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  if (!d.hashes.length) return null;
  return (
    <DrawerCard title="Hashes" description="Releases this title has used and whether they are blacklisted.">
      {d.hashes.map((h) => (
        <div key={h.info_hash} className="rounded border border-border p-2 text-xs">
          <div className="flex flex-wrap items-center gap-2"><span className="font-mono break-all">{h.info_hash}</span><Copy value={h.info_hash} />{h.current && <span className="text-ok">current</span>}</div>
          <div className="text-muted">
            <span>{h.blacklisted ? `blacklisted, ${h.fail_count} failures` : h.fail_count ? `${h.fail_count} failures` : 'no failures'}</span>
            {h.last_error && <span>{h.last_error}</span>}
          </div>
          <div className="mt-1">
            {h.blacklisted
              ? <ActionButton label="Unblacklist" run={() => ACTIONS.unblacklist(h.info_hash)} onDone={onDone} />
              : <ActionButton label="Blacklist" run={() => ACTIONS.blacklist(h.info_hash)} onDone={onDone} />}
          </div>
        </div>
      ))}
    </DrawerCard>
  );
}
