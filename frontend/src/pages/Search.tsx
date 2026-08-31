import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, tmdbImg } from '../api';
import type { MediaType, TmdbItem } from '../types';
import { Chip } from '../components/primitives/Chip';
import { Pill } from '../components/primitives/Pill';
import { statusLabel } from '../components/primitives/statusLabels';
import DetailModal from '../components/DetailModal';

type Facet = 'all' | 'movie' | 'tv' | 'inlib';

export default function Search() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState(searchParams.get('q') || '');
  const [facet, setFacet] = useState<Facet>('all');

  // Pick up ?q= changes from the topbar search bar (or a shared link) after mount.
  useEffect(() => {
    const urlQ = searchParams.get('q') || '';
    if (urlQ !== q) setQ(urlQ);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const updateQuery = (value: string) => {
    setQ(value);
    setSearchParams(value ? { q: value } : {}, { replace: true });
  };
  const [detail, setDetail] = useState<{ id: number; type: MediaType } | null>(null);

  // Debounce the value that actually triggers a search request so fast typing
  // doesn't fire one TMDB call per keystroke - the input itself stays instant.
  const [debouncedQ, setDebouncedQ] = useState(q);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQ(q), 300);
    return () => clearTimeout(timer);
  }, [q]);

  const [elapsed, setElapsed] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ['search', debouncedQ],
    queryFn: async () => {
      const t0 = performance.now();
      const r = await api.search(debouncedQ);
      setElapsed((performance.now() - t0) / 1000);
      return r.results;
    },
    enabled: debouncedQ.trim().length > 0,
  });

  const counts = {
    movie: (data || []).filter((i) => i.media_type === 'movie').length,
    tv: (data || []).filter((i) => i.media_type === 'tv').length,
    inlib: (data || []).filter((i) => i.library_status === 'success' || i.library_status === 'available').length,
  };

  const filtered = (data || []).filter((i) =>
    facet === 'all' ? true
    : facet === 'inlib' ? (i.library_status === 'success' || i.library_status === 'available')
    : i.media_type === facet,
  );

  const open = (it: TmdbItem) => setDetail({ id: it.tmdb_id, type: it.media_type });

  return (
    <div className="space-y-4">
      <input
        type="text"
        autoFocus
        value={q}
        onChange={(e) => updateQuery(e.target.value)}
        placeholder="Search movies and series..."
        className="w-full max-w-xl bg-bg border border-border rounded-lg px-4 py-3 text-sm
                   focus:outline-none focus:border-accent text-white placeholder-muted"
      />
      {q.trim() && (
        <div className="flex flex-wrap gap-2">
          <Chip label={`All · ${(data || []).length}`} selected={facet === 'all'} onClick={() => setFacet('all')} />
          <Chip label={`Movies · ${counts.movie}`} selected={facet === 'movie'} onClick={() => setFacet('movie')} />
          <Chip label={`Series · ${counts.tv}`} selected={facet === 'tv'} onClick={() => setFacet('tv')} />
          <Chip label={`In library · ${counts.inlib}`} selected={facet === 'inlib'} onClick={() => setFacet('inlib')} />
        </div>
      )}
      {q.trim() && (
        <p className="font-mono text-xs text-muted">
          {filtered.length} results{elapsed != null && ` · ${elapsed.toFixed(2)}s`}
        </p>
      )}
      {q.trim() ? (
        isLoading ? (
          <div className="text-muted text-sm py-6">Loading...</div>
        ) : filtered.length > 0 ? (
          <div className="space-y-2">
            {filtered.map((it) => (
              <button
                key={`${it.media_type}-${it.tmdb_id}`}
                type="button"
                onClick={() => open(it)}
                className="flex w-full items-start gap-3 rounded-xl border border-border bg-card p-3 text-left
                           hover:border-accent-light/50 transition-colors"
              >
                <span className="h-20 w-14 flex-none overflow-hidden rounded-md bg-bg">
                  {tmdbImg.poster(it.poster_path) && (
                    <img loading="lazy" src={tmdbImg.poster(it.poster_path)!} alt="" className="h-full w-full object-cover" />
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-body">{it.title}</span>
                    {it.year && <span className="text-xs text-muted">{it.year}</span>}
                    <span className="text-[10px] uppercase tracking-wide text-muted">{it.media_type === 'tv' ? 'Series' : 'Movie'}</span>
                    {(it.library_status === 'success' || it.library_status === 'available') && <Pill state="ready">In library</Pill>}
                    {it.library_status === 'pending' && <Pill state="queued">Requested</Pill>}
                    {it.library_status === 'failed' && <Pill state="failed">{statusLabel('failed')}</Pill>}
                    {it.library_status === 'wanted' && <Pill state="queued">{statusLabel('wanted')}</Pill>}
                    {it.library_status === 'upcoming' && <Pill state="lazy">{statusLabel('upcoming')}</Pill>}
                  </span>
                  {it.overview && <span className="mt-1 block text-xs leading-relaxed text-muted line-clamp-2">{it.overview}</span>}
                  {it.rating > 0 && (
                    <span className="mt-1 inline-block font-mono text-[11px] text-warn">★ {it.rating}</span>
                  )}
                </span>
              </button>
            ))}
          </div>
        ) : (
          <div className="text-muted text-sm py-6">No results</div>
        )
      ) : (
        <div className="text-muted text-sm py-8 text-center">
          Start typing to search across movies and series.
        </div>
      )}
      <DetailModal
        tmdbId={detail?.id ?? null}
        mediaType={detail?.type ?? null}
        onClose={() => setDetail(null)}
        onSelectItem={open}
      />
    </div>
  );
}
