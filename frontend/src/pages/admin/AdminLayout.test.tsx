import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import AdminLayout, { ADMIN_TABS } from './AdminLayout';

function renderIt(hash = '') {
  return render(
    <MemoryRouter initialEntries={[`/admin${hash}`]}>
      <AdminLayout />
    </MemoryRouter>,
  );
}

describe('AdminLayout', () => {
  it('declares the nine tabs in order', () => {
    expect(ADMIN_TABS.map((t) => t.id)).toEqual([
      'overview', 'users', 'requests', 'filter-rules', 'scrapers',
      'logs', 'maintenance', 'blacklist', 'settings',
    ]);
  });

  it('renders the strip and defaults to Overview', () => {
    renderIt();
    for (const t of ADMIN_TABS) {
      expect(screen.getByRole('tab', { name: t.label })).toBeInTheDocument();
    }
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true');
  });

  it('opens the tab named in the URL hash', () => {
    renderIt('#blacklist');
    expect(screen.getByRole('tab', { name: 'Blacklist' })).toHaveAttribute('aria-selected', 'true');
  });

  it('switches tabs on click and writes the hash', async () => {
    renderIt();
    await userEvent.click(screen.getByRole('tab', { name: 'Users' }));
    expect(screen.getByRole('tab', { name: 'Users' })).toHaveAttribute('aria-selected', 'true');
  });
});
