import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Logs, { LOGS_POLL_MS } from './Logs';

const apiMocks = vi.hoisted(() => ({
  adminLogs: vi.fn(),
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
  return render(<QueryClientProvider client={qc}><Logs /></QueryClientProvider>);
}

const ALL_LINES = [
  { time: '10:00:01', level: 'INFO', name: 'processor', msg: 'scan started' },
  { time: '10:00:02', level: 'WARNING', name: 'torbox', msg: 'rate limited' },
  { time: '10:00:03', level: 'ERROR', name: 'catbox', msg: 'materialize failed' },
];

describe('Logs tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.adminLogs.mockImplementation((_limit?: number, level?: string) => {
      if (!level) return Promise.resolve({ lines: ALL_LINES });
      return Promise.resolve({ lines: ALL_LINES.filter((l) => l.level === level) });
    });
  });

  it('exports a 5s poll interval constant', () => {
    expect(LOGS_POLL_MS).toBe(5000);
  });

  it('renders mocked log lines as time level [name] msg', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText(/scan started/)).toBeInTheDocument();
      expect(screen.getByText(/rate limited/)).toBeInTheDocument();
      expect(screen.getByText(/materialize failed/)).toBeInTheDocument();
    });
  });

  it('hides INFO lines when the ERROR filter chip is selected', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByText(/scan started/)).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /^ERROR$/i }));
    await waitFor(() => {
      expect(screen.queryByText(/scan started/)).not.toBeInTheDocument();
      expect(screen.getByText(/materialize failed/)).toBeInTheDocument();
    });
  });
});
