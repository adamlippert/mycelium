import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { loginFlags } from '../api';
import { Sidebar } from './shell/Sidebar';
import { Topbar } from './shell/Topbar';

/** Which build is this? Read from the app-version meta tag _spa_index()
 * embeds, the same source the login page uses, so it needs no request and
 * is correct before any API call resolves. */
function Footer() {
  const version = loginFlags().appVersion;
  return (
    <footer className="border-t border-border px-4 py-3 lg:px-8">
      <div className="flex items-center gap-2 font-mono text-[10px] text-muted">
        <span className="h-1.5 w-1.5 rounded-full bg-ok" />
        <span data-testid="app-version">
          mycelium{version ? ` v${version}` : ''} &middot; self-hosted
        </span>
      </div>
    </footer>
  );
}

export default function Layout() {
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-bg text-body">
      <Sidebar open={drawerOpen} onNavigate={() => setDrawerOpen(false)} />

      {drawerOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setDrawerOpen(false)}
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenMenu={() => setDrawerOpen(true)} />
        <main className="flex-1 px-4 py-6 lg:px-8">
          <Outlet />
        </main>
        <Footer />
      </div>
    </div>
  );
}
