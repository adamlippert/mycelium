import type { HealthService, OverviewPayload } from '../../../api';
import { StatusCell } from '../../../components/primitives';
import type { StatusTone } from '../../../components/primitives';
import { relativeAge } from './format';

const ADD_WARN_AT = 45;

type Cell = { tone: StatusTone; value: string; sub?: string };

export function StatusStrip({ status, services, servicesLoading, loading, error, errors }: {
  status: OverviewPayload['status'] | undefined;
  services: HealthService[] | undefined;
  servicesLoading: boolean;
  loading: boolean;
  error: boolean;
  errors: string[] | undefined;
}) {
  const off = error || (!loading && !status);
  const failed = (name: string) => (errors ?? []).includes(name);

  // Loading or a failed block both render "-" / "unavailable" with the off
  // tone, on top of whatever the base payload's own off/loading state is.
  const cell = (blockOff: boolean, tone: StatusTone, value: string, sub?: string): Cell => {
    if (loading) return { tone: 'off', value: '-' };
    if (off || blockOff) return { tone: 'off', value: 'unavailable' };
    return { tone, value, sub };
  };

  const enabled = (services ?? []).filter((s) => s.status !== 'disabled');
  const down = enabled.filter((s) => s.status === 'down');
  const warn = enabled.filter((s) => s.status === 'warn');
  const notOk = [...down, ...warn];
  const servicesOff = services === undefined && !servicesLoading;
  const services_: Cell = servicesLoading
    ? { tone: 'off', value: '-' }
    : servicesOff
      ? { tone: 'off', value: 'unavailable' }
      : {
          tone: down.length ? 'danger' : warn.length ? 'warn' : 'ok',
          value: `${enabled.length - down.length - warn.length}/${enabled.length}`,
          sub: notOk.length ? notOk.map((s) => `${s.name}: ${s.status}`).join(', ') : enabled.map((s) => s.name).join(', '),
        };

  const scrapersOn = (status?.scrapers ?? []).filter((s) => s.state !== 'disabled');
  const scrapersDown = scrapersOn.filter((s) => s.state === 'down');
  const scrapers = cell(failed('scrapers'), scrapersDown.length ? 'warn' : 'ok',
    `${scrapersOn.length - scrapersDown.length}/${scrapersOn.length}`,
    scrapersDown.length ? `${scrapersDown.map((s) => s.name).join(', ')} down` : undefined);

  const adds = status?.torbox_adds;
  const torboxAdds = cell(failed('torbox_adds'), adds && adds.uncached >= ADD_WARN_AT ? 'warn' : 'ok',
    adds ? `${adds.uncached} / ${adds.limit}` : '-',
    adds ? `uncached this hour, ${adds.cached} cached` : undefined);

  // Failures and queue read straight off the base payload: no block of
  // their own, so a base failure is what takes them off.
  const baseOff = failed('base');
  const failures = cell(baseOff, status && status.failures_7d > 0 ? 'danger' : 'ok', String(status?.failures_7d ?? 0));

  const q = status?.queue;
  const queue = cell(baseOff, q && q.retry > 0 ? 'warn' : 'ok', String((q?.retry ?? 0) + (q?.wanted ?? 0)),
    q ? (q.retry ? `${q.retry} retrying, ${q.wanted} wanted` : 'retry queue empty') : undefined);

  const attention = cell(failed('attention'), status && status.attention > 0 ? 'warn' : 'ok',
    String(status?.attention ?? 0), status ? 'degraded or stuck titles' : undefined);

  const approvals = status?.approvals;
  const approvalsCell = cell(failed('approvals'), approvals && approvals.pending > 0 ? 'warn' : 'ok',
    String(approvals?.pending ?? 0),
    approvals?.oldest_age_sec != null ? `oldest ${relativeAge(approvals.oldest_age_sec)}` : approvals ? 'nothing waiting' : undefined);

  return (
    <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
      <StatusCell tone={services_.tone} label="Services" value={services_.value} sub={services_.sub}
        href="#settings" linkLabel="Open Settings" />
      <StatusCell tone={scrapers.tone} label="Scrapers" value={scrapers.value} sub={scrapers.sub}
        href="#scrapers" linkLabel="Open Scrapers" />
      <StatusCell tone={torboxAdds.tone} label="TorBox adds" value={torboxAdds.value} sub={torboxAdds.sub}
        href="#settings" linkLabel="Open Settings" />
      <StatusCell tone={failures.tone} label="Failures 7d" value={failures.value}
        href="#library?view=attention" linkLabel="Open failures" />
      <StatusCell tone={queue.tone} label="Queue" value={queue.value} sub={queue.sub}
        href="#library?view=queue" linkLabel="Open queue" />
      <StatusCell tone={attention.tone} label="Attention" value={attention.value} sub={attention.sub}
        href="#library?view=attention" linkLabel="Open Library" />
      <StatusCell tone={approvalsCell.tone} label="Approvals" value={approvalsCell.value} sub={approvalsCell.sub}
        href="#requests" linkLabel="Review requests" />
    </div>
  );
}
