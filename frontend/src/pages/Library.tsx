import { useState, useMemo, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { usePluginSlot } from '../hooks/usePluginSlots';
import PosterCard from '../components/PosterCard';
import DetailModal from '../components/DetailModal';
import { StatTile, Chip, DataTable, Pill, statusLabel, statusToPillState } from '../components/primitives';
import type { Column } from '../components/primitives';
import type { TmdbItem } from '../types';

// Mockup's type filter row is All/Movies/Series/Materialized/Lazy/Needs repair.
// Materialized/Lazy/Needs repair need per-title virtual_items state that no current
// endpoint exposes (see Plan 3); only the type split the page's data can answer
// (All/Movies/Series) is implemented here.
type Tab = 'all' | 'movies' | 'series';

const PAGE_SIZE = 24;

function formatAdded(created_at: string | undefined): string {
  if (!created_at) return '-';
  const d = new Date(created_at);
  return Number.isNaN(d.getTime()) ? '-' : d.toLocaleDateString();
}

// Columns limited to fields the /ui/api/library/movies response actually carries
// (title, year, quality, status, created_at); nothing invented.
const movieColumns: Column<any>[] = [
  { key: 'title', header: 'Title', render: (m) => m.title },
  { key: 'year', header: 'Year', render: (m) => (m.year ? String(m.year) : '-') },
  { key: 'quality', header: 'Quality', render: (m) => m.quality || '-' },
  { key: 'state', header: 'State', render: (m) => <Pill state={statusToPillState(m.status || 'lazy')}>{statusLabel(m.status || 'lazy')}</Pill> },
  { key: 'added', header: 'Added', render: (m) => formatAdded(m.created_at) },
];

export default function Library() {
  const [tab, setTab] = useState<Tab>('movies');
  const { data: stats } = useQuery({ queryKey: ['stats'], queryFn: api.stats, staleTime: 60_000 });
  return (
    <div>
      {stats && (
        <div className="mb-5 grid grid-cols-1 sm:grid-cols-3 gap-3">
          <StatTile value={String(stats.library.movie_count + stats.library.series_count)} label="Titles" glow="accent" />
          <StatTile value={String(stats.library.episode_count)} label="Episodes" />
          <StatTile value={`${Math.round(stats.requests.success_rate_7d)}%`} label="Success rate 7d" glow="ok" />
        </div>
      )}
      <div className="flex gap-2 mb-5">
        {([
          ['all', 'All'],
          ['movies', 'Movies'],
          ['series', 'Series'],
        ] as [Tab, string][]).map(([t, label]) => (
          <Chip key={t} label={label} selected={tab === t} onClick={() => setTab(t)} />
        ))}
      </div>
      {tab !== 'series' && <MoviesPanel />}
      {tab !== 'movies' && <SeriesPanel />}
    </div>
  );
}

function MoviesPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ['library-movies'],
    queryFn: api.libraryMovies,
  });
  const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session });
  const clickJellyfin = !!(session?.user as any)?.library_click_jellyfin;

  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<'all' | 'available' | 'wanted'>('all');
  const [view, setView] = useState<'grid' | 'table'>('grid');
  const [modalItem, setModalItem] = useState<{ tmdb_id: number; media_type: string; title: string } | null>(null);

  const items = useMemo(() => data?.items || [], [data]);

  // Pre-fetch all Jellyfin item IDs when Jellyfin mode is on.
  // Stored as a Map so clicking is always synchronous (no popup blocker).
  const allImdbIds = useMemo(() => items.map((m: any) => m.imdb_id).filter(Boolean), [items]);
  const { data: jellyfinData } = useQuery({
    queryKey: ['jellyfin-items', allImdbIds],
    queryFn: () => api.jellyfinItems(allImdbIds),
    enabled: clickJellyfin && allImdbIds.length > 0,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const jellyfinMap: Record<string, string | null> = jellyfinData?.items ?? {};
  const jellyfinUrl = jellyfinData?.jellyfin_url ?? session?.jellyfin_url ?? null;

  const filtered = useMemo(() => {
    let list = items;
    if (filter === 'available') list = list.filter((m: any) => m.status === 'success');
    else if (filter === 'wanted') list = list.filter((m: any) => m.status !== 'success');
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((m: any) => (m.title || '').toLowerCase().includes(q));
    }
    return list;
  }, [items, filter, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginated = useMemo(
    () => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filtered, page],
  );

  const handleSearch = (v: string) => { setSearch(v); setPage(1); };
  const handleFilter = (v: typeof filter) => { setFilter(v); setPage(1); };

  const openModal = useCallback(async (m: any) => {
    // Resolve tmdb_id if missing (older items may not have it)
    let tmdbId: number | null = m.tmdb_id ?? null;
    let mediaType: string = m.media_type ?? 'movie';
    if (!tmdbId && m.imdb_id) {
      try {
        const found = await api.tmdbFind(m.imdb_id);
        if (found.tmdb_id) { tmdbId = found.tmdb_id; mediaType = found.media_type ?? 'movie'; }
      } catch { /* ignore */ }
    }
    if (tmdbId) setModalItem({ tmdb_id: tmdbId, media_type: mediaType, title: m.title });
  }, []);

  const handlePosterClick = useCallback((m: any) => {
    if (clickJellyfin && m.imdb_id && m.status === 'success') {
      const jid = jellyfinMap[m.imdb_id];
      const jurl = (jellyfinData?.jellyfin_url || jellyfinUrl || '').replace(/\/$/, '');
      if (jid && jurl) {
        window.open(`${jurl}/web/index.html#!/details?id=${jid}`, '_blank');
        return;
      }
      // Item not in Jellyfin or URL not configured: fall through to modal
    }
    openModal(m);
  }, [clickJellyfin, jellyfinUrl, jellyfinData, jellyfinMap, openModal]);

  if (isLoading) return <div className="text-muted">Loading...</div>;

  const available = items.filter((m: any) => m.status === 'success').length;
  const wanted    = items.length - available;

  return (
    <>
      {/* Toolbar */}
      <div className="flex flex-col sm:flex-row gap-3 mb-3">
        <input
          type="search"
          placeholder="Search movies..."
          value={search}
          onChange={(e) => handleSearch(e.target.value)}
          className="flex-1 bg-card border border-border rounded-lg px-3 py-2 text-sm
                     placeholder:text-muted focus:outline-none focus:border-accent"
        />
        <div className="flex gap-1">
          {([
            ['all',       `All (${items.length})`],
            ['available', `Available (${available})`],
            ['wanted',    `Wanted (${wanted})`],
          ] as const).map(([v, label]) => (
            <Chip key={v} label={label} selected={filter === v} onClick={() => handleFilter(v)} />
          ))}
        </div>
      </div>

      {/* View toggle */}
      <div className="flex justify-end gap-1 mb-3">
        <Chip label="Grid" selected={view === 'grid'} onClick={() => setView('grid')} />
        <Chip label="Table" selected={view === 'table'} onClick={() => setView('table')} />
      </div>

      {/* Poster grid / table */}
      {paginated.length === 0 ? (
        <p className="text-muted text-sm py-8 text-center">No movies found.</p>
      ) : view === 'table' ? (
        <DataTable columns={movieColumns} rows={paginated} empty="No movies found." />
      ) : (
        <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 200px))' }}>
          {paginated.map((m: any) => (
            <LibraryPosterCard
              key={m.imdb_id}
              movie={m}
              onClick={() => handlePosterClick(m)}
            />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-6">
          <button
            type="button"
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1 rounded border border-border text-sm text-muted
                       hover:text-white disabled:opacity-30 transition"
          >
            Prev
          </button>
          <span className="text-sm text-muted">
            {page} / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-3 py-1 rounded border border-border text-sm text-muted
                       hover:text-white disabled:opacity-30 transition"
          >
            Next
          </button>
        </div>
      )}

      {/* Detail modal */}
      {modalItem && (
        <DetailModal
          tmdbId={modalItem.tmdb_id}
          mediaType={modalItem.media_type as any}
          onClose={() => setModalItem(null)}
          onSelectItem={(item: TmdbItem) => {
            if (item.tmdb_id) setModalItem({ tmdb_id: item.tmdb_id, media_type: item.media_type, title: item.title });
          }}
        />
      )}
    </>
  );
}

/** Wraps PosterCard with lazy poster fetching for library items that lack a cached poster_path. */
function LibraryPosterCard({ movie, onClick }: { movie: any; onClick: () => void }) {
  // Lazy-fetch poster when not already cached in the library response
  const { data: lazyPoster } = useQuery({
    queryKey: ['poster', movie.imdb_id],
    queryFn: () => fetch(`/ui/api/poster/${movie.imdb_id}?type=movie`).then(r => {
      if (!r.ok) throw new Error(`${r.status}`);
      return r.json();
    }),
    enabled: !movie.poster_path && !!movie.imdb_id,
    staleTime: Infinity,
    retry: false,
  });

  // poster_path is a TMDB relative path; lazyPoster.poster is already a full URL,
  // so we store it as a fake path by stripping the base prefix PosterCard will re-add.
  const resolvedPath: string | null =
    movie.poster_path ??
    (lazyPoster?.poster
      ? lazyPoster.poster.replace(/^https:\/\/image\.tmdb\.org\/t\/p\/w\d+/, '')
      : null);

  const item: TmdbItem = {
    tmdb_id:      movie.tmdb_id ?? 0,
    media_type:   'movie',
    title:        movie.title,
    year:         movie.year ? String(movie.year) : null,
    rating:       0,
    votes:        0,
    popularity:   0,
    overview:     '',
    poster_path:  resolvedPath,
    backdrop_path: null,
    imdb_id:      movie.imdb_id,
    library_status: movie.status,
  } as TmdbItem & { imdb_id?: string };

  return <PosterCard item={item} onClick={() => onClick()} status={movie.status} />;
}

function SeriesPanel() {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const { data, isLoading } = useQuery({
    queryKey: ['library-series-episodes'],
    queryFn: () => fetch('/ui/api/library/series-episodes').then(r => {
      if (!r.ok) throw new Error(`${r.status}`);
      return r.json();
    }),
  });
  const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session });
  const canPlay = !!(session?.user as any)?.webplayer_enabled;
  const traktConnected = !!(session?.user as any)?.trakt_connected;
  const PlayerModal = usePluginSlot('episode-player');
  const [playEp, setPlayEp] = useState<{
    imdb_id: string; season: number; episode: number; title: string
  } | null>(null);

  // Per-episode watched data: only fetch when trakt is connected
  const { data: watchedEpsData } = useQuery({
    queryKey: ['trakt-watched-episodes'],
    queryFn: api.traktWatchedEpisodes,
    enabled: traktConnected,
    staleTime: 5 * 60 * 1000,
  });
  // watchedEps: { imdb_id: { "1": [1,2,3], "2": [1] } }
  const watchedEps = useMemo(
    () => watchedEpsData?.shows ?? {},
    [watchedEpsData],
  );

  const allSeries: any[] = useMemo(() => data?.series || [], [data]);
  const series = useMemo(() => {
    if (!search.trim()) return allSeries;
    const q = search.trim().toLowerCase();
    return allSeries.filter((s: any) => (s.title || '').toLowerCase().includes(q));
  }, [allSeries, search]);

  if (isLoading) return <div className="text-muted">Loading...</div>;

  const toggle = (title: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(title) ? next.delete(title) : next.add(title);
      return next;
    });
  };

  return (
    <>
    <div>
      <div className="flex flex-col sm:flex-row gap-3 mb-3">
        <input
          type="search"
          placeholder="Search series..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 bg-card border border-border rounded-lg px-3 py-2 text-sm
                     placeholder:text-muted focus:outline-none focus:border-accent"
        />
      </div>
      <p className="text-muted text-sm mb-4">{allSeries.length} series in library</p>
      {series.length === 0 ? (
        <p className="text-muted text-sm py-8 text-center">No series found.</p>
      ) : (
      <div className="space-y-1">
        {series.map((s: any) => {
          const isOpen = expanded.has(s.title);
          const totalEps = s.seasons.reduce((n: number, se: any) => n + se.episodes.length, 0);
          const missingList: {season: number; episode: number}[] = s.missing || [];
          const missingCount = missingList.length;
          const missingSet = new Set(missingList.map((m: any) => `${m.season}-${m.episode}`));
          const showWatched = watchedEps[s.imdb_id] ?? {};
          return (
            <div key={s.title} className="border border-border rounded">
              <button
                type="button"
                onClick={() => toggle(s.title)}
                className="w-full flex items-center justify-between px-4 py-3 text-sm hover:bg-card transition text-left"
              >
                <span className="font-medium">{s.title}</span>
                <span className="text-muted text-xs">
                  {s.seasons.length} season{s.seasons.length !== 1 ? 's' : ''} · {totalEps} episodes
                  {missingCount > 0 && (
                    <span className="text-danger ml-2">{missingCount} missing</span>
                  )}
                  <span className="ml-2">{isOpen ? '▲' : '▼'}</span>
                </span>
              </button>
              {isOpen && (
                <div className="border-t border-border px-4 py-3 space-y-2 bg-card/50">
                  {s.seasons.map((se: any) => {
                    const seasonMissing = missingList
                      .filter((m: any) => m.season === se.season)
                      .map((m: any) => m.episode);
                    const allEps = new Set([...se.episodes, ...seasonMissing]);
                    const sorted = Array.from(allEps).sort((a, b) => a - b);
                    const watchedInSeason = new Set<number>(showWatched[String(se.season)] ?? []);
                    return (
                      <div key={se.season}>
                        <div className="text-xs text-muted mb-1">
                          Season {String(se.season).padStart(2, '0')}{se.year ? ` (${se.year})` : ''} - {se.episodes.length} episode{se.episodes.length !== 1 ? 's' : ''}
                          {seasonMissing.length > 0 && (
                            <span className="text-danger ml-1">({seasonMissing.length} missing)</span>
                          )}
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {sorted.map((ep: number) => {
                            const isWanted  = missingSet.has(`${se.season}-${ep}`);
                            const isWatched = watchedInSeason.has(ep);
                            const playable  = !isWanted && canPlay && s.imdb_id;
                            const label = `E${String(ep).padStart(2, '0')}`;

                            if (isWanted) {
                              return (
                                <span key={ep}
                                  className="text-xs px-2 py-0.5 rounded bg-danger/20 text-danger"
                                  title="Wanted - not yet cached"
                                >
                                  {label}
                                </span>
                              );
                            }
                            if (playable) {
                              return (
                                <button
                                  key={ep}
                                  type="button"
                                  onClick={() => setPlayEp({
                                    imdb_id: s.imdb_id,
                                    season: se.season,
                                    episode: ep,
                                    title: `${s.title} S${String(se.season).padStart(2,'0')}E${String(ep).padStart(2,'0')}`,
                                  })}
                                  className={`text-xs px-2 py-0.5 rounded transition-colors
                                    ${isWatched
                                      ? 'bg-ok/20 text-ok hover:bg-ok hover:text-white'
                                      : 'bg-accent/20 text-accent hover:bg-accent-light hover:text-white'
                                    }`}
                                  title={isWatched ? 'Watched - play again' : 'Play in browser'}
                                >
                                  ▶ {label}
                                </button>
                              );
                            }
                            // available but no webplayer
                            return (
                              <span key={ep}
                                className={`text-xs px-2 py-0.5 rounded
                                  ${isWatched ? 'bg-ok/20 text-ok' : 'bg-accent/20 text-accent'}`}
                                title={isWatched ? 'Watched' : 'Available'}
                              >
                                {label}
                              </span>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
      )}
    </div>

    {playEp && PlayerModal && (
      <PlayerModal
        imdb_id={playEp.imdb_id}
        media_type="tv"
        title={playEp.title}
        season={playEp.season}
        episode={playEp.episode}
        onClose={() => setPlayEp(null)}
      />
    )}
    </>
  );
}
