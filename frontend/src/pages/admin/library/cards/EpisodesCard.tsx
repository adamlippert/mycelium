import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../../api';
import type { LibraryDetail } from '../../../../api';
import { Button } from '../../../../components/primitives';
import { ACTIONS } from '../actions';
import { ActionButton, DrawerCard, Row } from './DrawerCard';

function Season({ d, season, onDone }: { d: LibraryDetail; season: { season: number; present: number; wanted: number }; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ['library-season', d.request.imdb_id, season.season], queryFn: () => api.librarySeason(d.request.imdb_id, season.season), enabled: open });
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    <div className="rounded border border-border p-2 text-xs">
      <div className="flex items-center justify-between">
        <span>Season {season.season}: {season.present} present, {season.wanted} wanted</span>
        <Button variant="ghost" aria-label={`${open ? 'Collapse' : 'Expand'} season ${season.season}`} onClick={() => setOpen((o) => !o)}>{open ? 'Hide' : 'Show'}</Button>
      </div>
      {open && q.data && (
        <ul className="mt-2 space-y-1">
          {q.data.episodes.map((e) => (
            <li key={e.episode} className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <span className="font-mono">E{pad(e.episode)}</span>
                <span className="text-muted">{e.present ? '✓' : e.wanted_status || 'missing'}{e.air_date ? `, aired ${e.air_date}` : ''}{e.attempt_count ? `, ${e.attempt_count} attempts` : ''}{e.last_attempted ? `, last try ${e.last_attempted.slice(0, 16)}` : ''}</span>
              </span>
              {!e.present && <ActionButton label={`Retry S${pad(season.season)}E${pad(e.episode)}`} run={() => ACTIONS.retryEpisode(d, season.season, e.episode)} onDone={onDone} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function EpisodesCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  if (!d.episodes) return null;
  return (
    <DrawerCard title="Episodes" description="Seasons Mycelium tracks for this series.">
      {d.monitored && <Row label="Monitor">{d.monitored.status}, last check {d.monitored.last_checked || 'never'}</Row>}
      {d.episodes.map((s) => <Season key={s.season} d={d} season={s} onDone={onDone} />)}
      <ActionButton label="Recheck series" run={() => ACTIONS.recheckSeries(d)} onDone={onDone} />
    </DrawerCard>
  );
}
