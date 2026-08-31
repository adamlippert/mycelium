import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, tmdbImg } from '../../api';
import type { MediaType, TmdbItem, WatchlistItem } from '../../types';
import TrailerModal from '../TrailerModal';
import PersonModal from '../PersonModal';
import { usePluginSlot } from '../../hooks/usePluginSlots';
import { useWatched } from '../../hooks/useWatched';
import { useToast } from '../primitives';
import { Header } from './Header';
import { Seasons } from './Seasons';
import { Cast } from './Cast';
import { Similar } from './Similar';
import type { AddStatus } from './LibraryButton';

export default function DetailModal({
  tmdbId,
  mediaType,
  onClose,
  onSelectItem,
}: {
  tmdbId: number | null;
  mediaType: MediaType | null;
  onClose: () => void;
  onSelectItem: (item: TmdbItem) => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const open = tmdbId !== null && mediaType !== null;

  const { data: detail, isLoading } = useQuery({
    queryKey: ['detail', mediaType, tmdbId],
    queryFn: () => api.details(mediaType!, tmdbId!),
    enabled: open,
  });

  const { data: watchlist } = useQuery({
    queryKey: ['watchlist'],
    queryFn: api.watchlist,
  });

  const inWatchlist =
    detail?.imdb_id &&
    watchlist?.items.some(
      (w: WatchlistItem) => w.imdb_id === detail.imdb_id && w.media_type === detail.media_type,
    );

  const libStatus = detail?.library_status as string | undefined;
  const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session });
  // webplayer_enabled is injected by the webplayer plugin; absent when plugin not loaded
  const canPlay = !!(session?.user as any)?.webplayer_enabled;
  const PlayerModal = usePluginSlot('episode-player');
  const watched = useWatched();
  const isWatched = !!(detail?.imdb_id && watched.has(detail.imdb_id));

  const [addStatus, setAddStatus] = useState<AddStatus>(
    'idle',
  );
  const [pollingImdbId, setPollingImdbId] = useState<string | null>(null);
  const [personId, setPersonId] = useState<number | null>(null);

  // Poll request status until a terminal state is reached or 3 min timeout
  useEffect(() => {
    if (!pollingImdbId) return;
    const deadline = Date.now() + 3 * 60 * 1000;
    const interval = setInterval(async () => {
      try {
        if (Date.now() > deadline) {
          setAddStatus('error');
          setPollingImdbId(null);
          return;
        }
        const res = await fetch(`/ui/api/requests/status?imdb_id=${pollingImdbId}`);
        if (res.status === 401) {
          // Session expired mid-poll - match api.ts's http() wrapper behavior
          // instead of silently polling a dead session for up to 3 minutes.
          setPollingImdbId(null);
          if (!window.location.pathname.endsWith('/login')) window.location.href = '/login';
          return;
        }
        if (!res.ok) return;
        const data = await res.json();
        if (data.status === 'success') {
          setAddStatus('added');
          setPollingImdbId(null);
          queryClient.invalidateQueries({ queryKey: ['detail', mediaType, tmdbId] });
        } else if (data.status === 'wanted') {
          setAddStatus('wanted');
          setPollingImdbId(null);
        } else if (data.status === 'upcoming') {
          setAddStatus('upcoming');
          setPollingImdbId(null);
        } else if (data.status === 'failed' || data.status === 'rate_limited') {
          setAddStatus('error');
          setPollingImdbId(null);
        }
      } catch { /* ignore */ }
    }, 1000);
    return () => clearInterval(interval);
  }, [pollingImdbId, queryClient, mediaType, tmdbId]);

  // TV monitoring scope
  const [showTrailer, setShowTrailer] = useState(false);
  const [showPlayer, setShowPlayer] = useState(false);
  const [monitorMode, setMonitorMode] = useState<'all' | 'future' | 'selected'>('all');
  const [selectedSeasons, setSelectedSeasons] = useState<number[]>([]);

  const addMutation = useMutation({
    mutationFn: () =>
      api.addToLibrary(
        detail!.tmdb_id,
        detail!.media_type,
        detail!.title,
        detail!.media_type === 'tv'
          ? { monitor_mode: monitorMode, seasons: selectedSeasons }
          : undefined,
      ),
    onMutate: () => setAddStatus('adding'),
    onSuccess: (r) => {
      if (r.status === 'pending') {
        setAddStatus('pending');
        toast('Request submitted', 'Waiting for admin approval');
      } else if (r.imdb_id) {
        setPollingImdbId(r.imdb_id);
        toast('Request submitted', 'Looking for a release…');
      } else if (r.error) {
        setAddStatus('error');
        toast('Request failed', r.error, 'err');
      } else {
        setAddStatus('added');
        toast('Added to library');
      }
    },
    onError: (err: Error) => {
      setAddStatus('error');
      toast('Request failed', err.message, 'err');
    },
  });

  const toggleSeason = (n: number) =>
    setSelectedSeasons((prev) =>
      prev.includes(n) ? prev.filter((x) => x !== n) : [...prev, n].sort((a, b) => a - b),
    );

  const watchlistMutation = useMutation({
    mutationFn: async () => {
      if (!detail?.imdb_id) throw new Error('no imdb id');
      if (inWatchlist) {
        return api.watchlistRemove(detail.imdb_id, detail.media_type);
      }
      return api.watchlistAdd({
        imdb_id: detail.imdb_id,
        tmdb_id: detail.tmdb_id,
        media_type: detail.media_type,
        title: detail.title,
        poster_path: detail.poster_path,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] });
    },
  });

  // Reset state when modal opens fresh
  useEffect(() => {
    if (open) { setAddStatus('idle'); setShowTrailer(false); setShowPlayer(false); }
  }, [open, tmdbId]);

  // Esc to close
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const poster = tmdbImg.poster(detail?.poster_path);
  const backdrop = tmdbImg.backdrop(detail?.backdrop_path);
  const trailer = detail?.trailers?.[0];

  return createPortal(
    <>
    <div
      className="fixed inset-0 z-[200] bg-black/70 backdrop-blur-sm overflow-y-auto p-4 sm:p-8"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="relative max-w-5xl mx-auto bg-card border border-border rounded-xl overflow-hidden shadow-2xl">
        {/* Backdrop hero */}
        {backdrop && (
          <div
            className="h-64 sm:h-80 bg-cover bg-center relative"
            style={{ backgroundImage: `url(${backdrop})` }}
          >
            <div className="absolute inset-0 bg-gradient-to-t from-card via-card/60 to-transparent" />
          </div>
        )}
        <button
          type="button"
          onClick={onClose}
          className="absolute top-3 right-3 z-10 w-9 h-9 rounded-full bg-black/60 hover:bg-black/80
                      text-white text-xl flex items-center justify-center"
          aria-label="Close"
        >
          ×
        </button>

        <div className={`p-6 sm:p-8 ${backdrop ? '-mt-32 relative' : ''}`}>
          {isLoading || !detail ? (
            <div className="text-muted text-center py-12">Loading…</div>
          ) : (
            <Header
              detail={detail}
              poster={poster}
              isWatched={isWatched}
              libStatus={libStatus}
              addStatus={addStatus}
              monitorMode={monitorMode}
              setMonitorMode={setMonitorMode}
              selectedSeasons={selectedSeasons}
              toggleSeason={toggleSeason}
              addMutation={addMutation}
              canPlay={canPlay}
              setShowPlayer={setShowPlayer}
              watchlistMutation={watchlistMutation}
              inWatchlist={inWatchlist}
              trailer={trailer}
              setShowTrailer={setShowTrailer}
            />
          )}

          {detail?.media_type === 'tv' && detail.seasons && detail.seasons.length > 0 && (
            <Seasons seasons={detail.seasons} />
          )}

          {detail?.cast && detail.cast.length > 0 && (
            <Cast cast={detail.cast} onSelectPerson={setPersonId} />
          )}

          {detail?.recommendations && detail.recommendations.length > 0 && (
            <Similar recommendations={detail.recommendations} onSelectItem={onSelectItem} />
          )}
        </div>
      </div>
    </div>
    {showTrailer && (
      <TrailerModal
        youtubeKey={trailer ? trailer.key : null}
        title={detail?.title || ''}
        onClose={() => setShowTrailer(false)}
      />
    )}
    {showPlayer && detail?.imdb_id && PlayerModal && (
      <PlayerModal
        imdb_id={detail.imdb_id}
        media_type={detail.media_type}
        title={detail.title}
        onClose={() => setShowPlayer(false)}
      />
    )}
    <PersonModal
      personId={personId}
      onClose={() => setPersonId(null)}
      onSelectItem={(item) => { setPersonId(null); onSelectItem(item); }}
    />
  </>,
  document.body
  );
}
