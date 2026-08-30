import { tmdbImg } from '../../api';
import type { TmdbDetail, TmdbItem } from '../../types';

export function Similar({
  recommendations,
  onSelectItem,
}: {
  recommendations: NonNullable<TmdbDetail['recommendations']>;
  onSelectItem: (item: TmdbItem) => void;
}) {
  return (
    <div className="mt-7">
      <h3 className="text-[10px] uppercase tracking-wider text-muted font-semibold mb-3">
        You might also like
      </h3>
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-3">
        {recommendations.slice(0, 12).map((r) => (
          <button
            key={`${r.media_type}-${r.tmdb_id}`}
            type="button"
            onClick={() => onSelectItem(r)}
            className="aspect-[2/3] rounded-md overflow-hidden bg-bg border border-border
                        hover:border-accent/50 transition"
          >
            {r.poster_path ? (
              <img
                src={tmdbImg.poster(r.poster_path) || undefined}
                alt={r.title}
                className="w-full h-full object-cover"
              />
            ) : (
              <div className="text-xs text-muted p-2 text-center">{r.title}</div>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

export function StreamingOn({ providers }: { providers: TmdbDetail['providers'] }) {
  if (!providers?.flatrate || providers.flatrate.length === 0) return null;
  return (
    <div className="mt-5">
      <div className="text-[10px] uppercase tracking-wider text-muted font-semibold mb-2">
        Streaming on
      </div>
      <div className="flex flex-wrap gap-2">
        {providers.flatrate.map((p) => (
          <img
            key={p.id}
            src={tmdbImg.logo(p.logo_path) || undefined}
            alt={p.name}
            title={p.name}
            className="w-10 h-10 rounded-md"
          />
        ))}
      </div>
    </div>
  );
}
