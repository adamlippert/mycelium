import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import DetailModal from './index';
import { ToastProvider } from '../primitives';

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      details: () => Promise.resolve({
        tmdb_id: 1, media_type: 'movie', title: 'Dune', year: '2021', rating: 8.1,
        votes: 100, popularity: 10, overview: 'Sand.', poster_path: null, backdrop_path: null,
        runtime: 155, genres: ['Sci-Fi'], cast: [], recommendations: [], seasons: [],
        library_status: 'success', imdb_id: 'tt1160419',
      }),
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
});
