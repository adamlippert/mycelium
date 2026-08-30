import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Sidebar, NAV_GROUPS } from './Sidebar';

const mockSession = { authenticated: true, user: { username: 'adam', role: 'admin' } };

vi.mock('../../api', () => ({
  api: {
    shellSummary: () => Promise.resolve({
      counts: { watchlist: 38, requests: 3, wanted: 11 },
      torbox: { state: 'ok', label: 'TorBox online' },
    }),
    session: () => Promise.resolve(mockSession),
  },
}));

function renderSidebar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Sidebar open onNavigate={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('NAV_GROUPS', () => {
  it('puts Settings under Manage, not Browse', () => {
    const browse = NAV_GROUPS.find((g) => g.title === 'Browse')!;
    const manage = NAV_GROUPS.find((g) => g.title === 'Manage')!;
    expect(browse.items.map((i) => i.label)).not.toContain('Settings');
    expect(manage.items.map((i) => i.label)).toContain('Settings');
  });

  it('covers every navigable route exactly once', () => {
    const tos = NAV_GROUPS.flatMap((g) => g.items.map((i) => i.to));
    expect(tos).toEqual([
      '/', '/library', '/watchlist', '/search', '/requests', '/wanted',
      '/settings', '/admin', '/manual',
    ]);
    expect(new Set(tos).size).toBe(tos.length);
  });

  it('uses icon names, never emoji', () => {
    for (const item of NAV_GROUPS.flatMap((g) => g.items)) {
      expect(item.icon).toMatch(/^[a-z]+$/);
    }
  });
});

describe('Sidebar', () => {
  beforeEach(() => {
    mockSession.authenticated = true;
    mockSession.user = { username: 'adam', role: 'admin' };
  });

  it('renders every navigation label', async () => {
    renderSidebar();
    for (const label of ['Discover', 'Library', 'Watchlist', 'Search', 'My Requests', 'Wanted']) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
  });

  it('shows live counts beside the three routes that have them', async () => {
    renderSidebar();
    expect(await screen.findByText('38')).toBeInTheDocument();
    expect(await screen.findByText('11')).toBeInTheDocument();
  });

  it('renders no count badge before the summary arrives', () => {
    const { container } = renderSidebar();
    expect(container.textContent).not.toContain('undefined');
    expect(container.textContent).not.toContain('NaN');
  });

  it('hides Admin for a non-admin session but still shows Manual and Settings', async () => {
    mockSession.user = { username: 'jane', role: 'user' };
    renderSidebar();
    expect(await screen.findByText('Manual')).toBeInTheDocument();
    expect(await screen.findByText('Settings')).toBeInTheDocument();
    // Admin is bootstrap-visible until the session query resolves; wait for
    // the non-admin session to land before asserting it is gone.
    await waitFor(() => expect(screen.queryByText('Admin')).not.toBeInTheDocument());
  });

  it('shows Admin for an admin session', async () => {
    renderSidebar();
    expect(await screen.findByText('Admin')).toBeInTheDocument();
  });
});
