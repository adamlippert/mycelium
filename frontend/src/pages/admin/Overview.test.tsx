import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import Overview from './Overview';
import { api } from '../../api';

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      overview: () => Promise.resolve({
        status: {
          scrapers: [
            { name: 'Zilean', state: 'ok', latency_ms: 120 },
            { name: 'Torrentio', state: 'down', latency_ms: null },
          ],
          torbox_adds: { uncached: 3, cached: 41, limit: 60, resets_in_sec: 2520 },
          failures_7d: 2,
          queue: { retry: 1, wanted: 4 },
          attention: 0,
          approvals: { pending: 0, oldest_age_sec: null },
        },
        activity: {
          plays: { today: 4, week: 20, titles_today: 3, titles_week: 12 },
          requests_7d: { total: 10, succeeded: 8, failed: 2, success_rate: 80 },
          egress: { proxied_bytes: 1_500_000_000_000, estimated_bytes: 2_250_000_000_000 },
        },
        library: {
          movies: 312, episodes: 340, series: 12, wanted: 9, upcoming: 3,
          qualities: { '1080p': 10, '2160p': 5 },
          consistency: {
            db_items: 300, strm_without_db: 0, db_without_strm: 0,
            arr_mirrored: 5, arr_total: 5,
            last_cleanup: null,
          },
        },
        torbox: { recent_streams: 2, last_429_at: null },
      }),
      health: () => Promise.resolve({
        services: [
          { name: 'TorBox', status: 'ok' },
          { name: 'Zilean', status: 'disabled' },
          { name: 'Torrentio', status: 'down', note: 'Movies: trickplay, chapter images' },
        ],
        stream_front: true,
      }),
      activity: () => Promise.resolve({
        events: [
          { id: 1, created_at: '2026-08-29T10:00:00', event: 'added', title: 'Movie A', message: '', success: true },
          { id: 2, created_at: '2026-08-29T09:00:00', event: 'failed', title: 'Movie B', message: 'no release', success: false },
        ],
      }),
      torboxQuota: () => Promise.resolve({
        count: 5, limit: 60, window_sec: 3600,
        cached_count: 27,
        by_reason: { webhook: 3, manual: 9 },
        oldest_ts: 1700000000, resets_in_sec: 125,
      }),
      torboxUsage: () => Promise.resolve({
        usage: {
          torrent_count: 77,
          total_bytes: 107374182400,
          total_gb: 100.5,
          states: { downloading: 21, uploading: 44, meta_dl: 8 },
        },
        plan: 'Pro',
      }),
      metricsSummary: vi.fn(() => Promise.resolve({
        quality: [{ label: '1080p', count: 4, avg_real: null, sum_int: null }],
        sources: [{ label: 'Zilean', count: 10, avg_real: null, sum_int: null }],
        unique_sources: [{ label: 'Zilean', count: 3, avg_real: null, sum_int: null }],
        latency: [{ label: 'movie', count: 1, avg_real: 12.34, sum_int: null }],
        failures: [],
      })),
      storage: () => Promise.resolve({
        folders: [
          { path: 'movies/Foo (2024)', count: 42 },
          { path: 'series/Bar', count: 17 },
        ],
      }),
      webhookSecret: () => Promise.resolve({ secret: 'super-secret-value', source: 'env', previous_valid_until: null }),
      session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin' } }),
    },
  };
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/admin']}>
        <Overview />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Overview tab', () => {
  it('renders the five bands in order with the status strip first', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByRole('group', { name: 'Failures 7d: problem' })).toBeInTheDocument());
    const bands = screen.getAllByRole('region').map((r) => r.getAttribute('aria-label'));
    expect(bands).toEqual(['Right now', 'Activity', 'Library', 'TorBox', 'Reference']);
  });

  it('feeds the bands from the aggregated payload', async () => {
    renderIt();
    expect(await screen.findByText('312')).toBeInTheDocument();
    expect(screen.getByText('Plays today')).toBeInTheDocument();
    expect(screen.getByText('Streamed in last 15 min')).toBeInTheDocument();
  });

  it('keeps the reference sections closed and does not fetch them until opened', async () => {
    renderIt();
    await screen.findByText('312');
    expect(api.metricsSummary).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText('Metrics, 30 days'));
    await waitFor(() => expect(api.metricsSummary).toHaveBeenCalledTimes(1));
  });

  it('has exactly one TorBox card', async () => {
    renderIt();
    await screen.findByText('312');
    expect(screen.queryByText('TorBox quota')).not.toBeInTheDocument();
    expect(screen.queryByText('TorBox Usage')).not.toBeInTheDocument();
    expect(screen.getAllByText('TorBox').length).toBeGreaterThanOrEqual(1);
  });
});
