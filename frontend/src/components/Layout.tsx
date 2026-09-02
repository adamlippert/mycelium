import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './shell/Sidebar';
import { Topbar } from './shell/Topbar';
import { VersionLine } from './VersionLine';

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
        <footer className="border-t border-border px-4 py-3 lg:px-8">
          <VersionLine />
        </footer>
      </div>
    </div>
  );
}
