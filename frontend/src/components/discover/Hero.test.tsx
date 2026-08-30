import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import { Hero } from './Hero';

const top = {
  tmdb_id: 42, media_type: 'movie', title: 'Dune: Part Three', year: '2026',
  rating: 8.4, votes: 900, popularity: 99, overview: 'Sand again.',
  poster_path: null, backdrop_path: '/bd.jpg', library_status: null,
};

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      trending: () => Promise.resolve({ results: [top] }),
      details: () => Promise.resolve({ ...top, runtime: 166, genres: ['Sci-Fi', 'Adventure'] }),
    },
  };
});

function renderHero() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Hero onRequest={() => {}} onOpen={() => {}} />
    </QueryClientProvider>,
  );
}

describe('Hero', () => {
  it('features the top trending title with its metadata', async () => {
    renderHero();
    // The title comes from the trending query; runtime/genres come from the
    // dependent details query (enabled once `top` resolves), one render tick
    // later. Wait for the whole metadata block together instead of just the
    // title, so the assertion isn't racing that second query.
    await waitFor(() => {
      expect(screen.getByText('Dune: Part Three')).toBeInTheDocument();
      expect(screen.getByText('Trending #1 this week')).toBeInTheDocument();
      expect(screen.getByText('8.4')).toBeInTheDocument();
      expect(screen.getByText('2h 46m')).toBeInTheDocument();
      expect(screen.getByText(/Sci-Fi/)).toBeInTheDocument();
    });
  });

  it('offers Request and Watchlist actions', async () => {
    renderHero();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Request title' })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Watchlist' })).toBeInTheDocument();
  });

  it('renders nothing while trending has not resolved', () => {
    const { container } = renderHero();
    expect(container.textContent).toBe('');
  });
});
