import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { Candidate } from '../../../api';
import { ReleasesPanel } from './ReleasesPanel';

const apiMocks = vi.hoisted(() => ({ libraryCandidates: vi.fn(), librarySwap: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const cand = (over: Partial<Candidate>): Candidate => ({
  info_hash: 'a'.repeat(40), name: 'Heat.1995.1080p.WEB-DL.x264', quality: '1080p', source: 'WEB-DL', size_gb: 4.2, seeders: 120,
  languages: ['en'], cached: true, scrapers: ['torrentio'], kept: true, rule: null, value: null, current: false, ...over,
});

function renderIt(props: Partial<React.ComponentProps<typeof ReleasesPanel>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onDone = vi.fn(); const onClose = vi.fn();
  render(<QueryClientProvider client={qc}><ReleasesPanel imdb="tt1" onDone={onDone} onClose={onClose} {...props} /></QueryClientProvider>);
  return { onDone, onClose };
}

describe('ReleasesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.libraryCandidates.mockResolvedValue({ current: { info_hash: 'd'.repeat(40), quality: '1080p', source: 'BluRay' }, candidates: [
      cand({}),
      cand({ info_hash: 'd'.repeat(40), name: 'Heat.1995.1080p.BluRay.x264', source: 'BluRay', current: true }),
      cand({ info_hash: 'c'.repeat(40), name: 'Heat.1995.2160p.REMUX', quality: '2160p', source: 'REMUX', size_gb: 60, cached: false, scrapers: ['zilean'] }),
      cand({ info_hash: 'b'.repeat(40), name: 'Heat.1995.CAM.x264', quality: '720p', source: 'CAM', kept: false, rule: 'SOURCE_EXCLUDED', value: 'cam' }),
    ] });
  });

  it('shows the loading line, then rows with badges and the dropped reason, current row without Use', async () => {
    renderIt();
    expect(screen.getByText('Asking the scrapers...')).toBeInTheDocument();
    const rows = await screen.findAllByRole('listitem');
    expect(rows).toHaveLength(4);
    expect(within(rows[0]).getByText('cached')).toBeInTheDocument();
    expect(within(rows[1]).getByText('current')).toBeInTheDocument();
    expect(within(rows[1]).queryByRole('button', { name: 'Use' })).not.toBeInTheDocument();
    expect(within(rows[2]).queryByText('cached')).not.toBeInTheDocument();
    expect(within(rows[3]).getByText('dropped: SOURCE_EXCLUDED = cam')).toBeInTheDocument();
    expect(within(rows[0]).getByText('4.2 GB')).toBeInTheDocument();
    expect(apiMocks.libraryCandidates).toHaveBeenCalledWith('tt1', undefined, undefined);
  });

  it('Use opens the confirm strip, warns for an uncached one, and Confirm posts the swap', async () => {
    apiMocks.librarySwap.mockResolvedValue({ ok: true, message: 'next play uses 2160p REMUX' });
    const { onDone, onClose } = renderIt();
    const rows = await screen.findAllByRole('listitem');
    await userEvent.click(within(rows[0]).getByRole('button', { name: 'Use' }));
    expect(screen.getByText(/Switch to this release\?/)).toBeInTheDocument();
    expect(screen.queryByText(/TorBox does not have this yet/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByText(/Switch to this release\?/)).not.toBeInTheDocument();
    await userEvent.click(within(rows[2]).getByRole('button', { name: 'Use' }));
    expect(screen.getByText(/TorBox does not have this yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Blacklist the current release' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(apiMocks.librarySwap).toHaveBeenCalledWith('tt1', { info_hash: 'c'.repeat(40), blacklist_old: true }));
    expect(await screen.findByText('next play uses 2160p REMUX')).toBeInTheDocument();
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
  });

  it('passes season and episode through', async () => {
    apiMocks.librarySwap.mockResolvedValue({ ok: true, message: 'ok' });
    renderIt({ season: 2, episode: 3 });
    const rows = await screen.findAllByRole('listitem');
    expect(apiMocks.libraryCandidates).toHaveBeenCalledWith('tt1', 2, 3);
    await userEvent.click(within(rows[0]).getByRole('button', { name: 'Use' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(apiMocks.librarySwap).toHaveBeenCalledWith('tt1', { info_hash: 'a'.repeat(40), season: 2, episode: 3, blacklist_old: false }));
  });

  it('empty and error states', async () => {
    apiMocks.libraryCandidates.mockResolvedValueOnce({ current: null, candidates: [] });
    const first = renderIt();
    expect(await screen.findByText('The scrapers returned nothing for this title.')).toBeInTheDocument();
    void first;
    apiMocks.libraryCandidates.mockRejectedValueOnce(new Error('502: scrapers unavailable: torrentio down'));
    apiMocks.libraryCandidates.mockResolvedValueOnce({ current: null, candidates: [cand({})] });
    renderIt();
    expect(await screen.findByText(/torrentio down/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findAllByRole('listitem')).toHaveLength(1);
  });
});
