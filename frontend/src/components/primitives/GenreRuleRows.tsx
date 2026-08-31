import { Toggle } from './Toggle';
import type { GenreRule } from '../../api';

/** Shared editor rows for a list of genre rules - used by both the admin
 * Requests tab (auto-approve genre rules) and the admin Settings tab
 * (Discover genre tabs). The two call sites differ only in which mutation
 * callbacks they pass; this component owns the row markup and the enabled
 * toggle (now the shared `Toggle` primitive, previously a hand-rolled
 * button duplicated in both files). */
export function GenreRuleRows({
  rules,
  movieGenres,
  tvGenres,
  onUpdate,
  onRemove,
}: {
  rules: GenreRule[];
  movieGenres: Array<{ id: number; name: string }>;
  tvGenres: Array<{ id: number; name: string }>;
  onUpdate: (i: number, patch: Partial<GenreRule>) => void;
  onRemove: (i: number) => void;
}) {
  return (
    <div className="space-y-2">
      {rules.map((rule, i) => {
        const genres = rule.media_type === 'movie' ? movieGenres : tvGenres;
        return (
          <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg bg-bg p-2">
            <Toggle
              checked={rule.enabled}
              onChange={(next) => onUpdate(i, { enabled: next })}
              label={rule.genre_name ? `Enable ${rule.genre_name} rule` : 'Enable rule'}
            />
            <select
              value={rule.media_type}
              onChange={(e) => {
                const mt = e.target.value as 'movie' | 'tv';
                const g = (mt === 'movie' ? movieGenres : tvGenres)?.[0];
                onUpdate(i, { media_type: mt, genre_id: g?.id || 0, genre_name: g?.name || '' });
              }}
              className="rounded border border-border bg-card px-2 py-1 text-xs"
            >
              <option value="movie">Movies</option>
              <option value="tv">Shows</option>
            </select>
            <select
              value={rule.genre_id}
              onChange={(e) => {
                const g = genres.find((x) => x.id === Number(e.target.value));
                onUpdate(i, { genre_id: g?.id || 0, genre_name: g?.name || '' });
              }}
              className="rounded border border-border bg-card px-2 py-1 text-xs"
            >
              {genres.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
            <input
              type="number"
              placeholder="From year"
              value={rule.year_from ?? ''}
              onChange={(e) => onUpdate(i, { year_from: e.target.value ? Number(e.target.value) : null })}
              className="w-24 rounded border border-border bg-card px-2 py-1 text-xs"
            />
            <span className="text-xs text-muted">to</span>
            <input
              type="number"
              placeholder="To year"
              value={rule.year_to ?? ''}
              onChange={(e) => onUpdate(i, { year_to: e.target.value ? Number(e.target.value) : null })}
              className="w-24 rounded border border-border bg-card px-2 py-1 text-xs"
            />
            <button
              type="button"
              onClick={() => onRemove(i)}
              className="ml-auto rounded px-2 py-1 text-xs text-danger hover:bg-danger/10"
            >
              Remove
            </button>
          </div>
        );
      })}
    </div>
  );
}
