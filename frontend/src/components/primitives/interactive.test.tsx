import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { Chip, Toggle, StatTile, DataTable } from './index';

describe('Chip', () => {
  it('calls onClick when pressed', async () => {
    const onClick = vi.fn();
    render(<Chip label="Movies" onClick={onClick} />);
    await userEvent.click(screen.getByRole('button', { name: 'Movies' }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('marks the selected chip for assistive tech, not just visually', () => {
    render(<Chip label="Movies" selected onClick={() => {}} />);
    expect(screen.getByRole('button', { name: 'Movies' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows a remove control only when onRemove is given', async () => {
    const onRemove = vi.fn();
    const { rerender } = render(<Chip label="1080p" />);
    expect(screen.queryByRole('button', { name: /remove 1080p/i })).toBeNull();

    rerender(<Chip label="1080p" onRemove={onRemove} />);
    await userEvent.click(screen.getByRole('button', { name: /remove 1080p/i }));
    expect(onRemove).toHaveBeenCalledOnce();
  });
});

describe('Toggle', () => {
  it('reports its state through the checkbox role', () => {
    render(<Toggle checked label="Enabled" onChange={() => {}} />);
    expect(screen.getByRole('checkbox', { name: 'Enabled' })).toBeChecked();
  });

  it('emits the inverted value when clicked', async () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} label="Enabled" onChange={onChange} />);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Enabled' }));
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe('StatTile', () => {
  it('renders value, label and sub-line', () => {
    render(<StatTile value="1,284" label="Titles" sub="+18 this week" />);
    expect(screen.getByText('1,284')).toBeInTheDocument();
    expect(screen.getByText('Titles')).toBeInTheDocument();
    expect(screen.getByText('+18 this week')).toBeInTheDocument();
  });

  it('omits the sub-line entirely when there is none', () => {
    const { container } = render(<StatTile value="6" label="Failures" />);
    expect(container.textContent).toBe('6Failures');
  });
});

describe('DataTable', () => {
  type Row = { title: string; year: number };
  const columns = [
    { key: 'title', header: 'Title', render: (r: Row) => r.title },
    { key: 'year', header: 'Year', render: (r: Row) => String(r.year), align: 'right' as const },
  ];

  it('renders a header cell per column and a row per item', () => {
    render(<DataTable columns={columns} rows={[{ title: 'Dune', year: 2021 }]} empty="Nothing" />);
    expect(screen.getAllByRole('columnheader').map((c) => c.textContent)).toEqual(['Title', 'Year']);
    expect(screen.getByText('Dune')).toBeInTheDocument();
    expect(screen.getByText('2021')).toBeInTheDocument();
  });

  it('shows the empty message instead of a bare table', () => {
    render(<DataTable columns={columns} rows={[]} empty="No repair history yet" />);
    expect(screen.getByText('No repair history yet')).toBeInTheDocument();
  });
});
