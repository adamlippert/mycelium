import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import Users from './Users';

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
    },
  };
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Users /></QueryClientProvider>);
}

describe('Users tab', () => {
  it('lists every user with role and quota', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('adam')).toBeInTheDocument();
      expect(screen.getByText('guest')).toBeInTheDocument();
      expect(screen.getByText('unlimited')).toBeInTheDocument();
      expect(screen.getByText('25')).toBeInTheDocument();
    });
  });

  it('offers the create form', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByRole('button', { name: /create/i })).toBeInTheDocument());
  });
});
