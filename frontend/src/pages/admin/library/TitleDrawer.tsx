import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api';
import { Button, Pill, statusLabel, statusToPillState } from '../../../components/primitives';
import { ACTIONS } from './actions';
import { ActionButton } from './cards/DrawerCard';
import { StatusCard } from './cards/StatusCard';
import { ReleaseCard } from './cards/ReleaseCard';
import { PlayabilityCard } from './cards/PlayabilityCard';
import { EpisodesCard } from './cards/EpisodesCard';
import { RequestsCard } from './cards/RequestsCard';
import { PreferencesCard } from './cards/PreferencesCard';
import { ArrCard } from './cards/ArrCard';
import { HashesCard } from './cards/HashesCard';
import { ActivityCard } from './cards/ActivityCard';

export function TitleDrawer({ imdb, onClose, onChanged, onPurged }: {
  imdb: string; onClose: () => void; onChanged: () => void; onPurged?: (imdb: string) => void;
}) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['library-detail', imdb], queryFn: () => api.libraryDetail(imdb) });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const refresh = () => { qc.invalidateQueries({ queryKey: ['library-detail', imdb] }); onChanged(); };
  const d = q.data;
  return (
    <aside role="dialog" aria-label="Title details" className="fixed inset-y-0 right-0 z-20 w-full max-w-[560px] overflow-y-auto border-l border-border bg-bg p-5 shadow-2xl">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold">{d ? d.request.title : 'Loading...'}</h2>
          {d && <div className="mt-1 flex items-center gap-2 text-xs text-muted">
            <span>{d.request.media_type === 'movie' ? 'Movie' : 'Series'}</span><span className="font-mono">{d.request.imdb_id}</span>
            <Pill state={statusToPillState(d.request.status)}>{statusLabel(d.request.status)}</Pill>
          </div>}
        </div>
        <Button variant="ghost" aria-label="Close" onClick={onClose}>&times;</Button>
      </div>
      {q.error && <p className="mt-4 text-sm text-danger">{(q.error as Error).message}</p>}
      {d && (
        <div className="mt-4 space-y-4">
          <div className="flex flex-wrap gap-2">
            <ActionButton label="Retry" run={() => ACTIONS.retry(d)} onDone={refresh} variant="primary" />
            <ActionButton label="Re-resolve" run={() => ACTIONS.reresolve(d)} onDone={refresh} />
            <ActionButton label="Mirror to arr" run={() => ACTIONS.mirror(d)} onDone={refresh} />
            <ActionButton label="Blacklist current hash" run={() => ACTIONS.blacklistCurrent(d)} onDone={refresh} />
            <ActionButton label="Purge" run={() => ACTIONS.purge(d)} onDone={() => { onPurged?.(d.request.imdb_id); onChanged(); onClose(); }}
              confirm={`Remove "${d.request.title}" from the library? Its files, monitoring and request go too.`} />
            <ActionButton label="Forget request" run={() => ACTIONS.forget(d)} onDone={() => { onPurged?.(d.request.imdb_id); onChanged(); onClose(); }}
              confirm={`Forget the request for "${d.request.title}" but keep its files? It disappears from the Library table; the files stay in Jellyfin.`} />
          </div>
          <StatusCard d={d} onDone={refresh} />
          <ReleaseCard d={d} />
          <PlayabilityCard d={d} onDone={refresh} />
          <EpisodesCard d={d} onDone={refresh} />
          <RequestsCard d={d} onDone={refresh} />
          <PreferencesCard d={d} onDone={refresh} />
          <ArrCard d={d} onDone={refresh} />
          <HashesCard d={d} onDone={refresh} />
          <ActivityCard d={d} />
        </div>
      )}
    </aside>
  );
}
