import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { TorboxCard } from './TorboxCard';

const usage = { usage: { torrent_count: 128, total_bytes: 3_400_000_000_000, total_gb: 3400, states: { completed: 121, downloading: 1, stalled: 6 } }, plan: 'Pro' };

describe('TorboxCard', () => {
  it('merges budget, library and streaming into one card', () => {
    render(<TorboxCard adds={{ uncached: 3, cached: 41, limit: 60, resets_in_sec: 2520 }} byReason={{ 'catbox-search': 2, processor: 1 }}
      usage={usage} streamFront recentStreams={2} last429At={null} idleMinutes={90} />);
    expect(screen.getByText('3 / 60')).toBeInTheDocument();
    expect(screen.getByText('41 cached adds this hour, not limited by TorBox. Resets in 42 min.')).toBeInTheDocument();
    expect(screen.getByText('catbox-search')).toBeInTheDocument();
    expect(screen.getByText('128')).toBeInTheDocument();
    expect(screen.getByText('Pro')).toBeInTheDocument();
    expect(screen.getByText('Stalled')).toBeInTheDocument();
    expect(screen.getByText('Go')).toBeInTheDocument();
    expect(screen.getByText('after 90 min')).toBeInTheDocument();
    expect(screen.getByText('none since start')).toBeInTheDocument();
  });

  it('shows the last 429 as a relative time and the Flask front when the Go front is off', () => {
    const t = new Date(Date.now() - 3 * 86400 * 1000).toISOString().replace(/\.\d+Z$/, 'Z');
    render(<TorboxCard adds={undefined} byReason={undefined} usage={undefined} streamFront={false} recentStreams={0} last429At={t} idleMinutes={null} />);
    expect(screen.getByText('3 d ago')).toBeInTheDocument();
    expect(screen.getByText('Flask')).toBeInTheDocument();
    expect(screen.getAllByText('unavailable').length).toBeGreaterThanOrEqual(1);
  });
});
