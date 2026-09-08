import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Requests from './Requests';
import { row } from './requests/fixtures';

function HashProbe() {
  const location = useLocation();
  return <div data-testid="hash-probe">{location.hash}</div>;
}

const apiMocks = vi.hoisted(() => ({
  adminRequests: vi.fn(), adminRequestViews: vi.fn(), users: vi.fn(), adminQuotas: vi.fn(),
  approveRequest: vi.fn(), denyRequest: vi.fn(), reopenRequest: vi.fn(),
  autoApproveGenreRules: vi.fn(), genres: vi.fn(), libraryDetail: vi.fn(),
}));
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

function renderIt(hash = '#requests') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[`/admin${hash}`]}>
      <QueryClientProvider client={qc}><Requests /></QueryClientProvider>
      <HashProbe />
    </MemoryRouter>,
  );
}

describe('Requests tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.adminRequestViews.mockResolvedValue({ counts: { pending: 2, approved: 1, denied: 1, all: 4 } });
    apiMocks.users.mockResolvedValue({ users: [{ id: 3, username: 'adam' }, { id: 4, username: 'bea' }] });
    apiMocks.adminQuotas.mockResolvedValue({ rows: [] });
    apiMocks.autoApproveGenreRules.mockResolvedValue({ rules: [] });
    apiMocks.genres.mockResolvedValue({ genres: [{ id: 1, name: 'Action' }] });
    apiMocks.adminRequests.mockResolvedValue({
      rows: [row({}), row({ id: 2, imdb_id: 'tt2', title: 'Loki', media_type: 'series', status: 'approved', username: 'adam',
        reviewer: 'root', reviewed_at: '2026-09-02 10:00:00', library_status: 'success' })],
      total: 2, page: 1, per_page: 50,
    });
  });

  it('renders views with counts and the table, defaulting to Pending', async () => {
    renderIt();
    const nav = await screen.findByRole('navigation', { name: 'Request views' });
    await waitFor(() => expect(within(nav).getByRole('button', { name: /Pending/ })).toHaveTextContent('2'));
    expect(await screen.findByText('Heat')).toBeInTheDocument();
    const loki = screen.getByText('Loki').closest('tr')!;
    expect(within(loki).getByText('root')).toBeInTheDocument();
    expect(within(loki).getByText('In library')).toBeInTheDocument();
    expect(within(screen.getByText('Heat').closest('tr')!).getByText('not in library')).toBeInTheDocument();
    expect(apiMocks.adminRequests).toHaveBeenCalledWith(expect.objectContaining({ view: 'pending', page: '1' }));
  });

  it('hides the type icon from screen readers and gives it a text alternative', async () => {
    renderIt();
    const heatRow = (await screen.findByText('Heat')).closest('tr')!;
    const heatIcon = heatRow.querySelector('[aria-hidden="true"]')!;
    expect(heatIcon).toHaveTextContent('\u{1F3AC}');
    expect(within(heatRow).getByText('movie', { selector: '.sr-only' })).toBeInTheDocument();

    const lokiRow = screen.getByText('Loki').closest('tr')!;
    const lokiIcon = lokiRow.querySelector('[aria-hidden="true"]')!;
    expect(lokiIcon).toHaveTextContent('\u{1F4FA}');
    expect(within(lokiRow).getByText('series', { selector: '.sr-only' })).toBeInTheDocument();
  });

  it('a view click and a filter re-query and update the hash', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Denied/ }));
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenLastCalledWith(expect.objectContaining({ view: 'denied' })));
    expect(screen.getByTestId('hash-probe')).toHaveTextContent('view=denied');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'User' }), '4');
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenLastCalledWith(expect.objectContaining({ user: '4', page: '1' })));
  });

  it('restores from the hash, pages and sorts', async () => {
    apiMocks.adminRequests.mockResolvedValue({ rows: [row({})], total: 120, page: 2, per_page: 50 });
    renderIt('#requests?view=all&page=2');
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenCalledWith(expect.objectContaining({ view: 'all', page: '2' })));
    expect(await screen.findByText(/51 to 100 of 120/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenLastCalledWith(expect.objectContaining({ page: '3' })));
    await userEvent.click(screen.getByRole('button', { name: 'Sort by user' }));
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'user', order: 'asc' })));
  });

  it('shows the empty state for the view', async () => {
    apiMocks.adminRequests.mockResolvedValue({ rows: [], total: 0, page: 1, per_page: 50 });
    renderIt();
    expect(await screen.findByText('No requests waiting for review')).toBeInTheDocument();
  });

  it('shows the quotas card with a paused user and the auto-approve card', async () => {
    apiMocks.adminQuotas.mockResolvedValue({
      rows: [{ user_id: 3, username: 'adam', used: 2, limit: 2, remaining: 0, unlimited: false,
        resets_at: '2026-10-01T00:00:00Z', auto_approve: true, paused: true, enabled: true }],
    });
    renderIt();
    expect(await screen.findByText('auto-approve paused')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Auto-approve' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run now' })).toBeInTheDocument();
  });

  it('clicking a title opens the drawer and updates the hash', async () => {
    apiMocks.libraryDetail.mockResolvedValue({
      request: { id: 1, imdb_id: 'tt1', title: 'Heat', media_type: 'movie', status: 'failed', error: 'no release', quality: null, source: null,
        info_hash: null, seasons: null, created_at: '2026-09-01 10:00:00', updated_at: '2026-09-02 10:00:00', tmdb_id: 949, arr_mirrored_at: null },
      items: [], playability: [], episodes: null, monitored: null, retry: null, wanted_movie: null,
      user_requests: [], seerr_request_id: null, override: null, hashes: [], activity: [], arr: { mirrored_at: null },
    });
    renderIt();
    await userEvent.click(await screen.findByText('Heat'));
    expect(await screen.findByRole('dialog', { name: 'Title details' })).toBeInTheDocument();
    expect(screen.getByTestId('hash-probe')).toHaveTextContent('open=tt1');
  });

  it('opening a pending row with no library row yet shows the friendly not-in-library message', async () => {
    apiMocks.libraryDetail.mockRejectedValue(new Error('404: not found'));
    renderIt();
    await userEvent.click(await screen.findByText('Heat'));
    expect(await screen.findByRole('heading', { name: 'Not in the library' })).toBeInTheDocument();
    expect(await screen.findByText('This title is not in the library yet, so there is nothing to act on here.')).toBeInTheDocument();
  });

  it('adopts a lower effective page from the response and reflects it in the hash', async () => {
    apiMocks.adminRequests.mockResolvedValue({ rows: [row({})], total: 3, page: 2, per_page: 50 });
    renderIt('#requests?view=all&page=99');
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenCalledWith(expect.objectContaining({ page: '99' })));
    await waitFor(() => expect(screen.getByTestId('hash-probe')).toHaveTextContent('page=2'));
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenLastCalledWith(expect.objectContaining({ page: '2' })));
  });
});
