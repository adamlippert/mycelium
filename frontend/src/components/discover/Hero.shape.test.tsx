import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import { Hero } from './Hero';
import PosterGrid from '../PosterGrid';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';

const results = [{
  tmdb_id: 42, media_type: 'movie' as const, title: 'Dune: Part Three', year: '2026',
  rating: 8.4, votes: 900, popularity: 99, overview: 'Sand again.',
  poster_path: null, backdrop_path: '/bd.jpg', library_status: null,
}];

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      trending: () => Promise.resolve({ results }),
      details: () => Promise.resolve({ ...results[0], runtime: 166, genres: ['Sci-Fi'] }),
    },
  };
});

vi.mock('../../hooks/useWatched', () => ({ useWatched: () => new Set<string>() }));

// Discover's trending Row, reduced to the part that matters: it shares Hero's
// cache key and unwraps .results itself.
function TrendingRow() {
  const { data } = useQuery({
    queryKey: ['trending', 'all', 'week'],
    queryFn: () => api.trending('all', 'week').then((r) => r.results),
  });
  return <PosterGrid items={data} onItemClick={() => {}} />;
}

describe('Hero and the trending Row share a cache key', () => {
  it('agree on the cached shape, so neither corrupts the other', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <Hero onRequest={() => {}} onWatchlist={() => {}} />
        <TrendingRow />
      </QueryClientProvider>,
    );

    // Hero features the top title and the Row lists it: both read one entry.
    await waitFor(() => expect(screen.getByText('Trending #1 this week')).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByText('Dune: Part Three').length).toBeGreaterThan(1));
  });
});
