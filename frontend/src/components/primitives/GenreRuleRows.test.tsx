import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { GenreRuleRows } from './GenreRuleRows';
import type { GenreRule } from '../../api';

function makeRule(overrides: Partial<GenreRule> = {}): GenreRule {
  return {
    media_type: 'movie',
    genre_id: 1,
    genre_name: 'Action',
    year_from: null,
    year_to: null,
    enabled: false,
    ...overrides,
  };
}

describe('GenreRuleRows', () => {
  it('renders one row per rule, reflecting its enabled state via the Toggle primitive', () => {
    render(
      <GenreRuleRows
        rules={[makeRule({ enabled: true })]}
        movieGenres={[{ id: 1, name: 'Action' }]}
        tvGenres={[]}
        onUpdate={() => {}}
        onRemove={() => {}}
      />,
    );
    expect(screen.getByRole('checkbox', { name: /action/i })).toBeChecked();
    expect(screen.getByRole('option', { name: 'Action' })).toBeInTheDocument();
  });

  it('fires onUpdate with the flipped enabled flag when the toggle is clicked', async () => {
    const onUpdate = vi.fn();
    render(
      <GenreRuleRows
        rules={[makeRule({ enabled: false })]}
        movieGenres={[{ id: 1, name: 'Action' }]}
        tvGenres={[]}
        onUpdate={onUpdate}
        onRemove={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('checkbox', { name: /action/i }));
    expect(onUpdate).toHaveBeenCalledWith(0, { enabled: true });
  });

  it('fires onRemove with the row index when Remove is clicked', async () => {
    const onRemove = vi.fn();
    render(
      <GenreRuleRows
        rules={[makeRule()]}
        movieGenres={[{ id: 1, name: 'Action' }]}
        tvGenres={[]}
        onUpdate={() => {}}
        onRemove={onRemove}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /remove/i }));
    expect(onRemove).toHaveBeenCalledWith(0);
  });

  it('fires onUpdate with the year as a number when a year field changes', async () => {
    const onUpdate = vi.fn();
    render(
      <GenreRuleRows
        rules={[makeRule()]}
        movieGenres={[{ id: 1, name: 'Action' }]}
        tvGenres={[]}
        onUpdate={onUpdate}
        onRemove={() => {}}
      />,
    );
    await userEvent.type(screen.getByPlaceholderText('From year'), '2');
    expect(onUpdate).toHaveBeenLastCalledWith(0, { year_from: 2 });
  });
});
