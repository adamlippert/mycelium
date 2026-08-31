import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Blacklist from './Blacklist';

const apiMocks = vi.hoisted(() => ({
  blacklist: vi.fn(),
  blacklistClear: vi.fn(),
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
  return render(<QueryClientProvider client={qc}><Blacklist /></QueryClientProvider>);
}

describe('Blacklist tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.blacklist.mockResolvedValue({
      items: [
        {
          info_hash: 'abcdef0123456789abcdef0123456789abcdef01',
          fail_count: 3,
          last_error: 'ADD_FAILED',
          last_attempt: '2026-08-20 10:00:00',
        },
      ],
    });
    apiMocks.blacklistClear.mockResolvedValue(undefined);
  });

  it('renders blacklisted hash rows with a Clear button per row', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText(/abcdef0123456789/)).toBeInTheDocument();
      expect(screen.getByText('3')).toBeInTheDocument();
      expect(screen.getByText('ADD_FAILED')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /clear/i })).toBeInTheDocument();
    });
  });

  it('clears a hash after confirming', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderIt();
    await waitFor(() => expect(screen.getByRole('button', { name: /clear/i })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /clear/i }));
    expect(apiMocks.blacklistClear).toHaveBeenCalledWith('abcdef0123456789abcdef0123456789abcdef01');
  });

  it('does not clear when the confirm dialog is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderIt();
    await waitFor(() => expect(screen.getByRole('button', { name: /clear/i })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: /clear/i }));
    expect(apiMocks.blacklistClear).not.toHaveBeenCalled();
  });
});
