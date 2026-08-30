import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Pill, StatusDot, Card, PILL_STATES } from './index';

describe('Pill', () => {
  it('renders its label', () => {
    render(<Pill state="ready">Ready</Pill>);
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('drives colour from the state token, not a hardcoded hex', () => {
    const { container } = render(<Pill state="failed">Failed</Pill>);
    const el = container.firstElementChild as HTMLElement;
    expect(el.style.background).toContain('--pill-failed-bg');
    expect(el.style.color).toContain('--pill-failed-fg');
  });

  it('supports all five states without falling back', () => {
    for (const state of PILL_STATES) {
      const { container } = render(<Pill state={state}>x</Pill>);
      const el = container.firstElementChild as HTMLElement;
      expect(el.style.background, `${state} has no background`).toContain(`--pill-${state}-bg`);
    }
  });
});

describe('StatusDot', () => {
  it('tints and glows in the same tone', () => {
    const { container } = render(<StatusDot tone="warn" />);
    const el = container.firstElementChild as HTMLElement;
    expect(el.style.background).toContain('--dot-warn');
    expect(el.style.boxShadow).toContain('--dot-warn');
  });
});

describe('Card', () => {
  it('renders children inside a bordered surface', () => {
    render(<Card>contents</Card>);
    const el = screen.getByText('contents');
    expect(el).toHaveClass('bg-card', 'border', 'border-border');
  });

  it('merges an extra className rather than replacing its own', () => {
    render(<Card className="mb-4">contents</Card>);
    expect(screen.getByText('contents')).toHaveClass('bg-card', 'mb-4');
  });
});
