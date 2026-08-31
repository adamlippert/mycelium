import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import PosterGrid from './PosterGrid';

vi.mock('../hooks/useWatched', () => ({ useWatched: () => new Set<string>() }));

describe('PosterGrid', () => {
  it('shows the empty state when a caller hands it a non-array', () => {
    // Shipped as a black screen in 0.8.0: Hero and Discover's trending Row
    // shared a React Query key while returning different shapes, so the Row
    // received {results: [...]}. An object is truthy and its .length is
    // undefined rather than 0, so the old guard let it through and the map
    // below threw. A wrong shape must degrade to the empty state, never to a
    // blank page.
    const notAnArray = { results: [] } as unknown as undefined;
    expect(() => render(<PosterGrid items={notAnArray} onItemClick={() => {}} />)).not.toThrow();
    expect(screen.getByText('Nothing to show.')).toBeInTheDocument();
  });

  it('still renders real items', () => {
    const items = [{
      tmdb_id: 1, media_type: 'movie' as const, title: 'Dune', year: '2021',
      rating: 8.1, votes: 1, popularity: 1, overview: '', poster_path: null,
      backdrop_path: null,
    }];
    render(<PosterGrid items={items} onItemClick={() => {}} />);
    expect(screen.getByText('Dune')).toBeInTheDocument();
  });
});
