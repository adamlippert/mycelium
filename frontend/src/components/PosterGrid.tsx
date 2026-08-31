import { useRef, useState, useEffect } from 'react';
import type { TmdbItem } from '../types';
import PosterCard from './PosterCard';

export default function PosterGrid({
  items,
  loading,
  onItemClick,
  empty,
}: {
  items: TmdbItem[] | undefined;
  loading?: boolean;
  onItemClick: (item: TmdbItem) => void;
  empty?: string;
}) {
  if (loading) {
    return <div className="text-muted text-sm py-6">Loading...</div>;
  }
  // Array.isArray, not a truthiness check: an object slipping through here
  // reaches .map below and blanks the whole page.
  if (!Array.isArray(items) || items.length === 0) {
    return <div className="text-muted text-sm py-6">{empty || 'Nothing to show.'}</div>;
  }
  return <ScrollStrip items={items} onItemClick={onItemClick} />;
}

function ScrollStrip({
  items,
  onItemClick,
}: {
  items: TmdbItem[];
  onItemClick: (item: TmdbItem) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [canLeft, setCanLeft] = useState(false);
  const [canRight, setCanRight] = useState(false);
  const check = () => {
    const el = ref.current;
    if (!el) return;
    setCanLeft(el.scrollLeft > 0);
    setCanRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
  };

  useEffect(() => {
    check();
    const el = ref.current;
    if (!el) return;
    el.addEventListener('scroll', check, { passive: true });
    window.addEventListener('resize', check);
    return () => {
      el.removeEventListener('scroll', check);
      window.removeEventListener('resize', check);
    };
  }, [items]);

  const scroll = (dir: -1 | 1) => {
    const el = ref.current;
    if (!el) return;
    el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: 'smooth' });
  };

  return (
    <div className="group/strip relative">
      {canLeft && (
        <button
          type="button"
          onClick={() => scroll(-1)}
          className="absolute left-0 top-0 bottom-2 z-10 w-10 bg-gradient-to-r from-bg/90 to-transparent
                     flex items-center justify-center text-white/70 hover:text-white
                     opacity-0 group-hover/strip:opacity-100 transition-opacity"
          aria-label="Scroll left"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M13 4l-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      )}
      <div
        ref={ref}
        className="flex gap-3 overflow-x-auto scrollbar-hidden pb-2 -mx-1 px-1"
      >
        {items.map((item) => (
          <div key={`${item.media_type}-${item.tmdb_id}`} className="flex-shrink-0 w-[200px]">
            <PosterCard item={item} onClick={onItemClick} status={item.library_status} />
          </div>
        ))}
      </div>
      {canRight && (
        <button
          type="button"
          onClick={() => scroll(1)}
          className="absolute right-0 top-0 bottom-2 z-10 w-10 bg-gradient-to-l from-bg/90 to-transparent
                     flex items-center justify-center text-white/70 hover:text-white
                     opacity-0 group-hover/strip:opacity-100 transition-opacity"
          aria-label="Scroll right"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M7 4l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      )}
    </div>
  );
}
