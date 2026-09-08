import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import DetailModal from './index';
import { ToastProvider } from '../primitives';

const apiMocks = vi.hoisted(() => ({ details: vi.fn(), addToLibrary: vi.fn() }));

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      details: apiMocks.details,
      addToLibrary: apiMocks.addToLibrary,
      watchlist: () => Promise.resolve({ items: [] }),
      session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin' } }),
    },
  };
});

function renderModal() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <DetailModal tmdbId={1} mediaType="movie" onClose={() => {}} onSelectItem={() => {}} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe('DetailModal after the split', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.details.mockResolvedValue({
      tmdb_id: 1, media_type: 'movie', title: 'Dune', year: '2021', rating: 8.1,
      votes: 100, popularity: 10, overview: 'Sand.', poster_path: null, backdrop_path: null,
      runtime: 155, genres: ['Sci-Fi'], cast: [], recommendations: [], seasons: [],
      library_status: 'success', imdb_id: 'tt1160419',
    });
  });

  it('renders title, overview and metadata from the details query', async () => {
    renderModal();
    await waitFor(() => expect(screen.getByText('Dune')).toBeInTheDocument());
    expect(screen.getByText('Sand.')).toBeInTheDocument();
  });

  it('renders nothing at all when closed', () => {
    const qc = new QueryClient();
    const { container } = render(
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <MemoryRouter>
            <DetailModal tmdbId={null} mediaType={null} onClose={() => {}} onSelectItem={() => {}} />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(container.innerHTML).toBe('');
  });

  it('shows a quota message when the add request is rejected for quota', async () => {
    apiMocks.details.mockResolvedValue({
      tmdb_id: 1, media_type: 'movie', title: 'Dune', year: '2021', rating: 8.1,
      votes: 100, popularity: 10, overview: 'Sand.', poster_path: null, backdrop_path: null,
      runtime: 155, genres: ['Sci-Fi'], cast: [], recommendations: [], seasons: [],
      library_status: null, imdb_id: 'tt1160419',
    });
    apiMocks.addToLibrary.mockRejectedValue(new Error('409: quota reached'));
    renderModal();
    await userEvent.click(await screen.findByRole('button', { name: '+ Add to library' }));
    expect(await screen.findByText('Monthly quota reached')).toBeInTheDocument();
  });
});
