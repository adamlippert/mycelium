import { useState } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TitleDrawer } from './TitleDrawer';

function focusablesIn(el: HTMLElement): HTMLElement[] {
  return Array.from(el.querySelectorAll<HTMLElement>('a[href], button, input, select, textarea, [tabindex]'))
    .filter((e) => !(e as HTMLButtonElement).disabled && e.getAttribute('tabindex') !== '-1');
}

function Harness({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Opener</button>
      {open && <TitleDrawer imdb="tt1" onClose={() => { setOpen(false); onClose(); }} onChanged={() => {}} onPurged={() => {}} />}
    </>
  );
}

const apiMocks = vi.hoisted(() => ({ libraryDetail: vi.fn(), libraryAction: vi.fn(), retryRequest: vi.fn(), purgeRequest: vi.fn(), reResolve: vi.fn(), deleteRequest: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const detail = (over: Record<string, unknown> = {}) => ({
  request: { id: 1, imdb_id: 'tt1', title: 'Heat', media_type: 'movie', status: 'failed', error: 'no release', quality: null, source: null,
    info_hash: 'a'.repeat(40), seasons: null, created_at: '2026-09-01 10:00:00', updated_at: '2026-09-02 10:00:00', tmdb_id: 949, arr_mirrored_at: null },
  items: [{ token: 'tok', info_hash: 'a'.repeat(40), strm_path: '/media/movies/Heat (1995)/Heat (1995).strm', torbox_id: 5, last_played: null, play_count: 0, season: null, episode: null, debrid_provider: 'torbox', quality: '1080p' }],
  playability: [{ content_key: 'tt1', status: 'degraded', last_ok_provider: null, last_ok_at: null, last_fail_reason: 'cdn 404', consecutive_failures: 2, updated_at: '2026-09-02 10:00:00' }],
  episodes: null, monitored: null, retry: { id: 3, attempt: 2, next_retry_at: '2026-09-03 00:00:00' }, wanted_movie: null,
  user_requests: [], seerr_request_id: null, override: null, hashes: [], activity: [], arr: { mirrored_at: null },
  mirror_on: true,
  ...over,
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn(); const onChanged = vi.fn(); const onPurged = vi.fn();
  render(<QueryClientProvider client={qc}><TitleDrawer imdb="tt1" onClose={onClose} onChanged={onChanged} onPurged={onPurged} /></QueryClientProvider>);
  return { onClose, onChanged, onPurged };
}

describe('TitleDrawer', () => {
  beforeEach(() => { vi.clearAllMocks(); apiMocks.libraryDetail.mockResolvedValue(detail()); });

  it('shows the header, the status, release and playability cards, and hides empty ones', async () => {
    renderIt();
    expect(await screen.findByRole('heading', { name: /Heat/ })).toBeInTheDocument();
    expect(screen.getByText('no release')).toBeInTheDocument();
    expect(screen.getByText(/attempt 2/)).toBeInTheDocument();
    expect(screen.getByText('/media/movies/Heat (1995)/Heat (1995).strm')).toBeInTheDocument();
    expect(screen.getByText('cdn 404')).toBeInTheDocument();
    expect(screen.queryByText('Requests')).not.toBeInTheDocument();
  });

  it('runs an action, shows its message and refetches', async () => {
    apiMocks.libraryAction.mockResolvedValue({ ok: true, message: 'dropped from the retry queue' });
    const { onChanged } = renderIt();
    await userEvent.click(await screen.findByRole('button', { name: 'Drop from queue' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith('/ui/api/library/tt1/drop-retry'));
    expect(await screen.findByText('dropped from the retry queue')).toBeInTheDocument();
    await waitFor(() => expect(apiMocks.libraryDetail).toHaveBeenCalledTimes(2));
    expect(onChanged).toHaveBeenCalled();
  });

  it('Retry uses the request route, Purge asks first, Escape closes', async () => {
    apiMocks.retryRequest.mockResolvedValue({ ok: true, title: 'Heat' });
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { onClose } = renderIt();
    await userEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(apiMocks.retryRequest).toHaveBeenCalledWith(1));
    await userEvent.click(screen.getByRole('button', { name: 'Purge' }));
    expect(apiMocks.purgeRequest).not.toHaveBeenCalled();
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });

  it('Purge prunes the title from the bulk selection before closing', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    apiMocks.purgeRequest.mockResolvedValue({ ok: true });
    const { onPurged, onChanged, onClose } = renderIt();
    await userEvent.click(await screen.findByRole('button', { name: 'Purge' }));
    await waitFor(() => expect(apiMocks.purgeRequest).toHaveBeenCalledWith(1));
    expect(onPurged).toHaveBeenCalledWith('tt1');
    expect(onChanged).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('Forget request keeps the files and prunes the selection before closing', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    apiMocks.deleteRequest.mockResolvedValue({ ok: true });
    const { onPurged, onChanged, onClose } = renderIt();
    await userEvent.click(await screen.findByRole('button', { name: 'Forget request' }));
    await waitFor(() => expect(apiMocks.deleteRequest).toHaveBeenCalledWith(1));
    expect(onPurged).toHaveBeenCalledWith('tt1');
    expect(onChanged).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('shows the Arr mirror card when mirroring is on', async () => {
    apiMocks.libraryDetail.mockResolvedValue(detail({ mirror_on: true }));
    renderIt();
    expect(await screen.findByText('Arr mirror')).toBeInTheDocument();
  });

  it('hides the Arr mirror card when mirroring is off', async () => {
    apiMocks.libraryDetail.mockResolvedValue(detail({ mirror_on: false }));
    renderIt();
    await screen.findByRole('heading', { name: /Heat/ });
    expect(screen.queryByText('Arr mirror')).not.toBeInTheDocument();
  });

  it('shows a friendly message when the title is not in the library yet', async () => {
    apiMocks.libraryDetail.mockRejectedValue(new Error('404: not found'));
    renderIt();
    expect(await screen.findByRole('heading', { name: 'Not in the library' })).toBeInTheDocument();
    expect(await screen.findByText('This title is not in the library yet, so there is nothing to act on here.')).toBeInTheDocument();
  });

  it('is an aria-modal dialog, traps Tab/Shift+Tab focus inside it, and restores focus to the opener on close', async () => {
    const onClose = vi.fn();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><Harness onClose={onClose} /></QueryClientProvider>);
    const opener = screen.getByRole('button', { name: 'Opener' });
    await userEvent.click(opener);

    const dialog = await screen.findByRole('dialog', { name: 'Title details' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    await screen.findByRole('heading', { name: /Heat/ });

    const closeButton = within(dialog).getByRole('button', { name: 'Close' });
    expect(document.activeElement).toBe(closeButton);

    const focusable = focusablesIn(dialog);
    const last = focusable[focusable.length - 1];
    await userEvent.tab({ shift: true });
    expect(document.activeElement).toBe(last);

    await userEvent.tab();
    expect(document.activeElement).toBe(closeButton);

    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(onClose).toHaveBeenCalled();
    expect(document.activeElement).toBe(opener);
  });
});
