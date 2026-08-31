import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, tmdbImg } from '../../api';
import type { TmdbItem } from '../../types';

function fmtRuntime(min?: number) {
  if (!min) return null;
  return `${Math.floor(min / 60)}h ${min % 60}m`;
}

export function Hero({
  onRequest,
  onWatchlist,
}: {
  onRequest: (item: TmdbItem) => void;
  onWatchlist: (item: TmdbItem) => Promise<unknown> | void;
}) {
  const [watchlistPending, setWatchlistPending] = useState(false);
  // Discover's trending Row uses this exact key and unwraps .results in its
  // own fetcher. React Query stores one entry per key, so returning the raw
  // {results: [...]} envelope here would hand the Row an object to map over,
  // whichever query resolved first. Both sides must cache the same shape.
  const { data: trending } = useQuery({
    queryKey: ['trending', 'all', 'week'],
    queryFn: () => api.trending('all', 'week').then((r) => r.results),
    staleTime: 5 * 60_000,
  });
  const top = trending?.[0];
  const { data: detail } = useQuery({
    queryKey: ['hero-detail', top?.media_type, top?.tmdb_id],
    queryFn: () => api.details(top!.media_type, top!.tmdb_id),
    enabled: !!top,
    staleTime: 5 * 60_000,
  });

  if (!top) return null;

  const backdrop = tmdbImg.backdrop(top.backdrop_path);
  const runtime = fmtRuntime(detail?.runtime);
  const genres = detail?.genres?.slice(0, 3).join(' · ');

  const handleWatchlist = async () => {
    setWatchlistPending(true);
    try {
      await onWatchlist(detail ?? top);
    } finally {
      setWatchlistPending(false);
    }
  };

  return (
    <section
      className="relative -mx-4 lg:-mx-8 mb-8 overflow-hidden"
      aria-label="Featured title"
    >
      {backdrop && (
        <img
          src={backdrop}
          alt=""
          aria-hidden="true"
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
      <div className="absolute inset-0 bg-gradient-to-r from-bg via-bg/70 to-transparent" />
      <div className="absolute inset-0 bg-gradient-to-t from-bg via-transparent to-transparent" />
      <div className="relative px-4 lg:px-8 py-14 lg:py-20 max-w-2xl">
        <div className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider">
          <span className="rounded-md px-2 py-1 text-white" style={{ background: 'rgba(97,82,223,0.88)' }}>
            Featured
          </span>
          <span className="text-accent-pale">Trending #1 this week</span>
        </div>
        <h2 className="text-3xl lg:text-4xl font-bold text-white">{top.title}</h2>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-body">
          {top.rating > 0 && (
            <span className="rounded px-1.5 py-0.5 font-semibold"
                  style={{ background: 'rgba(198,178,83,0.9)', color: '#070707' }}>
              {top.rating}
            </span>
          )}
          {top.year && <span>{top.year}</span>}
          {runtime && <><span className="text-muted">&middot;</span><span>{runtime}</span></>}
          {genres && <><span className="text-muted">&middot;</span><span>{genres}</span></>}
        </div>
        {top.overview && (
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted line-clamp-3">{top.overview}</p>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onRequest(top)}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-light"
          >
            Request title
          </button>
          <button
            type="button"
            onClick={handleWatchlist}
            disabled={watchlistPending}
            className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-body hover:border-accent-light/50 disabled:opacity-50"
          >
            Watchlist
          </button>
        </div>
      </div>
    </section>
  );
}
