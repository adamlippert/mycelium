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
  it('ignores an explicit type="submit" and stays type="button"', () => {
    render(<Button type={'submit' as any}>Go</Button>);
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

  it('shows a value outside the option list instead of going blank', () => {
    const onChange = vi.fn();
    render(<Select label="Region" value="fr" onChange={onChange} options={OPTS} />);
    const s = screen.getByRole('combobox', { name: 'Region' }) as HTMLSelectElement;
    expect(s).toHaveValue('fr');
    expect(screen.getByText('fr (not in list)')).toBeInTheDocument();
  });

  it('does not add an out-of-list option when value is empty', () => {
    const onChange = vi.fn();
    render(<Select label="Region" value="" onChange={onChange} options={OPTS} placeholder="(first)" />);
    expect(screen.queryByText(/not in list/)).not.toBeInTheDocument();
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

  it('moves a highlight with the arrow keys and adds the highlighted candidate on Enter', async () => {
    const onChange = vi.fn();
    const wideOpts = [{ value: 'nl', label: 'nl' }, { value: 'nb', label: 'nb' }];
    render(<MultiSelect label="Languages" value={[]} onChange={onChange} options={wideOpts} />);
    const input = screen.getByRole('textbox', { name: 'Languages' });
    // 'n' matches both candidates, nl and nb.
    await userEvent.type(input, 'n');
    const nl = screen.getByRole('option', { name: 'nl' });
    const nb = screen.getByRole('option', { name: 'nb' });
    expect(nl).toHaveAttribute('aria-selected', 'false');
    await userEvent.keyboard('{ArrowDown}');
    expect(nl).toHaveAttribute('aria-selected', 'true');
    expect(input).toHaveAttribute('aria-activedescendant', nl.id);
    await userEvent.keyboard('{ArrowDown}');
    expect(nb).toHaveAttribute('aria-selected', 'true');
    expect(nl).toHaveAttribute('aria-selected', 'false');
    await userEvent.keyboard('{ArrowUp}');
    expect(nl).toHaveAttribute('aria-selected', 'true');
    await userEvent.keyboard('{Enter}');
    expect(onChange).toHaveBeenLastCalledWith(['nl']);
  });

  it('adds the first visible candidate on Enter when nothing is highlighted', async () => {
    const onChange = vi.fn();
    render(<MultiSelect label="Languages" value={['en']} onChange={onChange} options={OPTS} />);
    const input = screen.getByRole('textbox', { name: 'Languages' });
    await userEvent.type(input, 'n');
    await userEvent.keyboard('{Enter}');
    expect(onChange).toHaveBeenLastCalledWith(['en', 'nl']);
  });

  it('removes the last chip on Backspace in an empty input', async () => {
    const onChange = vi.fn();
    render(<MultiSelect label="Languages" value={['en', 'nl']} onChange={onChange} options={OPTS} />);
    const input = screen.getByRole('textbox', { name: 'Languages' });
    input.focus();
    await userEvent.keyboard('{Backspace}');
    expect(onChange).toHaveBeenLastCalledWith(['en']);
  });

  it('closes the list on Escape without removing the query', async () => {
    const onChange = vi.fn();
    render(<MultiSelect label="Languages" value={['en']} onChange={onChange} options={OPTS} />);
    const input = screen.getByRole('textbox', { name: 'Languages' });
    await userEvent.type(input, 'n');
    expect(screen.getByRole('option', { name: 'nl' })).toBeInTheDocument();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('option', { name: 'nl' })).not.toBeInTheDocument();
    expect(input).toHaveValue('n');
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
