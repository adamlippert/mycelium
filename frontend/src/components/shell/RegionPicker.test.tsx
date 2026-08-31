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

  // F3(a): a successful save patches the cached session in place rather than
  // invalidating it. GET /ui/api/session re-derives region from
  // auth.current_user_record(), which for the legacy single-user login never
  // carries one (auth.py:170) - a refetch there would silently re-show the
  // old region, so the picker must not depend on one to reflect a real save.
  it('patches the cached session region on success without waiting on a refetch', async () => {
    vi.mocked(api.setRegion).mockResolvedValue({ ok: true, region: 'DE' });
    const qc = renderPicker('NL');
    pickGermany();
    await waitFor(() => {
      const session = qc.getQueryData<SessionInfo>(['session']);
      expect(session?.user?.region).toBe('DE');
    });
  });

  // F3(a): for the legacy single-user login, POST /ui/api/me/region now
  // fails loudly (app.py's ui_api_me_region 409s when current_user_record()
  // has no persistable id) instead of silently no-oping, so this must
  // surface to the user via F1's toast system.
  it('toasts the failure when the save cannot persist', async () => {
    vi.mocked(api.setRegion).mockRejectedValue(
      new Error("409: Region can't be saved for the shared login."),
    );
    renderPicker('NL');
    pickGermany();
    expect(await screen.findByText('Could not save region')).toBeInTheDocument();
  });
});
