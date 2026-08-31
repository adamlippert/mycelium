import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Scrapers from './Scrapers';

const apiMocks = vi.hoisted(() => ({
  scraperHealth: vi.fn(),
  zileanStatus: vi.fn(),
  zileanSync: vi.fn(),
  zileanImport: vi.fn(),
}));

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: { ...actual.api, ...apiMocks },
  };
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Scrapers /></QueryClientProvider>);
}

describe('Scrapers tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.scraperHealth.mockResolvedValue({
      scrapers: [
        { name: 'torrentio', latency_ms: 212, state: 'ok', samples: 40 },
        { name: 'zilean', latency_ms: 1400, state: 'slow', samples: 12 },
        { name: 'debridio', latency_ms: null, state: 'down', samples: 0 },
      ],
    });
    apiMocks.zileanStatus.mockResolvedValue({
      mode: 'native',
      total_hashes: 123456,
      last_synced_at: '2026-08-20 10:00:00',
      last_status: 'ok',
      last_new_hashes: 10,
      syncing: false,
      importing: false,
    });
    apiMocks.zileanSync.mockResolvedValue({ ok: true, started: true });
    apiMocks.zileanImport.mockResolvedValue({ ok: true, started: true });
  });

  it('renders three mocked scrapers with formatted latencies', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('torrentio')).toBeInTheDocument();
      expect(screen.getByText('212 ms')).toBeInTheDocument();
      expect(screen.getByText('zilean')).toBeInTheDocument();
      expect(screen.getByText('1.4 s')).toBeInTheDocument();
      expect(screen.getByText('debridio')).toBeInTheDocument();
    });
  });

  it('shows the failed pill for the down scraper and "-" for its null latency', async () => {
    renderIt();
    await waitFor(() => {
      const row = screen.getByText('debridio').closest('tr');
      expect(row).not.toBeNull();
      expect(row!.textContent).toContain('-');
      expect(row!.textContent).toMatch(/failed/i);
    });
  });

  it('renders the Zilean panel with status and triggers sync', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText(/123456/)).toBeInTheDocument();
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await userEvent.click(screen.getByRole('button', { name: /sync now/i }));
    expect(apiMocks.zileanSync).toHaveBeenCalled();
  });

  it('triggers Zilean import from Postgres', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByRole('button', { name: /import from postgres/i })).toBeInTheDocument());
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await userEvent.click(screen.getByRole('button', { name: /import from postgres/i }));
    expect(apiMocks.zileanImport).toHaveBeenCalled();
  });
});
