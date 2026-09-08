import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { QuotasCard } from './QuotasCard';

describe('QuotasCard', () => {
  it('lists users with used, cap, remaining and reset date, marking the ones at the cap', () => {
    render(<MemoryRouter initialEntries={['/admin']}><QuotasCard rows={[
      { user_id: 3, username: 'adam', used: 3, limit: 2, remaining: 0, unlimited: false, resets_at: '2026-10-01T00:00:00Z', auto_approve: true, paused: true, enabled: true },
      { user_id: 4, username: 'bea', used: 5, limit: 0, remaining: null, unlimited: true, resets_at: '2026-10-01T00:00:00Z', auto_approve: false, paused: false, enabled: true },
      { user_id: 5, username: 'carl', used: 1, limit: 10, remaining: 9, unlimited: false, resets_at: '2026-10-01T00:00:00Z', auto_approve: false, paused: false, enabled: true },
    ]} /></MemoryRouter>);
    const adam = screen.getByText('adam').closest('li')!;
    expect(within(adam).getByText('3 of 2')).toHaveClass('text-danger');
    expect(within(adam).getByText('auto-approve paused')).toBeInTheDocument();
    expect(within(screen.getByText('bea').closest('li')!).getByText('unlimited')).toBeInTheDocument();
    expect(within(screen.getByText('carl').closest('li')!).getByText('9 left')).toBeInTheDocument();
    expect(screen.getAllByText(/resets 2026-10-01/)).toHaveLength(2);
    expect(screen.getByRole('link', { name: 'Edit quotas in Users' })).toHaveAttribute('href', '/admin#users');
    expect(screen.queryByText('disabled')).not.toBeInTheDocument();
  });
  it('says so when no user has a cap', () => {
    render(<MemoryRouter initialEntries={['/admin']}><QuotasCard rows={[]} /></MemoryRouter>);
    expect(screen.getByText('No users to show.')).toBeInTheDocument();
  });
  it('marks a disabled user without hiding their usage', () => {
    render(<MemoryRouter initialEntries={['/admin']}><QuotasCard rows={[
      { user_id: 6, username: 'dana', used: 1, limit: 5, remaining: 4, unlimited: false, resets_at: '2026-10-01T00:00:00Z', auto_approve: false, paused: false, enabled: false },
    ]} /></MemoryRouter>);
    const dana = screen.getByText('dana').closest('li')!;
    expect(within(dana).getByText('disabled')).toBeInTheDocument();
    expect(within(dana).getByText('1 of 5')).toBeInTheDocument();
  });
});
