import { tmdbImg } from '../api';
import type { TmdbItem } from '../types';
import { useWatched } from '../hooks/useWatched';

export default function PosterCard({
  item,
  onClick,
  status,
}: {
  item: TmdbItem;
  onClick: (item: TmdbItem) => void;
  status?: string | null;
}) {
  const watched = useWatched();
  const isWatched = !!(item.imdb_id && watched.has(item.imdb_id));
  const poster = tmdbImg.poster(item.poster_path);
  const isTV = item.media_type === 'tv';
  return (
    <button
      type="button"
      onClick={() => onClick(item)}
      className="group relative w-full aspect-[2/3] rounded-lg overflow-hidden bg-card border border-border
                  hover:border-accent/50 transition-all hover:-translate-y-1 hover:shadow-xl
                  hover:shadow-black/40 text-left"
    >
      {poster ? (
        <img
          loading="lazy"
          src={poster}
          alt={item.title}
          className="absolute inset-0 w-full h-full object-cover"
        />
      ) : (
        <div
          className="absolute inset-0 flex items-center justify-center font-mono font-bold text-[80px]"
          style={{
            background: `linear-gradient(135deg, hsl(${(item.title.charCodeAt(0) * 7) % 360}, 40%, 25%), hsl(${(item.title.charCodeAt(0) * 7 + 40) % 360}, 50%, 15%))`,
            color: 'rgba(255,255,255,0.14)',
          }}
        >
          {item.title[0]}
        </div>
      )}
      <div
        className={`absolute top-2 right-2 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
          isTV ? 'bg-accent/90' : 'bg-black/70'
        } text-white`}
      >
        {isTV ? 'TV' : 'Movie'}
      </div>
      {isWatched && (
        <div className="absolute top-8 right-2 w-5 h-5 rounded-full bg-green-500/90 flex items-center justify-center shadow-md z-10"
             title="Watched">
          <span className="text-white text-[10px] font-bold leading-none">✓</span>
        </div>
      )}
      {status && <StatusBadge status={status} />}
      <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/95 via-black/60 to-transparent p-2.5 pt-6">
        <div className="font-semibold text-xs leading-tight line-clamp-2 mb-1">
          {item.title}
        </div>
        <div className="flex items-center gap-2 text-[10px] text-white/70">
          {item.year && <span>{item.year}</span>}
          {item.rating > 0 && (
            <span className="bg-warn/90 text-black font-semibold px-1.5 py-0.5 rounded">
              &#9733; {item.rating}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

const STATUS_STYLES: Record<string, { bg: string; label: string }> = {
  success:   { bg: 'bg-green-600',  label: 'In library' },
  available: { bg: 'bg-green-600',  label: 'In library' },
  wanted:    { bg: 'bg-yellow-600', label: 'Wanted' },
  upcoming:  { bg: 'bg-blue-600',   label: 'Upcoming' },
  pending:   { bg: 'bg-yellow-600', label: 'Pending' },
  failed:    { bg: 'bg-red-600',    label: 'Failed' },
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLES[status];
  if (!s) return null;
  return (
    <div className={`absolute top-2 left-2 px-1.5 py-0.5 rounded text-[10px] font-semibold ${s.bg} text-white`}>
      {s.label}
    </div>
  );
}
