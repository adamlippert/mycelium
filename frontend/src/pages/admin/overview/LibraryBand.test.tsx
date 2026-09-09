import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { LibraryBand } from './LibraryBand';

const library = {
  movies: 312, episodes: 1940, series: 64, wanted: 7, upcoming: 2,
  qualities: { '2160p': 38, '1080p': 55, '720p': 6 },
  consistency: { db_items: 2252, strm_without_db: 1, db_without_strm: 0, arr_mirrored: 312, arr_total: 312,
    last_cleanup: { ran_at: '2026-09-08 03:00:00', deleted: 0 } },
};
const torbox = { usage: { torrent_count: 128, total_bytes: 3_400_000_000_000, total_gb: 3400, states: {} }, plan: 'Pro' };

describe('LibraryBand', () => {
  it('renders size tiles, quality shares and consistency', () => {
    render(<MemoryRouter><LibraryBand library={library} torbox={torbox} loading={false} /></MemoryRouter>);
    expect(screen.getByText('312')).toBeInTheDocument();
    expect(screen.getByText('1,940')).toBeInTheDocument();
    expect(screen.getByText('64 series')).toBeInTheDocument();
    expect(screen.getByText('2 upcoming')).toBeInTheDocument();
    expect(screen.getByText('128 torrents')).toBeInTheDocument();
    expect(screen.getByText('56%')).toBeInTheDocument();  // 55 of 99, rounded
    expect(screen.getByText('312/312')).toBeInTheDocument();
    const consistency = screen.getByText('Consistency').parentElement as HTMLElement;
    expect(within(consistency).getByText('1')).toHaveClass('text-warn');
    expect(screen.getByRole('link', { name: 'Run integrity check' })).toHaveAttribute('href', expect.stringContaining('maintenance'));
  });

  it('shows the TorBox tile as unavailable when the list failed', () => {
    render(<MemoryRouter><LibraryBand library={library} torbox={undefined} loading={false} /></MemoryRouter>);
    expect(screen.getByText('unavailable')).toBeInTheDocument();
  });
});
