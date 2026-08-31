import type { ComponentType } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

function Stub() {
  return <p className="text-muted text-sm">Coming in this plan.</p>;
}

export const ADMIN_TABS: { id: string; label: string; component: ComponentType }[] = [
  { id: 'overview', label: 'Overview', component: Stub },
  { id: 'users', label: 'Users', component: Stub },
  { id: 'requests', label: 'Requests', component: Stub },
  { id: 'filter-rules', label: 'Filter rules', component: Stub },
  { id: 'scrapers', label: 'Scrapers', component: Stub },
  { id: 'logs', label: 'Logs', component: Stub },
  { id: 'maintenance', label: 'Maintenance', component: Stub },
  { id: 'blacklist', label: 'Blacklist', component: Stub },
  { id: 'settings', label: 'Settings', component: Stub },
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
