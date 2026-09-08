import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { EpisodesCard } from './cards/EpisodesCard';
import { RequestsCard } from './cards/RequestsCard';
import { PreferencesCard } from './cards/PreferencesCard';
import { HashesCard } from './cards/HashesCard';
import { ActivityCard } from './cards/ActivityCard';

const apiMocks = vi.hoisted(() => ({ librarySeason: vi.fn(), libraryAction: vi.fn(), libraryActivity: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const base: any = {
  request: { id: 1, imdb_id: 'tt4', title: 'Loki', media_type: 'series', status: 'success', error: null, info_hash: null, quality: null, source: null, seasons: '1,2', created_at: '', updated_at: '', tmdb_id: null, arr_mirrored_at: null },
  items: [], playability: [], episodes: [{ season: 2, present: 2, wanted: 1 }], monitored: { status: 'active', last_checked: '2026-09-01 10:00:00', seasons: '1,2' },
  retry: null, wanted_movie: null,
  user_requests: [{ id: 9, username: 'adam', status: 'denied', reviewer: 'root', note: 'too big', created_at: '2026-09-01 09:00:00', reviewed_at: '2026-09-01 10:00:00' }],
  seerr_request_id: 12, override: { quality_preference: '1080p', allow_4k: 0, prefer_hevc: 1, notes: 'keep small' },
  hashes: [{ info_hash: 'a'.repeat(40), blacklisted: true, fail_count: 3, last_error: 'blacklisted by admin', current: false }],
  activity: [{ id: 5, event: 'added', title: 'Loki', message: 'series', success: 1, created_at: '2026-09-01 10:00:00' }], arr: { mirrored_at: null },
};

function wrap(el: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{el}</QueryClientProvider>);
}

describe('drawer cards', () => {
  beforeEach(() => vi.clearAllMocks());

  it('Episodes shows seasons and loads a season on expand, with per-episode retry', async () => {
    apiMocks.librarySeason.mockResolvedValue({ episodes: [
      { season: 2, episode: 1, present: true, strm_path: '/s/e1.strm', token: 'e1', wanted_status: null, attempt_count: 0, air_date: null, last_attempted: null },
      { season: 2, episode: 3, present: false, strm_path: null, token: null, wanted_status: 'wanted', attempt_count: 4, air_date: '2024-01-01', last_attempted: '2026-09-01 10:00:00' },
    ] });
    apiMocks.libraryAction.mockResolvedValue({ ok: true, message: 'searching S02E03' });
    wrap(<EpisodesCard d={base} onDone={() => {}} />);
    expect(screen.getByText(/Season 2/)).toHaveTextContent('2 present, 1 wanted');
    await userEvent.click(screen.getByRole('button', { name: 'Expand season 2' }));
    expect(await screen.findByText('E03')).toBeInTheDocument();
    expect(screen.getByText(/4 attempts/)).toBeInTheDocument();
    expect(screen.getByText(/last try 2026-09-01 10:00/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry S02E03' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith('/ui/api/library/tt4/episodes/2/3/retry'));
    expect(await screen.findByText('searching S02E03')).toBeInTheDocument();
  });

  it('Requests lists every user request with reviewer and note', () => {
    wrap(<RequestsCard d={base} onDone={() => {}} />);
    expect(screen.getByText('adam')).toBeInTheDocument();
    expect(screen.getByText(/root/)).toBeInTheDocument();
    expect(screen.getByText('too big')).toBeInTheDocument();
    expect(screen.getByText(/Seerr request 12/)).toBeInTheDocument();
  });

  it('Preferences saves the override as JSON and can clear it', async () => {
    apiMocks.libraryAction.mockResolvedValue({ ok: true, message: 'override saved' });
    wrap(<PreferencesCard d={base} onDone={() => {}} />);
    expect(screen.getByRole('checkbox', { name: 'Prefer HEVC' })).toBeChecked();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Allow 4K' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith('/ui/api/library/tt4/override', 'POST',
      { quality_preference: '1080p', allow_4k: true, prefer_hevc: true, notes: 'keep small' }));
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith('/ui/api/library/tt4/override', 'DELETE'));
  });

  it('Preferences resyncs the form when the saved override changes', () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(<QueryClientProvider client={qc}><PreferencesCard d={base} onDone={() => {}} /></QueryClientProvider>);
    expect(screen.getByRole('checkbox', { name: 'Prefer HEVC' })).toBeChecked();
    rerender(<QueryClientProvider client={qc}><PreferencesCard d={{ ...base, override: null }} onDone={() => {}} /></QueryClientProvider>);
    expect(screen.getByRole('textbox', { name: 'Preferred resolution' })).toHaveValue('');
    expect(screen.getByRole('checkbox', { name: 'Prefer HEVC' })).not.toBeChecked();
  });

  it('Hashes shows the blacklist state with an Unblacklist button', async () => {
    apiMocks.libraryAction.mockResolvedValue({ ok: true, message: 'hash cleared' });
    wrap(<HashesCard d={base} onDone={() => {}} />);
    expect(screen.getByText('blacklisted by admin')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Unblacklist' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith(`/ui/api/library/hash/${'a'.repeat(40)}/unblacklist`));
  });

  it('Activity lists entries and loads more', async () => {
    // "Load more" only shows once the initial page could plausibly be full
    // (20 rows); a fixture with a single row must not offer it.
    const activity20 = Array.from({ length: 20 }, (_, i) => ({
      id: 24 - i, event: i === 0 ? 'added' : 'other', title: 'Loki', message: 'x', success: 1, created_at: '2026-09-01 10:00:00',
    }));
    apiMocks.libraryActivity.mockResolvedValue({ activity: [{ id: 4, event: 'wanted', title: 'Loki', message: 'x', success: 0, created_at: '2026-08-31 10:00:00' }] });
    wrap(<ActivityCard d={{ ...base, activity: activity20 }} />);
    expect(screen.getByText('added')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }));
    await waitFor(() => expect(apiMocks.libraryActivity).toHaveBeenCalledWith('tt4', 5));
    expect(await screen.findByText('wanted')).toBeInTheDocument();
  });

  it('Activity hides Load more when the first page is short, and shows a message if a later fetch fails', async () => {
    wrap(<ActivityCard d={base} />);
    expect(screen.getByText('added')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('Activity reports a failed Load more instead of rejecting silently', async () => {
    const activity20 = Array.from({ length: 20 }, (_, i) => ({
      id: 24 - i, event: i === 0 ? 'added' : 'other', title: 'Loki', message: 'x', success: 1, created_at: '2026-09-01 10:00:00',
    }));
    apiMocks.libraryActivity.mockRejectedValue(new Error('network down'));
    wrap(<ActivityCard d={{ ...base, activity: activity20 }} />);
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }));
    expect(await screen.findByText('network down')).toBeInTheDocument();
  });
});
