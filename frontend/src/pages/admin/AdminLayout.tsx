import type { ComponentType } from 'react';
import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { useToast } from '../../components/primitives';
import Overview from './Overview';
import Users from './Users';
import Requests from './Requests';
import Maintenance from './Maintenance';
import Blacklist from './Blacklist';
import Scrapers from './Scrapers';
import Logs from './Logs';
import Releases from './Releases';
import FilterRules from './FilterRules';
import Settings from './Settings';

export const ADMIN_TABS: { id: string; label: string; component: ComponentType }[] = [
  { id: 'overview', label: 'Overview', component: Overview },
  { id: 'users', label: 'Users', component: Users },
  { id: 'requests', label: 'Requests', component: Requests },
  { id: 'filter-rules', label: 'Filter rules', component: FilterRules },
  { id: 'scrapers', label: 'Scrapers', component: Scrapers },
  { id: 'logs', label: 'Logs', component: Logs },
  { id: 'releases', label: 'Releases', component: Releases },
  { id: 'maintenance', label: 'Maintenance', component: Maintenance },
  { id: 'blacklist', label: 'Blacklist', component: Blacklist },
  { id: 'settings', label: 'Settings', component: Settings },
];

// Refresh policy: mirrors the old Jinja dashboard's pollActivity() (see
// templates/ui.html, ~line 1474) - a 5s tail that turns new activity_log
// rows into corner toasts. The sub-10s cadence is justified here because
// this is the operator's live event stream (deletes, purges, sync results),
// not a dashboard metric, and it only runs while AdminLayout is mounted:
// navigating away from /admin unmounts this hook and the poll with it.
const ACTIVITY_POLL_MS = 5000;

/** Ports LAST_ACTIVITY_ID from the Jinja poller: /ui/api/activity returns
 * newest-first, so events[0].id is the high-water mark. The first poll only
 * primes that cursor - nothing "just happened" before this component
 * existed - then every later poll toasts whatever is newer than the cursor. */
function useActivityToasts() {
  const toast = useToast();
  const lastId = useRef<number | null>(null);
  const { data } = useQuery({
    queryKey: ['admin-activity-toasts'],
    queryFn: api.activity,
    refetchInterval: ACTIVITY_POLL_MS,
  });

  useEffect(() => {
    const events = data?.events;
    if (!events || events.length === 0) return;
    if (lastId.current === null) {
      lastId.current = events[0].id;
      return;
    }
    const fresh = events.filter((e) => e.id > lastId.current!);
    fresh.slice().reverse().forEach((e) => {
      toast(e.title ? `${e.event}: ${e.title}` : e.event, e.message || undefined, e.success ? 'ok' : 'err');
    });
    if (fresh.length) lastId.current = events[0].id;
  }, [data, toast]);
}

export default function AdminLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  useActivityToasts();

  const hashId = location.hash.replace(/^#/, '');
  const activeTab = ADMIN_TABS.find((t) => t.id === hashId) ?? ADMIN_TABS[0];
  const ActiveComponent = activeTab.component;

  return (
    <div>
      <div className="flex gap-0.5 border-b border-border">
        {ADMIN_TABS.map((t) => {
          const active = t.id === activeTab.id;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => navigate({ hash: t.id }, { replace: true })}
              className={`px-3.5 py-3.5 text-xs font-medium transition ${
                active ? 'text-white shadow-[inset_0_-2px_0_#9f92ff]' : 'text-muted hover:text-white'
              }`}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      <div className="pt-6">
        <ActiveComponent />
      </div>
    </div>
  );
}
