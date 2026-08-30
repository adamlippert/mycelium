import { tmdbImg } from '../../api';
import type { TmdbDetail } from '../../types';

export function Seasons({ seasons }: { seasons: NonNullable<TmdbDetail['seasons']> }) {
  return (
    <div className="mt-7">
      <h3 className="text-[10px] uppercase tracking-wider text-muted font-semibold mb-3">
        Seasons
      </h3>
      <div className="flex gap-3 overflow-x-auto scrollbar-hidden">
        {seasons.map((s) => (
          <div key={s.season_number} className="flex-shrink-0 w-24 text-center">
            <div className="aspect-[2/3] rounded-md bg-bg overflow-hidden">
              {s.poster_path && (
                <img
                  src={tmdbImg.logo(s.poster_path) || undefined}
                  className="w-full h-full object-cover"
                  alt={s.name}
                />
              )}
            </div>
            <div className="text-xs mt-1 font-semibold">S{s.season_number}</div>
            <div className="text-[10px] text-muted">{s.episode_count} eps</div>
          </div>
        ))}
      </div>
    </div>
  );
}
