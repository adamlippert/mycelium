import { tmdbImg } from '../../api';
import type { TmdbDetail } from '../../types';

export function Cast({
  cast,
  onSelectPerson,
}: {
  cast: NonNullable<TmdbDetail['cast']>;
  onSelectPerson: (id: number) => void;
}) {
  return (
    <div className="mt-7">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted mb-2">
        Cast
      </h3>
      <div className="flex gap-3 overflow-x-auto scrollbar-hidden">
        {cast.map((c, i) => (
          <button
            key={i}
            type="button"
            onClick={() => c.id && onSelectPerson(c.id)}
            disabled={!c.id}
            className="flex-shrink-0 w-20 text-center group"
          >
            <div className="w-20 h-20 rounded-full bg-bg overflow-hidden group-hover:ring-2 group-hover:ring-accent/60 transition">
              {c.profile_path && (
                <img
                  src={tmdbImg.profile(c.profile_path) || undefined}
                  alt={c.name}
                  className="w-full h-full object-cover"
                />
              )}
            </div>
            <div className="text-[11px] mt-1 font-semibold leading-tight line-clamp-2 group-hover:text-accent transition">
              {c.name}
            </div>
            <div className="text-[10px] text-muted line-clamp-2">{c.character}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
