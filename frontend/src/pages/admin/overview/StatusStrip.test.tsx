import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { StatusStrip } from './StatusStrip';
import type { HealthService, OverviewPayload } from '../../../api';

const status: OverviewPayload['status'] = {
  scrapers: [
    { name: 'zilean', state: 'ok', latency_ms: 45 },
    { name: 'comet', state: 'down', latency_ms: null },
    { name: 'debridio', state: 'disabled', latency_ms: null },
  ],
  torbox_adds: { uncached: 3, cached: 41, limit: 60, resets_in_sec: 2520 },
  failures_7d: 2,
  queue: { retry: 0, wanted: 7 },
  attention: 3,
  approvals: { pending: 2, oldest_age_sec: 100_800 },
};
const services: HealthService[] = [
  { name: 'TorBox', status: 'ok' }, { name: 'Jellyfin', status: 'ok' }, { name: 'Zilean', status: 'disabled' },
];

function renderIt(s = status, svc = services) {
  return render(<MemoryRouter><StatusStrip status={s} services={svc} loading={false} error={false} /></MemoryRouter>);
}

describe('StatusStrip', () => {
  it('renders the seven cells with the documented tones and links', () => {
    renderIt();
    expect(screen.getByRole('group', { name: 'Services: ok' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Scrapers: warning' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Scrapers' })).toHaveAttribute('href', expect.stringContaining('scrapers'));
    expect(screen.getByRole('group', { name: 'TorBox adds: ok' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Failures 7d: problem' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open failures' })).toHaveAttribute('href', expect.stringContaining('library?view=attention'));
    expect(screen.getByRole('group', { name: 'Queue: ok' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Library' })).toHaveAttribute('href', expect.stringContaining('library?view=attention'));
    expect(screen.getByRole('link', { name: 'Review requests' })).toHaveAttribute('href', expect.stringContaining('requests'));
    expect(screen.getByText('3 / 60')).toBeInTheDocument();
    expect(screen.getByText('oldest 1 d 4 h')).toBeInTheDocument();
  });

  it('counts only enabled services and marks a down service red', () => {
    renderIt(status, [{ name: 'TorBox', status: 'ok' }, { name: 'Jellyfin', status: 'down', note: 'HTTP 502' }]);
    const servicesCell = screen.getByRole('group', { name: 'Services: problem' });
    expect(servicesCell).toBeInTheDocument();
    expect(within(servicesCell).getByText('1/2')).toBeInTheDocument();
    expect(screen.getByText('Jellyfin down')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Settings' })).toBeInTheDocument();
  });

  it('turns TorBox adds amber from 45 uncached and queue amber with retries', () => {
    renderIt({ ...status, torbox_adds: { ...status.torbox_adds, uncached: 45 }, queue: { retry: 2, wanted: 1 } });
    expect(screen.getByRole('group', { name: 'TorBox adds: warning' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Queue: warning' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open queue' })).toHaveAttribute('href', expect.stringContaining('library?view=queue'));
  });

  it('shows unavailable cells when the payload failed', () => {
    render(<MemoryRouter><StatusStrip status={undefined} services={services} loading={false} error /></MemoryRouter>);
    expect(screen.getAllByText('unavailable').length).toBeGreaterThanOrEqual(5);
  });
});
