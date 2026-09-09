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

function renderIt(props: Partial<Parameters<typeof LibraryBand>[0]> = {}) {
  return render(
    <MemoryRouter>
      <LibraryBand library={library} torbox={torbox} loading={false} torboxLoading={false} errors={[]} {...props} />
    </MemoryRouter>,
  );
}

describe('LibraryBand', () => {
  it('renders size tiles, quality shares and consistency', () => {
    renderIt();
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
    renderIt({ torbox: undefined });
    expect(screen.getByText('unavailable')).toBeInTheDocument();
  });

  it('shows the TorBox tile as "-" while its query is loading, not unavailable', () => {
    renderIt({ torbox: undefined, torboxLoading: true });
    expect(screen.queryByText('unavailable')).not.toBeInTheDocument();
    const sizeCard = screen.getByText('Size').parentElement as HTMLElement;
    expect(within(sizeCard).getByText('-')).toBeInTheDocument();
  });

  it('marks the size tiles unavailable when the base block failed, even with library data present', () => {
    renderIt({ errors: ['base'] });
    const sizeCard = screen.getByText('Size').parentElement as HTMLElement;
    expect(within(sizeCard).getAllByText('unavailable').length).toBeGreaterThanOrEqual(3);
  });

  it('marks the consistency card unavailable when the consistency block failed', () => {
    renderIt({ errors: ['consistency'] });
    const consistencyCard = screen.getByText('Consistency').parentElement as HTMLElement;
    expect(within(consistencyCard).getByText('unavailable')).toBeInTheDocument();
  });
});
