import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { ActivityBand, eventPill } from './ActivityBand';

const activity = {
  plays: { today: 4, week: 23, titles_today: 3, titles_week: 17 },
  requests_7d: { total: 11, succeeded: 9, failed: 2, success_rate: 81.8 },
  egress: { proxied_bytes: 210_000_000_000, estimated_bytes: 1_630_000_000_000 },
};
const events = [
  { id: 1, created_at: '2026-09-08 10:41:00', event: 'played', title: 'Severance S02E04', message: 'by anna', success: true },
  { id: 2, created_at: '2026-09-08 10:05:00', event: 'swapped', title: 'Heat (1995)', message: '1080p to 2160p', success: true },
  { id: 3, created_at: '2026-09-08 08:30:00', event: 'wanted', title: 'Dune Part Two', message: 'no cached release', success: false },
  { id: 4, created_at: '2026-09-08 07:58:00', event: 'mystery', title: 'X', message: '', success: true },
];

describe('ActivityBand', () => {
  it('renders the five tiles with the documented formats', () => {
    render(<MemoryRouter><ActivityBand activity={activity} events={events} loading={false} /></MemoryRouter>);
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('3 titles')).toBeInTheDocument();
    expect(screen.getByText('23')).toBeInTheDocument();
    expect(screen.getByText('17 titles')).toBeInTheDocument();
    expect(screen.getByText('11')).toBeInTheDocument();
    expect(screen.getByText('9 ok, 2 failed')).toBeInTheDocument();
    expect(screen.getByText('82%')).toBeInTheDocument();
    expect(screen.getByText('1.84 TB')).toBeInTheDocument();
    expect(screen.getByText('0.21 TB proxied, 1.63 TB estimated')).toBeInTheDocument();
  });

  it('renders the feed with pills by event family and a link to the logs', () => {
    render(<MemoryRouter><ActivityBand activity={activity} events={events} loading={false} /></MemoryRouter>);
    expect(screen.getByText('Severance S02E04')).toBeInTheDocument();
    expect(screen.getByText('play')).toBeInTheDocument();
    expect(screen.getByText('swap')).toBeInTheDocument();
    expect(screen.getByText('wanted')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'All activity' })).toHaveAttribute('href', expect.stringContaining('logs'));
  });

  it('maps events to pills and leaves unknown events without one', () => {
    expect(eventPill('played')).toEqual({ label: 'play', tone: 'ok' });
    expect(eventPill('upgraded')).toEqual({ label: 'upgrade', tone: 'neutral' });
    expect(eventPill('failed')).toEqual({ label: 'failed', tone: 'danger' });
    expect(eventPill('mystery')).toBeNull();
  });
});
