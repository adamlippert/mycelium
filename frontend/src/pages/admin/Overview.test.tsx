import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import Overview from './Overview';

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      stats: () => Promise.resolve({
        library: { movie_count: 120, episode_count: 340, series_count: 12 },
        requests: { total: 55, succeeded_7d: 41, failed_7d: 7, success_rate_7d: 85.4 },
        wanted: { active: 9, found: 2, give_up: 1 },
        movies_pending: 3,
        qualities: { '1080p': 10, '2160p': 5, '4k': 1 },
      }),
      health: () => Promise.resolve({
        services: [
          { name: 'TorBox', status: 'ok' },
          { name: 'Zilean', status: 'disabled' },
          { name: 'Torrentio', status: 'down' },
        ],
      }),
      activity: () => Promise.resolve({
        events: [
          { created_at: '2026-08-29T10:00:00', event: 'added', title: 'Movie A', message: '', success: true },
          { created_at: '2026-08-29T09:00:00', event: 'failed', title: 'Movie B', message: 'no release', success: false },
        ],
      }),
      torboxList: () => Promise.resolve({
        torrents: [
          { id: 1, name: 'a', hash: 'h1', size: 4294967296, download_state: 'completed', download_finished: true, progress: 1, created_at: '', file_count: 1 },
          { id: 2, name: 'b', hash: 'h2', size: 2147483648, download_state: 'completed', download_finished: true, progress: 1, created_at: '', file_count: 1 },
        ],
      }),
      retryQueue: () => Promise.resolve({ items: [{ id: 1 }, { id: 2 }, { id: 3 }] }),
      webhookSecret: () => Promise.resolve({ secret: 'super-secret-value', source: 'env' }),
      releases: () => Promise.resolve({
        releases: [
          { version: '0.7.7', date: '2026-08-20', notes: ['Fixed streaming bug'] },
          { version: '0.7.6', date: '2026-08-10', notes: ['Earlier release'] },
        ],
      }),
      torboxQuota: () => Promise.resolve({
        count: 5, limit: 60, window_sec: 3600,
        by_reason: { webhook: 3, manual: 9 },
        oldest_ts: 1700000000, resets_in_sec: 125,
      }),
      metricsSummary: () => Promise.resolve({
        quality: [{ label: '1080p', count: 4, avg_real: null, sum_int: null }],
        sources: [{ label: 'Zilean', count: 10, avg_real: null, sum_int: null }],
        unique_sources: [{ label: 'Zilean', count: 3, avg_real: null, sum_int: null }],
        latency: [{ label: 'movie', count: 1, avg_real: 12.34, sum_int: null }],
        failures: [],
      }),
      storage: () => Promise.resolve({
        folders: [
          { path: 'movies/Foo (2024)', count: 42 },
          { path: 'series/Bar', count: 17 },
        ],
      }),
      libraryHealth: () => Promise.resolve({
        strm_count: 300, db_count: 295, strm_without_db: 5, db_without_strm: 0,
      }),
      session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin' } }),
    },
  };
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Overview /></QueryClientProvider>);
}

describe('Overview tab', () => {
  it('renders the four metric tiles with real, substituted values', async () => {
    renderIt();
    await waitFor(() => {
      // Requests 7d: succeeded_7d + failed_7d as the value (fix round 1;
      // requests.total is all-time, not a 7d figure), sub-line unchanged.
      expect(screen.getByText('48')).toBeInTheDocument();
      expect(screen.getByText('41 ok / 7 fail')).toBeInTheDocument();
      // Queue depth: retry-queue rows (3) + active wanted (9)
      expect(screen.getByText('12')).toBeInTheDocument();
      // TorBox library: item count + summed size in GiB
      expect(screen.getByText('2')).toBeInTheDocument();
      expect(screen.getByText('6.0 GiB')).toBeInTheDocument();
      // Failures 7d
      expect(screen.getByText('7')).toBeInTheDocument();
    });
  });

  it('never resurrects the dropped mockup tiles', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByText('48')).toBeInTheDocument());
    expect(screen.queryByText(/Active streams/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Cache hit rate/i)).not.toBeInTheDocument();
  });

  it('ports the four fix-round-1 cards: TorBox quota, metrics, storage, library health', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('TorBox quota')).toBeInTheDocument();
      expect(screen.getByText('5 / 60')).toBeInTheDocument();
      expect(screen.getByText('Metrics (30d)')).toBeInTheDocument();
      expect(screen.getByText('12.3s')).toBeInTheDocument();
      expect(screen.getByText('Top folders')).toBeInTheDocument();
      expect(screen.getByText('movies/Foo (2024)')).toBeInTheDocument();
      expect(screen.getByText('Library health')).toBeInTheDocument();
      expect(screen.getByText('300')).toBeInTheDocument();
    });
  });

  it('shows one status dot per health service', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getAllByTestId('health-service')).toHaveLength(3);
    });
  });

  it('lists a version in the releases changelog', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('v0.7.7')).toBeInTheDocument();
    });
  });
});
