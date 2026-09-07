import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { Button } from './Button';
import { Select } from './Select';
import { MultiSelect } from './MultiSelect';
import { OrderedList } from './OrderedList';

const OPTS = [
  { value: 'en', label: 'en' },
  { value: 'nl', label: 'nl' },
  { value: 'de', label: 'de' },
];

describe('Button', () => {
  it('is disabled and shows the loading label while loading', () => {
    render(<Button loading loadingLabel="Testing...">Test</Button>);
    const b = screen.getByRole('button');
    expect(b).toBeDisabled();
    expect(b).toHaveTextContent('Testing...');
  });
  it('never submits a form', () => {
    render(<Button>Go</Button>);
    expect(screen.getByRole('button')).toHaveAttribute('type', 'button');
  });
});

describe('Select', () => {
  it('offers the placeholder as the empty value and reports a pick', async () => {
    const onChange = vi.fn();
    render(<Select label="Region" value="" onChange={onChange} options={OPTS} placeholder="(first)" />);
    const s = screen.getByRole('combobox', { name: 'Region' });
    expect(s).toHaveValue('');
    await userEvent.selectOptions(s, 'nl');
    expect(onChange).toHaveBeenCalledWith('nl');
  });
});

describe('MultiSelect', () => {
  it('shows chips, filters by typing, adds on click and removes on x', async () => {
    const onChange = vi.fn();
    render(<MultiSelect label="Languages" value={['en']} onChange={onChange} options={OPTS} />);
    expect(screen.getByText('en')).toBeInTheDocument();
    await userEvent.type(screen.getByRole('textbox', { name: 'Languages' }), 'n');
    expect(screen.getByRole('option', { name: 'nl' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'de' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('option', { name: 'nl' }));
    expect(onChange).toHaveBeenLastCalledWith(['en', 'nl']);
    await userEvent.click(screen.getByRole('button', { name: 'Remove en' }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });
});

describe('OrderedList', () => {
  it('moves an entry down and appends from the unused options', async () => {
    const onChange = vi.fn();
    render(<OrderedList label="Sort order" value={['en', 'nl']} onChange={onChange} options={OPTS} />);
    await userEvent.click(screen.getByRole('button', { name: 'Move en down' }));
    expect(onChange).toHaveBeenLastCalledWith(['nl', 'en']);
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Add to Sort order' }), 'de');
    expect(onChange).toHaveBeenLastCalledWith(['en', 'nl', 'de']);
    expect(screen.getByRole('button', { name: 'Move en up' })).toBeDisabled();
  });
});
