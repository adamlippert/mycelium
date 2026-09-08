import { useState } from 'react';
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
const selMap = (...rows: LibraryRow[]) => new Map(rows.map((r) => [r.imdb_id, r]));

describe('ActionBar', () => {
  beforeEach(() => vi.clearAllMocks());

  it('retries each selected title in turn, counts, and reports failures', async () => {
    apiMocks.retryRequest.mockResolvedValueOnce({ ok: true }).mockRejectedValueOnce(new Error('500: boom'));
    const onDone = vi.fn();
    const heat = row(1, 'tt1', 'Heat');
    const alien = row(2, 'tt2', 'Alien');
    render(<ActionBar selected={selMap(heat, alien)} view="all" onDone={onDone} onClear={() => {}} />);
    expect(screen.getByText('2 selected')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run now' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(apiMocks.retryRequest).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/1 of 2 done, 1 failed/)).toBeInTheDocument();
    expect(screen.getByText(/Alien: 500: boom/)).toBeInTheDocument();
    expect(onDone).toHaveBeenCalledWith(['tt1']);
  });

  it('Re-resolve reports a failure when every item fails to resolve', async () => {
    apiMocks.libraryDetail.mockResolvedValue({ items: [{ token: 'tok1' }] });
    apiMocks.reResolve.mockResolvedValue({ ok: true, resolved: false });
    const onDone = vi.fn();
    render(<ActionBar selected={selMap(row(1, 'tt1', 'Heat'))} view="all" onDone={onDone} onClear={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: 'Re-resolve' }));
    await waitFor(() => expect(apiMocks.reResolve).toHaveBeenCalledWith('tok1'));
    expect(await screen.findByText(/0 of 1 done, 1 failed/)).toBeInTheDocument();
    expect(screen.getByText(/Heat: 0 of 1 resolved/)).toBeInTheDocument();
    expect(onDone).toHaveBeenCalledWith([]);
  });

  it('Remove asks once with the count and the queue view adds Run now and Drop', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<ActionBar selected={selMap(row(1, 'tt1', 'Heat'))} view="queue" onDone={() => {}} onClear={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: 'Remove from library' }));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('1 title'));
    expect(apiMocks.purgeRequest).not.toHaveBeenCalled();
    apiMocks.libraryAction.mockResolvedValue({ ok: true, message: 'dropped from the retry queue' });
    await userEvent.click(screen.getByRole('button', { name: 'Drop from queue' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith('/ui/api/library/tt1/drop-retry'));
    expect(screen.getByRole('button', { name: 'Run now' })).toBeInTheDocument();
  });

  // Mirrors how the Library page wires ActionBar: onDone prunes the
  // succeeded ids straight out of the selection it hands back down.
  function Harness({ onDone }: { onDone: (processed: string[]) => void }) {
    const [selected, setSelected] = useState(selMap(row(1, 'tt1', 'Heat'), row(2, 'tt2', 'Alien')));
    return (
      <ActionBar
        selected={selected}
        view="all"
        onDone={(processed) => {
          onDone(processed);
          setSelected((s) => { const n = new Map(s); processed.forEach((id) => n.delete(id)); return n; });
        }}
        onClear={() => setSelected(new Map())}
      />
    );
  }

  it('keeps "N of N done" visible after a fully successful run empties the selection', async () => {
    apiMocks.retryRequest.mockResolvedValue({ ok: true });
    const onDone = vi.fn();
    render(<Harness onDone={onDone} />);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(['tt1', 'tt2']));
    expect(await screen.findByText(/2 of 2 done/)).toBeInTheDocument();
    expect(screen.getByText('0 selected')).toBeInTheDocument();
  });

  it('Clear drops the last progress line along with the selection', async () => {
    apiMocks.retryRequest.mockResolvedValue({ ok: true });
    const onDone = vi.fn();
    render(<Harness onDone={onDone} />);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText(/2 of 2 done/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.queryByText(/done/)).not.toBeInTheDocument();
    expect(screen.queryByText('0 selected')).not.toBeInTheDocument();
  });

  it('disables the ops when nothing is selected, even while the bar stays open', async () => {
    apiMocks.retryRequest.mockResolvedValue({ ok: true });
    const onDone = vi.fn();
    render(<Harness onDone={onDone} />);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText(/2 of 2 done/);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeDisabled();
  });
});
