import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import type { IconName } from '../../design/icons';
import { NavItem } from './NavItem';

export type NavEntry = {
  to: string;
  label: string;
  icon: IconName;
  exact?: boolean;
  countKey?: 'watchlist' | 'requests' | 'wanted';
};

export const NAV_GROUPS: { title: string; items: NavEntry[] }[] = [
  {
    title: 'Browse',
    items: [
      { to: '/', label: 'Discover', icon: 'discover', exact: true },
      { to: '/library', label: 'Library', icon: 'library' },
      { to: '/watchlist', label: 'Watchlist', icon: 'watchlist', countKey: 'watchlist' },
      { to: '/search', label: 'Search', icon: 'search' },
      { to: '/requests', label: 'My Requests', icon: 'requests', countKey: 'requests' },
      { to: '/wanted', label: 'Wanted', icon: 'wanted', countKey: 'wanted' },
    ],
  },
  {
    title: 'Manage',
    items: [
      { to: '/settings', label: 'Settings', icon: 'settings' },
      { to: '/admin', label: 'Admin', icon: 'admin' },
      { to: '/manual', label: 'Manual', icon: 'manual' },
    ],
  },
];

export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  const { data: summary } = useQuery({
    queryKey: ['shell-summary'],
    queryFn: api.shellSummary,
    staleTime: 60_000,
  });
  const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session, staleTime: 60_000 });

  const user = session?.user;
  const initials = (user?.username || '?').slice(0, 2).toUpperCase();

  const isAdmin = user?.role === 'admin';
  const showAdmin = isAdmin || !session?.authenticated; // bootstrap visible

  return (
    <aside
      className={`fixed left-0 top-0 z-40 flex h-screen w-[248px] flex-none flex-col border-r
                  border-border bg-sidebar transition-transform duration-200 lg:sticky
                  ${open ? 'translate-x-0' : '-translate-x-full'} lg:translate-x-0`}
    >
      <div className="flex items-center gap-2.5 border-b border-border px-4 py-5">
        <span className="font-mono text-lg font-bold tracking-wide text-white">
          myc<span className="text-accent-pale">3</span>l<span className="text-accent-pale">1</span>um
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto py-3">
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="mb-2">
            <div className="px-4 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-muted">
              {group.title}
            </div>
            {group.items
              .filter((item) => item.to !== '/admin' || showAdmin)
              .map((item) => (
                <NavItem
                  key={item.to}
                  to={item.to}
                  label={item.label}
                  icon={item.icon}
                  exact={item.exact}
                  count={item.countKey ? summary?.counts[item.countKey] : undefined}
                  onNavigate={onNavigate}
                />
              ))}
          </div>
        ))}
      </nav>

      <div className="border-t border-border p-3">
        {user ? (
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 flex-none items-center justify-center rounded-lg border border-border
                             font-mono text-[11px] text-accent-pale"
                  style={{ background: 'rgba(97,82,223,0.2)' }}>
              {initials}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-xs text-body">{user.username}</span>
              <span className="block text-[10px] text-muted">
                {user.role === 'admin' ? 'Administrator' : 'User'}
              </span>
            </span>
            <a href="/logout" className="ml-auto text-[11px] text-muted hover:text-body">Log out</a>
          </div>
        ) : (
          <a href="/login" className="text-xs text-muted hover:text-body">Sign in</a>
        )}
      </div>
    </aside>
  );
}
