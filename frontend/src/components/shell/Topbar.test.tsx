import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import { Topbar, CRUMBS } from './Topbar';
import { ToastProvider } from '../primitives';

const mockSession: { authenticated: boolean; user: Record<string, unknown> | null } = {
  authenticated: true,
  user: { username: 'adam', role: 'admin', region: 'NL' },
};

vi.mock('../../api', () => ({
  api: {
    shellSummary: () => Promise.resolve({
      counts: { watchlist: 0, requests: 0, wanted: 0 },
      torbox: { state: 'degraded', label: 'TorBox near its limit' },
    }),
    session: () => Promise.resolve(mockSession),
  },
}));

function renderTopbar(path = '/library') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Topbar onOpenMenu={() => {}} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe('CRUMBS', () => {
  it('names every navigable route', () => {
    for (const path of ['/', '/library', '/watchlist', '/search', '/requests', '/wanted', '/settings', '/admin', '/manual']) {
      expect(CRUMBS[path], `no crumb for ${path}`).toBeTruthy();
    }
  });
});

describe('Topbar', () => {
  it('shows the MYCELIUM breadcrumb and the current page', async () => {
    renderTopbar('/library');
    expect(screen.getByText('MYCELIUM')).toBeInTheDocument();
    expect(await screen.findAllByText('Library')).not.toHaveLength(0);
  });

  it('shows the TorBox state from the summary, not a hardcoded label', async () => {
    renderTopbar();
    expect(await screen.findByText('TorBox near its limit')).toBeInTheDocument();
  });

  it('advertises the keyboard shortcut on the search field', () => {
    renderTopbar();
    expect(screen.getByText('⌘K')).toBeInTheDocument();
  });

  it('falls back to US, not NL, when the session carries no region', async () => {
    mockSession.user = { username: 'adam', role: 'admin' };
    renderTopbar();
    expect(await screen.findByText('US')).toBeInTheDocument();
    expect(screen.queryByText('NL')).not.toBeInTheDocument();
    mockSession.user = { username: 'adam', role: 'admin', region: 'NL' };
  });
});
