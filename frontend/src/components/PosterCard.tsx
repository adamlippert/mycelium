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
      className="group relative w-full aspect-[2/3] rounded-xl overflow-hidden bg-card border border-border
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
        <div
          className="absolute top-8 right-2 w-5 h-5 rounded-full flex items-center justify-center shadow-md z-10"
          style={{ background: 'rgba(37,140,96,0.9)' }}
          title="Watched"
        >
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
            <span
              className="font-semibold px-1.5 py-0.5 rounded"
              style={{ background: 'rgba(198,178,83,0.9)', color: '#070707' }}
            >
              &#9733; {item.rating}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

const BADGES: Record<string, { bg: string; label: string }> = {
  success:   { bg: 'rgba(37,140,96,0.85)',  label: 'IN LIBRARY' },
  available: { bg: 'rgba(37,140,96,0.85)',  label: 'IN LIBRARY' },
  pending:   { bg: 'rgba(97,82,223,0.88)',  label: 'REQUESTED' },
  wanted:    { bg: 'rgba(198,178,83,0.85)', label: 'WANTED' },
  upcoming:  { bg: 'rgba(97,82,223,0.55)',  label: 'UPCOMING' },
  failed:    { bg: 'rgba(209,71,71,0.85)',  label: 'FAILED' },
};

function StatusBadge({ status }: { status: string }) {
  const s = BADGES[status];
  if (!s) return null;
  return (
    <div
      data-badge
      className="absolute top-2 left-2 rounded-md px-1.5 py-1 text-[9px] font-semibold tracking-wide
                 text-white backdrop-blur-sm"
      style={{ background: s.bg }}
    >
      {s.label}
    </div>
  );
}
