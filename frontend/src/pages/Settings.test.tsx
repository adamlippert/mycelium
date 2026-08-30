import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import Settings from './Settings';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin' } }),
      settings: () => Promise.resolve({ groups: [] }),
    },
  };
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Settings /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Settings structure', () => {
  it('splits into Integrations and Preferences sections', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Integrations')).toBeInTheDocument());
    expect(screen.getByText('Preferences')).toBeInTheDocument();
  });

  it('describes each section', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Watchlist sources and playback targets')).toBeInTheDocument());
    expect(screen.getByText('Applies to your account only')).toBeInTheDocument();
  });
});
