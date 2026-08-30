import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import type { WantedMovie, WantedEpisode } from '../types';
import { Pill } from '../components/primitives';
import type { PillState } from '../components/primitives';

export default function Wanted() {
  const queryClient = useQueryClient();

  const { data: moviesData, isLoading: moviesLoading } = useQuery({
    queryKey: ['wanted-movies'],
    queryFn: api.wantedMovies,
    refetchInterval: 30_000,
  });

  const { data: episodesData, isLoading: epsLoading } = useQuery({
    queryKey: ['wanted-episodes'],
    queryFn: api.wantedEpisodes,
    refetchInterval: 30_000,
  });

  const recheckMutation = useMutation({
    mutationFn: api.wantedRecheck,
    onSuccess: () => {
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['wanted-movies'] });
        queryClient.invalidateQueries({ queryKey: ['wanted-episodes'] });
      }, 3000);
    },
  });

  const movies = moviesData?.items ?? [];
  const episodes = episodesData?.items ?? [];

  const wantedEps = episodes.filter((e) => e.status === 'wanted');
  const notAiredEps = episodes.filter((e) => e.status === 'not_aired');
  const foundEps = episodes.filter((e) => e.status === 'found');

  return (
    <div className="space-y-6">
      <div className="mb-5 flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3">
        <span className="text-sm text-body">{movies.length + episodes.length} items unresolved</span>
        <button
          type="button"
          onClick={() => recheckMutation.mutate()}
          disabled={recheckMutation.isPending}
          className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-light disabled:opacity-50"
        >
          {recheckMutation.isPending ? 'Retrying...' : 'Retry all now'}
        </button>
      </div>

      <section>
        <div className="mb-2 flex items-center gap-2">
          <h2 className="text-sm font-semibold text-body">Movies</h2>
          <span
            className="rounded px-1.5 py-0.5 font-mono text-[10px] text-muted"
            style={{ background: 'var(--surface-subtle)' }}
          >
            {movies.length}
          </span>
        </div>
        {moviesLoading ? (
          <Spinner />
        ) : movies.length === 0 ? (
          <Empty>No movies on the wanted list.</Empty>
        ) : (
          <div className="rounded-xl border border-border overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-card text-muted text-xs uppercase tracking-wider">
                  <Th>Title</Th>
                  <Th>Reason</Th>
                  <Th>Attempts</Th>
                  <Th>Added</Th>
                  <Th>Last checked</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {movies.map((m) => (
                  <MovieRow key={m.imdb_id} movie={m} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-6">
        <div className="mb-2 flex items-center gap-2">
          <h2 className="text-sm font-semibold text-body">Episodes</h2>
          <span
            className="rounded px-1.5 py-0.5 font-mono text-[10px] text-muted"
            style={{ background: 'var(--surface-subtle)' }}
          >
            {episodes.length}
          </span>
        </div>
        {epsLoading ? (
          <Spinner />
        ) : (
          <div className="space-y-6">
            <EpisodesTable
              title="Searching"
              rows={wantedEps}
              pillState="queued"
              emptyMsg="No episodes being searched."
            />
            <EpisodesTable
              title="Not yet aired"
              rows={notAiredEps}
              pillState="lazy"
              emptyMsg="No upcoming episodes tracked."
              dimmed
            />
            <EpisodesTable
              title="Found"
              rows={foundEps}
              pillState="ready"
              emptyMsg=""
              dimmed
              collapsed
            />
          </div>
        )}
      </section>
    </div>
  );
}

function attemptStyle(n: number): React.CSSProperties {
  if (n >= 10) return { background: 'rgba(209,71,71,0.14)', color: '#e48181' };
  if (n >= 5) return { background: 'rgba(198,178,83,0.13)', color: '#dacd8a' };
  return { background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.45)' };
}

function AttemptBadge({ n }: { n: number }) {
  return (
    <span data-attempts={n} className="rounded-md px-1.5 py-1 font-mono text-[10px]" style={attemptStyle(n)}>
      {n}
    </span>
  );
}

function MovieRow({ movie }: { movie: WantedMovie }) {
  return (
    <tr className="hover:bg-card/50 transition">
      <td className="px-4 py-3 font-medium">
        <div>{movie.title}</div>
        <div className="text-[10px] text-muted font-mono">{movie.imdb_id}</div>
      </td>
      <td className="px-4 py-3 text-muted text-xs">{movie.reason || ' - '}</td>
      <td className="px-4 py-3 text-center">
        <AttemptBadge n={movie.attempts} />
      </td>
      <td className="px-4 py-3 text-xs text-muted">{fmtDate(movie.added_at)}</td>
      <td className="px-4 py-3 text-xs text-muted">{movie.last_checked ? fmtDate(movie.last_checked) : ' - '}</td>
    </tr>
  );
}

function EpisodesTable({
  title,
  rows,
  pillState,
  emptyMsg,
  dimmed = false,
  collapsed = false,
}: {
  title: string;
  rows: WantedEpisode[];
  pillState: PillState;
  emptyMsg: string;
  dimmed?: boolean;
  collapsed?: boolean;
}) {
  const [open, setOpen] = useState(!collapsed);

  if (rows.length === 0 && !emptyMsg) return null;

  return (
    <div className={dimmed ? 'opacity-60' : ''}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 mb-2 text-left w-full group"
      >
        <span className="text-xs uppercase tracking-wider text-muted font-semibold group-hover:text-white transition">
          {title}
        </span>
        {rows.length > 0 && <Pill state={pillState}>{rows.length}</Pill>}
        <span className="text-muted text-xs ml-auto">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <>
          {rows.length === 0 ? (
            <p className="text-sm text-muted">{emptyMsg}</p>
          ) : (
            <div className="rounded-xl border border-border overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-card text-muted text-xs uppercase tracking-wider">
                    <Th>Series</Th>
                    <Th>Episode</Th>
                    <Th>Air date</Th>
                    <Th>Attempts</Th>
                    <Th>Last tried</Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {rows.map((ep) => (
                    <tr key={ep.id} className="hover:bg-card/50 transition">
                      <td className="px-4 py-3 font-medium">
                        <div>{ep.title}</div>
                        <div className="text-[10px] text-muted font-mono">{ep.imdb_id}</div>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        S{String(ep.season).padStart(2, '0')}E{String(ep.episode).padStart(2, '0')}
                      </td>
                      <td className="px-4 py-3 text-xs text-muted">{ep.air_date || ' - '}</td>
                      <td className="px-4 py-3 text-center">
                        <AttemptBadge n={ep.attempt_count} />
                      </td>
                      <td className="px-4 py-3 text-xs text-muted">
                        {ep.last_attempted ? fmtDate(ep.last_attempted) : ' - '}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 text-left font-medium">{children}</th>;
}

function Spinner() {
  return <div className="text-muted text-sm py-8 text-center">Loading…</div>;
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-muted text-sm py-12 text-center bg-card/30 rounded-xl border border-border">
      {children}
    </div>
  );
}

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}
