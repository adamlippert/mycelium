import { useState } from 'react';
import { api } from '../../../../api';
import type { LibraryDetail } from '../../../../api';
import { Button } from '../../../../components/primitives';
import { DrawerCard } from './DrawerCard';

export function ActivityCard({ d }: { d: LibraryDetail }) {
  const [extra, setExtra] = useState<LibraryDetail['activity']>([]);
  const [done, setDone] = useState(d.activity.length < 20);
  const [error, setError] = useState<string | null>(null);
  const rows = [...d.activity, ...extra];
  if (!rows.length) return null;
  const more = async () => {
    setError(null);
    try {
      const r = await api.libraryActivity(d.request.imdb_id, rows[rows.length - 1].id);
      setExtra((x) => [...x, ...r.activity]);
      if (r.activity.length < 20) setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'failed to load more activity');
    }
  };
  return (
    <DrawerCard title="Activity" description="What Mycelium did with this title, newest first.">
      <ul className="space-y-1 text-xs">
        {rows.map((a) => (
          <li key={a.id} className="flex gap-2"><span className="w-32 flex-none text-muted">{a.created_at.slice(0, 16)}</span><span className={a.success ? '' : 'text-danger'}>{a.event}</span><span className="text-muted">{a.message}</span></li>
        ))}
      </ul>
      {!done && <Button variant="ghost" onClick={more}>Load more</Button>}
      {error && <p className="text-xs text-danger">{error}</p>}
    </DrawerCard>
  );
}
