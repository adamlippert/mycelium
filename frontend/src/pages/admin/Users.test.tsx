import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Users from './Users';

const apiMocks = vi.hoisted(() => ({ updateUser: vi.fn() }));

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      users: () => Promise.resolve({ users: [
        { id: 1, username: 'adam', role: 'admin', quota_monthly: 0, enabled: true, auto_approve: true, last_login: null, created_at: '2026-01-01' },
        { id: 2, username: 'guest', role: 'user', quota_monthly: 25, enabled: true, auto_approve: false, last_login: null, created_at: '2026-01-01' },
      ] }),
      session: () => Promise.resolve({ authenticated: true, user: { id: 1, username: 'adam', role: 'admin' } }),
      updateUser: apiMocks.updateUser,
    },
  };
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Users /></QueryClientProvider>);
}

describe('Users tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.updateUser.mockResolvedValue({ ok: true });
  });

  it('lists every user with role and an editable monthly cap', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('adam')).toBeInTheDocument();
      expect(screen.getByText('guest')).toBeInTheDocument();
    });
    const capOfAdam = screen.getByRole('spinbutton', { name: 'Monthly cap for adam' });
    expect(capOfAdam).toHaveValue(null);
    expect(capOfAdam).toHaveAttribute('placeholder', 'unlimited');
    expect(screen.getByRole('spinbutton', { name: 'Monthly cap for guest' })).toHaveValue(25);
    expect(screen.getByText(/blank means no cap/i)).toBeInTheDocument();
  });

  it('saves a new cap on Enter and saves 0 when the field is cleared', async () => {
    renderIt();
    const cap = await screen.findByRole('spinbutton', { name: 'Monthly cap for guest' });
    await userEvent.clear(cap);
    await userEvent.type(cap, '10{Enter}');
    await waitFor(() => expect(apiMocks.updateUser).toHaveBeenCalledWith(2, { quota_monthly: 10 }));
    expect(await screen.findByText('saved')).toBeInTheDocument();
    await userEvent.clear(cap);
    await userEvent.tab();
    await waitFor(() => expect(apiMocks.updateUser).toHaveBeenLastCalledWith(2, { quota_monthly: 0 }));
  });

  it('does not save when the cap is unchanged on blur', async () => {
    renderIt();
    const cap = await screen.findByRole('spinbutton', { name: 'Monthly cap for guest' });
    await userEvent.click(cap);
    await userEvent.tab();
    expect(apiMocks.updateUser).not.toHaveBeenCalled();
  });

  it('offers the create form', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByRole('button', { name: /create/i })).toBeInTheDocument());
  });
});
