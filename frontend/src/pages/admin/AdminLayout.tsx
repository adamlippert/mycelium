import type { ComponentType } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Overview from './Overview';
import Users from './Users';
import Requests from './Requests';
import Maintenance from './Maintenance';
import Blacklist from './Blacklist';
import Scrapers from './Scrapers';
import Logs from './Logs';
import FilterRules from './FilterRules';
import Settings from './Settings';

export const ADMIN_TABS: { id: string; label: string; component: ComponentType }[] = [
  { id: 'overview', label: 'Overview', component: Overview },
  { id: 'users', label: 'Users', component: Users },
  { id: 'requests', label: 'Requests', component: Requests },
  { id: 'filter-rules', label: 'Filter rules', component: FilterRules },
  { id: 'scrapers', label: 'Scrapers', component: Scrapers },
  { id: 'logs', label: 'Logs', component: Logs },
  { id: 'maintenance', label: 'Maintenance', component: Maintenance },
  { id: 'blacklist', label: 'Blacklist', component: Blacklist },
  { id: 'settings', label: 'Settings', component: Settings },
];

export default function AdminLayout() {
  const location = useLocation();
  const navigate = useNavigate();

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
