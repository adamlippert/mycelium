import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Requests from './Requests';
import { row } from './requests/fixtures';

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

  it('a view click and a filter re-query and update the hash', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Denied/ }));
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenLastCalledWith(expect.objectContaining({ view: 'denied' })));
    expect(screen.getByTestId('requests-hash').textContent).toContain('view=denied');
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
});
