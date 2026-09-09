import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { StatusCell } from './StatusCell';

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe('StatusCell', () => {
  it('shows value, label and sub, and no link when green', () => {
    wrap(<StatusCell tone="ok" label="Queue" value="0" sub="retry queue empty" href="#library?view=queue" linkLabel="Open queue" />);
    expect(screen.getByText('Queue')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getByText('retry queue empty')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders the link only when amber or red', () => {
    wrap(<StatusCell tone="warn" label="Attention" value="3" href="#library?view=attention" linkLabel="Open Library" />);
    expect(screen.getByRole('link', { name: 'Open Library' })).toHaveAttribute('href', expect.stringContaining('library?view=attention'));
  });

  it('exposes its tone for assistive tech', () => {
    wrap(<StatusCell tone="danger" label="Failures 7d" value="2" />);
    expect(screen.getByRole('group', { name: 'Failures 7d: problem' })).toBeInTheDocument();
  });
});
