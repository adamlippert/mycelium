import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { Pill } from '../primitives';
import { RegionPicker } from './RegionPicker';

export const CRUMBS: Record<string, string> = {
  '/': 'Discover',
  '/library': 'Library',
  '/watchlist': 'Watchlist',
  '/search': 'Search',
  '/requests': 'My Requests',
  '/wanted': 'Wanted',
  '/settings': 'Settings',
  '/admin': 'Admin',
  '/manual': 'Manual',
};

const TORBOX_PILL = { ok: 'ready', degraded: 'queued', down: 'failed' } as const;

export function Topbar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);

  const { data: summary } = useQuery({
    queryKey: ['shell-summary'],
    queryFn: api.shellSummary,
    staleTime: 60_000,
  });
  const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session, staleTime: 60_000 });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const title = CRUMBS[location.pathname] || 'Mycelium';

  return (
    <header className="sticky top-0 z-20 border-b border-border bg-bg/80 backdrop-blur">
      <div className="flex items-center gap-3 px-4 py-3 lg:px-8">
        <button
          className="-ml-2 rounded p-2 text-body hover:bg-card lg:hidden"
          onClick={onOpenMenu}
          aria-label="Open menu"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </button>

        <div className="flex items-baseline gap-2">
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted">MYCELIUM</span>
          <span className="text-muted">/</span>
          <h1 className="text-base font-semibold text-body">{title}</h1>
        </div>

        <form
          className="ml-4 hidden max-w-sm flex-1 sm:block"
          onSubmit={(e) => {
            e.preventDefault();
            if (q.trim()) navigate(`/search?q=${encodeURIComponent(q.trim())}`);
          }}
        >
          <div className="relative">
            <input
              ref={searchRef}
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search titles"
              className="w-full rounded-lg border border-border bg-card py-1.5 pl-3 pr-12 text-sm
                         text-body placeholder:text-muted focus:border-accent focus:outline-none"
            />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 font-mono text-[10px] text-muted">
              ⌘K
            </span>
          </div>
        </form>

        <div className="ml-auto flex items-center gap-2">
          {summary && <Pill state={TORBOX_PILL[summary.torbox.state]}>{summary.torbox.label}</Pill>}
          {session?.user && <RegionPicker region={session.user.region || 'US'} />}
        </div>
      </div>
    </header>
  );
}
