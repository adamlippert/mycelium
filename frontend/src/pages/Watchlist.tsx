import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import type { MediaType, TmdbItem } from '../types';
import PosterCard from '../components/PosterCard';
import DetailModal from '../components/DetailModal';
import { SourceCard } from '../components/watchlist/SourceCard';
import { Icon } from '../design/icons';
import { useToast } from '../components/primitives';

export default function Watchlist() {
  const [detail, setDetail] = useState<{ id: number; type: MediaType } | null>(null);
  const { data, isLoading } = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist });
  const { data: trakt } = useQuery({ queryKey: ['trakt-status'], queryFn: api.traktStatus, staleTime: 60_000 });
  const { data: mdblist } = useQuery({ queryKey: ['mdblist-status'], queryFn: api.mdblistStatus, staleTime: 60_000 });
  const queryClient = useQueryClient();
  const toast = useToast();
  const traktSync = useMutation({
    mutationFn: api.traktSync,
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
      toast('Trakt sync started', `${r.added} title${r.added === 1 ? '' : 's'} added`);
    },
    onError: (err: Error) => toast('Trakt sync failed', err.message, 'err'),
  });
  const mdblistSync = useMutation({
    mutationFn: api.mdblistSync,
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
      toast('MDBList sync started', `${r.added} title${r.added === 1 ? '' : 's'} added`);
    },
    onError: (err: Error) => toast('MDBList sync failed', err.message, 'err'),
  });

  const open = (item: TmdbItem) => setDetail({ id: item.tmdb_id, type: item.media_type });

  const sourceCards = (
    <div className="mb-5 grid gap-3 sm:grid-cols-2">
      {trakt && (
        <SourceCard
          abbr="TR" name="Trakt"
          detail={trakt.connected ? [trakt.username, trakt.synced_at && `synced ${trakt.synced_at.slice(0, 16)}`].filter(Boolean).join(' · ') : 'Connect in Settings'}
          connected={trakt.connected}
          onSync={trakt.connected ? () => traktSync.mutate() : undefined}
          syncing={traktSync.isPending}
        />
      )}
      {mdblist && (
        <SourceCard
          abbr="MD" name="MDBList"
          detail={mdblist.connected ? `${mdblist.list_ids.split(',').filter(Boolean).length} lists` : 'Connect in Settings'}
          connected={mdblist.connected}
          onSync={mdblist.connected ? () => mdblistSync.mutate() : undefined}
          syncing={mdblistSync.isPending}
        />
      )}
    </div>
  );

  let body: React.ReactNode;
  if (isLoading) {
    body = <div className="text-muted text-sm py-6">Loading...</div>;
  } else if (!data?.items.length) {
    body = (
      <div className="text-center py-16">
        <Icon name="watchlist" className="mx-auto h-10 w-10 text-muted" />
        <h2 className="text-lg font-semibold mb-1 mt-3">Your watchlist is empty</h2>
        <p className="text-muted text-sm">Add items from the Discover page to track what you want to watch.</p>
      </div>
    );
  } else {
    body = (
      <>
        <p className="text-muted text-sm mb-4">{data.items.length} items in your watchlist</p>
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 200px))' }}>
          {data.items.map((it) => (
            <PosterCard
              key={it.id}
              item={{
                tmdb_id: it.tmdb_id || 0,
                media_type: it.media_type,
                title: it.title,
                year: null,
                rating: 0,
                votes: 0,
                popularity: 0,
                overview: '',
                poster_path: it.poster_path,
                backdrop_path: null,
              }}
              onClick={open}
              status={it.library_status}
            />
          ))}
        </div>
      </>
    );
  }

  return (
    <div>
      {sourceCards}
      {body}
      <DetailModal
        tmdbId={detail?.id ?? null}
        mediaType={detail?.type ?? null}
        onClose={() => setDetail(null)}
        onSelectItem={open}
      />
    </div>
  );
}
