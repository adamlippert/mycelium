import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { RegionPicker } from './RegionPicker';
import { ToastProvider } from '../primitives';
import { api } from '../../api';
import type { SessionInfo } from '../../types';

vi.mock('../../api', () => ({
  api: {
    setRegion: vi.fn(),
  },
}));

function renderPicker(region: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData<SessionInfo>(['session'], {
    authenticated: true,
    user: { id: 1, username: 'adam', role: 'admin', auto_approve: true, region },
  });
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <RegionPicker region={region} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return qc;
}

function pickGermany() {
  fireEvent.click(screen.getByTitle('Netherlands'));
  fireEvent.click(screen.getByText('Germany'));
}

describe('RegionPicker', () => {
  beforeEach(() => {
    vi.mocked(api.setRegion).mockReset();
  });

  it('posts the picked region code (existing behavior)', async () => {
    vi.mocked(api.setRegion).mockResolvedValue({ ok: true, region: 'DE' });
    renderPicker('NL');
    pickGermany();
    await waitFor(() => expect(api.setRegion).toHaveBeenCalledWith('DE'));
  });

  // F3 round 1: a successful save patches the cached session immediately
  // instead of waiting on a session refetch to land - both login types
  // genuinely persist now (real users via the users-table row, the legacy
  // single-user login via the LEGACY_USER_REGION runtime setting), so this
  // is purely about not making the picker wait on a round-trip.
  it('patches the cached session region on success without waiting on a refetch', async () => {
    vi.mocked(api.setRegion).mockResolvedValue({ ok: true, region: 'DE' });
    const qc = renderPicker('NL');
    pickGermany();
    await waitFor(() => {
      const session = qc.getQueryData<SessionInfo>(['session']);
      expect(session?.user?.region).toBe('DE');
    });
  });

  // The error-toast branch (F1's toast system) still covers genuine
  // failures - a network error, a 5xx, an expired session - even though the
  // legacy single-user login no longer 409s here (round 1 fix: it persists
  // to LEGACY_USER_REGION instead of failing).
  it('toasts the failure on a genuine save error', async () => {
    vi.mocked(api.setRegion).mockRejectedValue(new Error('500: internal error'));
    renderPicker('NL');
    pickGermany();
    expect(await screen.findByText('Could not save region')).toBeInTheDocument();
  });
});
