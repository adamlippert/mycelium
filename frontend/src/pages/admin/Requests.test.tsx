import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import Requests from './Requests';

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
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
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/admin']}>
        <Requests />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Requests tab', () => {
  it('renders pending approvals with a Failed pill and approve/deny buttons', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('Pending Movie')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /deny/i })).toBeInTheDocument();
    });
  });

  it('links to the Library tab', () => {
    renderIt();
    expect(screen.getByRole('link', { name: /open the library tab/i })).toBeInTheDocument();
  });
});
