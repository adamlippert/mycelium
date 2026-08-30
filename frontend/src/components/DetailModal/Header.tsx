import type { UseMutationResult } from '@tanstack/react-query';
import type { TmdbDetail } from '../../types';
import { LibraryButton, type AddStatus } from './index';
import { StreamingOn } from './Similar';

export function Header({
  detail,
  poster,
  isWatched,
  libStatus,
  addStatus,
  monitorMode,
  setMonitorMode,
  selectedSeasons,
  toggleSeason,
  addMutation,
  canPlay,
  setShowPlayer,
  watchlistMutation,
  inWatchlist,
  trailer,
  setShowTrailer,
}: {
  detail: TmdbDetail;
  poster: string | null;
  isWatched: boolean;
  libStatus: string | undefined;
  addStatus: AddStatus;
  monitorMode: 'all' | 'future' | 'selected';
  setMonitorMode: (mode: 'all' | 'future' | 'selected') => void;
  selectedSeasons: number[];
  toggleSeason: (n: number) => void;
  addMutation: UseMutationResult<any, unknown, void, unknown>;
  canPlay: boolean;
  setShowPlayer: (v: boolean) => void;
  watchlistMutation: UseMutationResult<any, unknown, void, unknown>;
  inWatchlist: boolean | undefined | '' | null;
  trailer: { key: string; name: string; site: string } | undefined;
  setShowTrailer: (v: boolean) => void;
}) {
  return (
    <div className="flex flex-col sm:flex-row gap-6">
      <div className="flex-shrink-0 w-40 sm:w-52 mx-auto sm:mx-0 aspect-[2/3] rounded-lg overflow-hidden bg-bg">
        {poster ? (
          <img src={poster} alt={detail.title} className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-muted text-xs p-3">
            No poster
          </div>
        )}
      </div>
      <div className="flex-1 min-w-0">
        <h2 className="text-2xl sm:text-3xl font-bold">
          {detail.title}{' '}
          {detail.year && (
            <span className="text-muted font-normal">({detail.year})</span>
          )}
        </h2>
        {detail.tagline && (
          <p className="text-muted italic mt-1">{detail.tagline}</p>
        )}
        <div className="flex flex-wrap gap-2 mt-3 text-xs">
          {isWatched && (
            <span className="px-2 py-0.5 rounded bg-ok/20 text-ok font-semibold">✓ Watched</span>
          )}
          {detail.rating > 0 && (
            <Badge>★ {detail.rating} ({detail.votes} votes)</Badge>
          )}
          {detail.runtime ? <Badge>{detail.runtime} min</Badge> : null}
          {detail.genres?.map((g) => (
            <Badge key={g}>{g}</Badge>
          ))}
          {detail.status && <Badge>{detail.status}</Badge>}
          {detail.media_type === 'tv' && detail.number_of_seasons && (
            <Badge>
              {detail.number_of_seasons} seasons / {detail.number_of_episodes} eps
            </Badge>
          )}
        </div>
        <p className="text-sm leading-relaxed mt-4 max-w-3xl">
          {detail.overview || 'No overview available.'}
        </p>

        {detail.media_type === 'tv' && (
          <div className="mt-4 bg-bg/60 border border-border rounded-lg p-3">
            <div className="text-[10px] uppercase tracking-wider text-muted font-semibold mb-2">
              What to monitor
            </div>
            <div className="flex gap-2 mb-2">
              {([
                ['all', 'All seasons'],
                ['future', 'Future episodes only'],
                ['selected', 'Pick seasons'],
              ] as const).map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setMonitorMode(mode)}
                  className={`text-xs px-3 py-1.5 rounded border ${
                    monitorMode === mode
                      ? 'border-accent bg-accent/10 text-white'
                      : 'border-border text-muted hover:text-white'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {monitorMode === 'selected' && detail.seasons && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {detail.seasons
                  .filter((s) => s.season_number >= 1)
                  .map((s) => (
                    <button
                      key={s.season_number}
                      type="button"
                      onClick={() => toggleSeason(s.season_number)}
                      className={`text-xs px-2 py-1 rounded border ${
                        selectedSeasons.includes(s.season_number)
                          ? 'border-accent bg-accent text-white'
                          : 'border-border text-muted hover:text-white'
                      }`}
                      title={`${s.episode_count} eps`}
                    >
                      S{s.season_number}
                    </button>
                  ))}
              </div>
            )}
            {monitorMode === 'future' && (
              <p className="text-[11px] text-muted mt-1">
                Only episodes airing from now on  -  the back-catalog is skipped.
              </p>
            )}
          </div>
        )}

        <div className="flex flex-wrap gap-2 mt-5">
          <LibraryButton
            libStatus={libStatus}
            addStatus={addStatus}
            mediaType={detail.media_type}
            disabled={
              detail.media_type === 'tv' &&
              monitorMode === 'selected' &&
              selectedSeasons.length === 0
            }
            onAdd={() => addMutation.mutate()}
          />
          {canPlay && (libStatus === 'available' || libStatus === 'success') && (
            <button
              type="button"
              onClick={() => setShowPlayer(true)}
              className="bg-accent hover:bg-accent-light text-white rounded-lg px-4 py-2 text-sm font-medium"
            >
              ▶ Play
            </button>
          )}
          <button
            type="button"
            onClick={() => watchlistMutation.mutate()}
            disabled={!detail.imdb_id || watchlistMutation.isPending}
            className="bg-transparent border border-border text-body hover:border-accent-light/50
                       rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            {inWatchlist ? '★ In watchlist' : '☆ Watchlist'}
          </button>
          {trailer && (
            <button
              type="button"
              onClick={() => setShowTrailer(true)}
              className="bg-transparent border border-border text-body hover:border-accent-light/50
                         rounded-lg px-4 py-2 text-sm font-medium"
            >
              ▶ Trailer
            </button>
          )}
          {detail.imdb_id && (
            <a
              href={`https://www.imdb.com/title/${detail.imdb_id}/`}
              target="_blank"
              rel="noopener"
              className="bg-transparent border border-border text-body hover:border-accent-light/50
                         rounded-lg px-4 py-2 text-sm font-medium"
            >
              IMDB
            </a>
          )}
        </div>

        <StreamingOn providers={detail.providers} />
      </div>
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return <span className="bg-card-raised border border-border text-body px-2 py-0.5 rounded text-xs">{children}</span>;
}
