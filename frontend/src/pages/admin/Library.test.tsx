import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { LibraryRow } from '../../api';
import Library from './Library';

const apiMocks = vi.hoisted(() => ({
  library: vi.fn(), libraryViews: vi.fn(), users: vi.fn(), libraryDetail: vi.fn(),
  retryRequest: vi.fn(), purgeRequest: vi.fn(), libraryAction: vi.fn(), reResolve: vi.fn(),
}));
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const row = (over: Partial<LibraryRow>): LibraryRow => ({
  id: 1, imdb_id: 'tt1', tmdb_id: null, title: 'Heat', media_type: 'movie', status: 'success', error: null,
  quality: '1080p', source: 'WEB-DL', info_hash: 'a'.repeat(40), seasons: null, created_at: '2026-09-01 10:00:00',
  updated_at: '2026-09-02 10:00:00', requester: 'adam', requester_id: 1, requested_at: '2026-09-01 09:00:00',
  playability: null, missing_episodes: 0, retry: null, arr_mirrored: true, in_torbox: true, in_wanted_movies: false,
  ...over,
});

function renderIt(hash = '#library') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[`/admin${hash}`]}>
      <QueryClientProvider client={qc}><Library /></QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('Library tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.libraryViews.mockResolvedValue({
      counts: { all: 2, attention: 1, wanted: 0, queue: 1, incomplete: 0, unmirrored: 0 },
      mirror_on: true,
    });
    apiMocks.users.mockResolvedValue({ users: [{ id: 1, username: 'adam' }] });
    apiMocks.library.mockResolvedValue({
      rows: [row({}), row({ id: 2, imdb_id: 'tt2', title: 'Alien', status: 'failed', error: 'no release', requester: 'auto',
        playability: { status: 'degraded', last_fail_reason: 'cdn 404' }, retry: { attempt: 3, next_retry_at: '2026-09-03 00:00:00' },
        arr_mirrored: false, in_torbox: false })],
      total: 2, page: 1, per_page: 50,
    });
  });

  it('renders views with counts, the table with badges, and requests the default query', async () => {
    renderIt();
    const nav = await screen.findByRole('navigation', { name: 'Library views' });
    await waitFor(() => expect(within(nav).getByRole('button', { name: /Needs attention/ })).toHaveTextContent('1'));
    expect(await screen.findByText('Heat')).toBeInTheDocument();
    expect(screen.getByText('no release')).toBeInTheDocument();
    const alien = screen.getByText('Alien').closest('tr')!;
    expect(within(alien).getByTitle('cdn 404')).toBeInTheDocument();
    expect(within(alien).getByTitle('retry attempt 3')).toBeInTheDocument();
    expect(within(screen.getByText('Heat').closest('tr')!).getByTitle('mirrored in the arr')).toBeInTheDocument();
    expect(apiMocks.library).toHaveBeenCalledWith(expect.objectContaining({ view: 'all', page: '1', per_page: '50' }));
  });

  it('a view click and a filter change re-query and update the hash', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Needs attention/ }));
    await waitFor(() => expect(apiMocks.library).toHaveBeenLastCalledWith(expect.objectContaining({ view: 'attention' })));
    expect(window.location.hash || screen.getByTestId('library-hash').textContent).toContain('view=attention');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Type' }), 'series');
    await waitFor(() => expect(apiMocks.library).toHaveBeenLastCalledWith(expect.objectContaining({ view: 'attention', type: 'series', page: '1' })));
  });

  it('restores state from the hash and pages', async () => {
    apiMocks.library.mockResolvedValue({ rows: [row({})], total: 120, page: 2, per_page: 50 });
    renderIt('#library?view=wanted&page=2');
    await waitFor(() => expect(apiMocks.library).toHaveBeenCalledWith(expect.objectContaining({ view: 'wanted', page: '2' })));
    expect(await screen.findByText(/51 to 100 of 120/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(apiMocks.library).toHaveBeenLastCalledWith(expect.objectContaining({ page: '3' })));
  });

  it('sorts by clicking a header and selects rows', async () => {
    renderIt();
    await screen.findByText('Heat');
    await userEvent.click(screen.getByRole('button', { name: 'Sort by title' }));
    await waitFor(() => expect(apiMocks.library).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'title', order: 'asc' })));
    await userEvent.click(screen.getByRole('button', { name: 'Sort by added' }));
    await waitFor(() => expect(apiMocks.library).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'created', order: 'asc' })));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select Heat' }));
    expect(screen.getByText('1 selected')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select all on this page' }));
    expect(screen.getByText('2 selected')).toBeInTheDocument();
  });

  it('selecting a row shows the action bar with Retry and Remove from library', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Select Heat' }));
    expect(screen.getByText('1 selected')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove from library' })).toBeInTheDocument();
  });

  it('select all merges with other pages selections instead of discarding them', async () => {
    apiMocks.library.mockImplementation((params: Record<string, string | string[]>) => Promise.resolve(
      params.page === '2'
        ? { rows: [row({ id: 3, imdb_id: 'tt3', title: 'Batman' }), row({ id: 4, imdb_id: 'tt4', title: 'Casino' })], total: 60, page: 2, per_page: 50 }
        : { rows: [row({}), row({ id: 2, imdb_id: 'tt2', title: 'Alien' })], total: 60, page: 1, per_page: 50 },
    ));
    renderIt();
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Select Heat' }));
    expect(screen.getByText('1 selected')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await screen.findByText('Batman');
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select all on this page' }));
    expect(screen.getByText('3 selected')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select all on this page' }));
    expect(screen.getByText('1 selected')).toBeInTheDocument();
  });

  it('gates the Unmirrored view on the mirror setting', async () => {
    apiMocks.libraryViews.mockResolvedValue({
      counts: { all: 2, attention: 1, wanted: 0, queue: 1, incomplete: 0, unmirrored: 0 },
      mirror_on: false,
    });
    const first = renderIt();
    const nav = await screen.findByRole('navigation', { name: 'Library views' });
    await waitFor(() => expect(within(nav).getByRole('button', { name: /Needs attention/ })).toHaveTextContent('1'));
    expect(within(nav).queryByRole('button', { name: /Unmirrored/ })).not.toBeInTheDocument();
    first.unmount();

    apiMocks.libraryViews.mockResolvedValue({
      counts: { all: 2, attention: 1, wanted: 0, queue: 1, incomplete: 0, unmirrored: 0 },
      mirror_on: true,
    });
    renderIt();
    const nav2 = await screen.findByRole('navigation', { name: 'Library views' });
    await waitFor(() => expect(within(nav2).getByRole('button', { name: /Unmirrored/ })).toBeInTheDocument());
  });
});
