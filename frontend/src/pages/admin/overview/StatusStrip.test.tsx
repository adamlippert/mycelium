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

function renderIt(props: Partial<Parameters<typeof StatusStrip>[0]> = {}) {
  return render(
    <MemoryRouter>
      <StatusStrip status={status} services={services} servicesLoading={false} loading={false} error={false} errors={[]} {...props} />
    </MemoryRouter>,
  );
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
    renderIt({ services: [{ name: 'TorBox', status: 'ok' }, { name: 'Jellyfin', status: 'down', note: 'HTTP 502' }] });
    const servicesCell = screen.getByRole('group', { name: 'Services: problem' });
    expect(servicesCell).toBeInTheDocument();
    expect(within(servicesCell).getByText('1/2')).toBeInTheDocument();
    expect(screen.getByText('Jellyfin: down')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Settings' })).toBeInTheDocument();
  });

  it('marks a warn-only service row amber, not red, and names it without saying "down"', () => {
    // I1: a health row with status "warn" (e.g. health.py's "TorBox adds
    // this hour" or "Jellyfin libraries" advisories) must not paint the
    // Services cell red or claim the service is down.
    renderIt({
      services: [{ name: 'TorBox', status: 'ok' }, { name: 'TorBox adds this hour', status: 'warn', note: '45/60 uncached' }],
    });
    const servicesCell = screen.getByRole('group', { name: 'Services: warning' });
    expect(servicesCell).toBeInTheDocument();
    expect(within(servicesCell).getByText('1/2')).toBeInTheDocument();
    expect(screen.getByText('TorBox adds this hour: warn')).toBeInTheDocument();
    expect(within(servicesCell).queryByText(/down/)).not.toBeInTheDocument();
  });

  it('shows the Services cell as unavailable with the off tone when the health query has failed', () => {
    renderIt({ services: undefined });
    expect(screen.getByRole('group', { name: 'Services: unavailable' })).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: 'Services: unavailable' })).getByText('unavailable')).toBeInTheDocument();
  });

  it('turns TorBox adds amber from 45 uncached and queue amber with retries', () => {
    renderIt({ status: { ...status, torbox_adds: { ...status.torbox_adds, uncached: 45 }, queue: { retry: 2, wanted: 1 } } });
    expect(screen.getByRole('group', { name: 'TorBox adds: warning' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Queue: warning' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open queue' })).toHaveAttribute('href', expect.stringContaining('library?view=queue'));
  });

  it('shows unavailable cells when the payload failed', () => {
    renderIt({ status: undefined, error: true });
    expect(screen.getAllByText('unavailable').length).toBeGreaterThanOrEqual(5);
  });

  it('shows the loading placeholder, not unavailable, while the payload is in flight', () => {
    renderIt({ status: undefined, loading: true });
    expect(screen.queryByText('unavailable')).not.toBeInTheDocument();
    expect(screen.getAllByText('-').length).toBeGreaterThanOrEqual(5);
  });

  it('shows the Services cell as "-" while loading, never unavailable', () => {
    renderIt({ services: undefined, servicesLoading: true });
    const servicesCell = screen.getByRole('group', { name: 'Services: unavailable' });
    // "off" tone shares its label with "unavailable"; the loading state
    // must render the dash, not the word, and no reason line.
    expect(within(servicesCell).getByText('-')).toBeInTheDocument();
    expect(within(servicesCell).queryByText('unavailable')).not.toBeInTheDocument();
  });

  it('marks a named failed block unavailable and off even though the payload otherwise loaded', () => {
    renderIt({ errors: ['scrapers', 'attention'] });
    expect(screen.getByRole('group', { name: 'Scrapers: unavailable' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Attention: unavailable' })).toBeInTheDocument();
    // Everything else still reads its real figure.
    expect(screen.getByRole('group', { name: 'TorBox adds: ok' })).toBeInTheDocument();
  });

  it('takes Failures 7d and Queue off when base failed, since neither has its own block', () => {
    renderIt({ errors: ['base'] });
    expect(screen.getByRole('group', { name: 'Failures 7d: unavailable' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Queue: unavailable' })).toBeInTheDocument();
  });
});
