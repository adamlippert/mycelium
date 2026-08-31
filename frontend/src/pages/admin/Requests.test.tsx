import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import Requests from './Requests';

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      requestsAll: () => Promise.resolve({
        items: [
          { id: 1, title: 'Good Movie', imdb_id: 'tt0000001', media_type: 'movie', status: 'success', created_at: '2026-08-01 10:00:00' },
          { id: 2, title: 'Bad Movie', imdb_id: 'tt0000002', media_type: 'movie', status: 'failed', created_at: '2026-08-02 11:00:00' },
        ],
      }),
      userRequests: () => Promise.resolve({
        items: [
          { id: 10, user_id: 1, username: 'guest', imdb_id: 'tt0000003', tmdb_id: null, media_type: 'movie', title: 'Pending Movie', status: 'pending', reviewed_at: null, note: null, created_at: '2026-08-03 12:00:00' },
        ],
      }),
      autoApproveGenreRules: () => Promise.resolve({ rules: [] }),
      genres: () => Promise.resolve({ genres: [{ id: 1, name: 'Action' }] }),
    },
  };
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Requests /></QueryClientProvider>);
}

describe('Requests tab', () => {
  it('renders pending approvals and all requests, with a Failed pill and approve/deny buttons', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('Pending Movie')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /deny/i })).toBeInTheDocument();
      expect(screen.getByText('Good Movie')).toBeInTheDocument();
      expect(screen.getByText('Bad Movie')).toBeInTheDocument();
      expect(screen.getByText('Failed')).toBeInTheDocument();
    });
  });

  it('hides non-matching rows when searching', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByText('Good Movie')).toBeInTheDocument());
    const search = screen.getByPlaceholderText(/search/i);
    await userEvent.type(search, 'Good');
    await waitFor(() => {
      expect(screen.getByText('Good Movie')).toBeInTheDocument();
      expect(screen.queryByText('Bad Movie')).not.toBeInTheDocument();
    });
  });
});
