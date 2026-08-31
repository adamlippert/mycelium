import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import Wanted from './Wanted';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      wantedMovies: () => Promise.resolve({ items: [
        { imdb_id: 'tt1', title: 'Movie A', reason: 'NO_RELEASE', attempts: 2, last_checked: '2026-08-30 10:00:00' },
        { imdb_id: 'tt2', title: 'Movie B', reason: 'NO_RELEASE', attempts: 11, last_checked: '2026-08-30 10:00:00' },
      ] }),
      wantedEpisodes: () => Promise.resolve({ items: [
        { imdb_id: 'tt3', title: 'Show C', season: 1, episode: 2, status: 'wanted', air_date: '2026-08-01' },
        { imdb_id: 'tt4', title: 'Show D', season: 2, episode: 5, status: 'give_up', air_date: '2026-07-01' },
      ] }),
    },
  };
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Wanted /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Wanted', () => {
  it('shows both sections at once with their counts', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Movie A')).toBeInTheDocument());
    expect(screen.getByText('Show C')).toBeInTheDocument();
    expect(screen.getByText(/Movies/)).toBeInTheDocument();
    expect(screen.getByText(/Episodes/)).toBeInTheDocument();
  });

  it('summarises the unresolved total with a retry action', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('3 items unresolved')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Retry all now' })).toBeInTheDocument();
  });

  it('excludes given-up episodes from the unresolved count but still shows the subgroup', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Movie A')).toBeInTheDocument());
    // 2 movies + 1 wanted episode = 3; the give_up episode does not add to the count.
    expect(screen.getByText('3 items unresolved')).toBeInTheDocument();
    expect(screen.getByText('Given up')).toBeInTheDocument();
  });

  it('colour-ramps attempt counts at 5 and 10', async () => {
    const { container } = renderPage();
    await waitFor(() => expect(screen.getByText('Movie B')).toBeInTheDocument());
    const low = container.querySelector('[data-attempts="2"]') as HTMLElement;
    const high = container.querySelector('[data-attempts="11"]') as HTMLElement;
    // jsdom does NOT resolve var() references in .style.color, so assert the
    // custom property name is wired up rather than a computed rgb() value.
    expect(low.style.color).not.toContain('var(--pill-failed-fg)');
    expect(high.style.color).toContain('var(--pill-failed-fg)');
  });
});
