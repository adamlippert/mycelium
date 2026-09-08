import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { LibraryRow } from '../../../api';
import { ActionBar } from './ActionBar';

const apiMocks = vi.hoisted(() => ({ retryRequest: vi.fn(), purgeRequest: vi.fn(), libraryAction: vi.fn(), libraryDetail: vi.fn(), reResolve: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});
const row = (id: number, imdb: string, title: string): LibraryRow => ({
  id, imdb_id: imdb, tmdb_id: null, title, media_type: 'movie', status: 'failed', error: null, quality: null, source: null, info_hash: null,
  seasons: null, created_at: '', updated_at: '', requester: 'auto', requester_id: null, requested_at: null, playability: null,
  missing_episodes: 0, retry: null, arr_mirrored: false, in_torbox: false, in_wanted_movies: false,
});

describe('ActionBar', () => {
  beforeEach(() => vi.clearAllMocks());

  it('retries each selected title in turn, counts, and reports failures', async () => {
    apiMocks.retryRequest.mockResolvedValueOnce({ ok: true }).mockRejectedValueOnce(new Error('500: boom'));
    const onDone = vi.fn();
    render(<ActionBar rows={[row(1, 'tt1', 'Heat'), row(2, 'tt2', 'Alien'), row(3, 'tt3', 'Dune')]} selected={new Set(['tt1', 'tt2'])} view="all" onDone={onDone} onClear={() => {}} />);
    expect(screen.getByText('2 selected')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run now' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(apiMocks.retryRequest).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/1 of 2 done, 1 failed/)).toBeInTheDocument();
    expect(screen.getByText(/Alien: 500: boom/)).toBeInTheDocument();
    expect(onDone).toHaveBeenCalled();
  });

  it('Remove asks once with the count and the queue view adds Run now and Drop', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<ActionBar rows={[row(1, 'tt1', 'Heat')]} selected={new Set(['tt1'])} view="queue" onDone={() => {}} onClear={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: 'Remove from library' }));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('1 title'));
    expect(apiMocks.purgeRequest).not.toHaveBeenCalled();
    apiMocks.libraryAction.mockResolvedValue({ ok: true, message: 'dropped from the retry queue' });
    await userEvent.click(screen.getByRole('button', { name: 'Drop from queue' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith('/ui/api/library/tt1/drop-retry'));
    expect(screen.getByRole('button', { name: 'Run now' })).toBeInTheDocument();
  });
});
