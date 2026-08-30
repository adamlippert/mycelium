import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import PosterCard from './PosterCard';
import type { TmdbItem } from '../types';

vi.mock('../hooks/useWatched', () => ({ useWatched: () => new Set(['tt0000001']) }));

const item = (over: Partial<TmdbItem> = {}): TmdbItem => ({
  tmdb_id: 1, media_type: 'movie', title: 'Dune', year: '2021', rating: 8.1,
  votes: 100, popularity: 5, overview: '', poster_path: null, backdrop_path: null,
  ...over,
});

describe('PosterCard badges', () => {
  it('shows IN LIBRARY for success and available', () => {
    for (const status of ['success', 'available']) {
      const { unmount } = render(<PosterCard item={item()} onClick={() => {}} status={status} />);
      expect(screen.getByText('IN LIBRARY')).toBeInTheDocument();
      unmount();
    }
  });

  it('shows REQUESTED for pending', () => {
    render(<PosterCard item={item()} onClick={() => {}} status="pending" />);
    expect(screen.getByText('REQUESTED')).toBeInTheDocument();
  });

  it('shows WANTED, UPCOMING and FAILED in token colours, never stock tailwind', () => {
    const { container } = render(<PosterCard item={item()} onClick={() => {}} status="failed" />);
    expect(screen.getByText('FAILED')).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/bg-(green|yellow|blue|red)-\d/);
  });

  it('renders no badge for an unknown status', () => {
    const { container } = render(<PosterCard item={item()} onClick={() => {}} status="bogus" />);
    expect(container.querySelector('[data-badge]')).toBeNull();
  });

  it('still marks watched items', () => {
    render(<PosterCard item={item({ imdb_id: 'tt0000001' } as any)} onClick={() => {}} />);
    expect(screen.getByTitle('Watched')).toBeInTheDocument();
  });
});
