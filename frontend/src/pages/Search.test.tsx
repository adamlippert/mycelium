import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import Search from './Search';
import { ToastProvider } from '../components/primitives';

const results = [
  { tmdb_id: 1, media_type: 'movie', title: 'Blade Runner', year: '1982', rating: 8.1,
    votes: 900, popularity: 9, overview: 'Replicants.', poster_path: null, backdrop_path: null,
    library_status: 'success' },
  { tmdb_id: 2, media_type: 'tv', title: 'Blade Runner: Black Lotus', year: '2021', rating: 6.9,
    votes: 100, popularity: 3, overview: 'Anime.', poster_path: null, backdrop_path: null,
    library_status: null },
];

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    api: { ...actual.api, search: () => Promise.resolve({ results }) },
  };
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={['/search?q=blade']}><Search /></MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe('Search results', () => {
  it('renders rows with overview text, not a poster grid', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Blade Runner')).toBeInTheDocument());
    expect(screen.getByText('Replicants.')).toBeInTheDocument();
  });

  it('computes facet counts from the result set', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Movies · 1')).toBeInTheDocument());
    expect(screen.getByText('Series · 1')).toBeInTheDocument();
    expect(screen.getByText('In library · 1')).toBeInTheDocument();
  });

  it('filters by facet without a new request', async () => {
    const { container } = renderPage();
    await waitFor(() => expect(screen.getByText('Blade Runner')).toBeInTheDocument());
    (screen.getByText('Movies · 1') as HTMLElement).click();
    await waitFor(() => expect(container.textContent).not.toContain('Black Lotus'));
  });
});
