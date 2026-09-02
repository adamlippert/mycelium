import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import Layout from './Layout';

vi.mock('../api', () => ({
  loginFlags: () => ({
    oidcEnabled: false, oidcProvider: '', passwordEnabled: true, appVersion: '9.9.9',
  }),
  api: {
    shellSummary: () => Promise.resolve({
      counts: { watchlist: 1, requests: 2, wanted: 3 },
      torbox: { state: 'ok', label: 'TorBox online' },
    }),
    session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin', region: 'NL' } }),
  },
}));

describe('Layout', () => {
  it('renders the shell around the routed page', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/library']}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="library" element={<p>page body</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Discover')).toBeInTheDocument();   // sidebar
    expect(screen.getByText('MYCELIUM')).toBeInTheDocument();          // topbar
    expect(screen.getByText('page body')).toBeInTheDocument();         // outlet
  });

  it('shows the running version in the footer', async () => {
    // "I can't tell what version I'm running" - the version was embedded in
    // the page all along (app-version meta) but only the login page showed
    // it, so it was invisible once you were signed in.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/library']}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="library" element={<p>page body</p>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId('app-version')).toHaveTextContent('mycelium v9.9.9');
  });
});
