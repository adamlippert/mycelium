import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import Library from './Library';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      stats: () => Promise.resolve({
        library: { movie_count: 12, episode_count: 300, series_count: 4 },
        requests: { total: 20, succeeded_7d: 9, failed_7d: 1, success_rate_7d: 90.0 },
        wanted: { active: 2, found: 1, give_up: 0 },
        movies_pending: 0, qualities: {},
      }),
      libraryMovies: () => Promise.resolve({ items: [] }),
      session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin' } }),
    },
  };
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Library /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Library stat tiles', () => {
  it('shows Titles as movies plus series, Episodes, and Success rate', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('16')).toBeInTheDocument());
    expect(screen.getByText('300')).toBeInTheDocument();
    expect(screen.getByText('90%')).toBeInTheDocument();
  });

  it('renders no invented delta lines', async () => {
    const { container } = renderPage();
    await waitFor(() => expect(screen.getByText('16')).toBeInTheDocument());
    expect(container.textContent).not.toMatch(/this week/);
  });
});
