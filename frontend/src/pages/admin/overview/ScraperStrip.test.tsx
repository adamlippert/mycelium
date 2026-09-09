import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ScraperStrip } from './ScraperStrip';

describe('ScraperStrip', () => {
  it('renders one entry per scraper with latency, state and dimmed disabled ones', () => {
    render(<ScraperStrip scrapers={[
      { name: 'zilean', state: 'ok', latency_ms: 45 },
      { name: 'mediafusion', state: 'slow', latency_ms: 1840 },
      { name: 'comet', state: 'down', latency_ms: null },
      { name: 'debridio', state: 'disabled', latency_ms: null },
    ]} />);
    expect(screen.getByText('45 ms')).toBeInTheDocument();
    expect(screen.getByText('1.8 s')).toBeInTheDocument();
    expect(screen.getByText('down')).toBeInTheDocument();
    expect(screen.getByText('disabled')).toBeInTheDocument();
    expect(screen.getByLabelText('comet: down')).toBeInTheDocument();
    expect(screen.getByLabelText('debridio: disabled')).toHaveClass('opacity-50');
  });
});
