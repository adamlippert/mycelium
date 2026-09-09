import type { HealthService, OverviewPayload } from '../../../api';
import { StatusCell } from '../../../components/primitives';
import type { StatusTone } from '../../../components/primitives';
import { relativeAge } from './format';

const ADD_WARN_AT = 45;

export function StatusStrip({ status, services, loading, error }: {
  status: OverviewPayload['status'] | undefined;
  services: HealthService[] | undefined;
  loading: boolean;
  error: boolean;
}) {
  const off = error || (!loading && !status);
  const v = (s: string) => (loading ? '-' : off ? 'unavailable' : s);
  const tone = (t: StatusTone): StatusTone => (loading || off ? 'off' : t);

  const enabled = (services ?? []).filter((s) => s.status !== 'disabled');
  const down = enabled.filter((s) => s.status !== 'ok');
  const scrapersOn = (status?.scrapers ?? []).filter((s) => s.state !== 'disabled');
  const scrapersDown = scrapersOn.filter((s) => s.state === 'down');
  const adds = status?.torbox_adds;
  const q = status?.queue;
  const approvals = status?.approvals;

  return (
    <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
      <StatusCell tone={services === undefined ? 'off' : down.length ? 'danger' : 'ok'} label="Services"
        value={services === undefined ? 'unavailable' : `${enabled.length - down.length}/${enabled.length}`}
        sub={services === undefined ? undefined : down.length ? down.map((s) => `${s.name} down`).join(', ') : enabled.map((s) => s.name).join(', ')}
        href="#settings" linkLabel="Open Settings" />
      <StatusCell tone={tone(scrapersDown.length ? 'warn' : 'ok')} label="Scrapers"
        value={v(`${scrapersOn.length - scrapersDown.length}/${scrapersOn.length}`)}
        sub={status && scrapersDown.length ? `${scrapersDown.map((s) => s.name).join(', ')} down` : undefined}
        href="#scrapers" linkLabel="Open Scrapers" />
      <StatusCell tone={tone(adds && adds.uncached >= ADD_WARN_AT ? 'warn' : 'ok')} label="TorBox adds"
        value={v(adds ? `${adds.uncached} / ${adds.limit}` : '-')}
        sub={adds ? `uncached this hour, ${adds.cached} cached` : undefined}
        href="#settings" linkLabel="Open Settings" />
      <StatusCell tone={tone(status && status.failures_7d > 0 ? 'danger' : 'ok')} label="Failures 7d"
        value={v(String(status?.failures_7d ?? 0))}
        href="#library?view=attention" linkLabel="Open failures" />
      <StatusCell tone={tone(q && q.retry > 0 ? 'warn' : 'ok')} label="Queue"
        value={v(String((q?.retry ?? 0) + (q?.wanted ?? 0)))}
        sub={q ? (q.retry ? `${q.retry} retrying, ${q.wanted} wanted` : 'retry queue empty') : undefined}
        href="#library?view=queue" linkLabel="Open queue" />
      <StatusCell tone={tone(status && status.attention > 0 ? 'warn' : 'ok')} label="Attention"
        value={v(String(status?.attention ?? 0))}
        sub={status ? 'degraded or stuck titles' : undefined}
        href="#library?view=attention" linkLabel="Open Library" />
      <StatusCell tone={tone(approvals && approvals.pending > 0 ? 'warn' : 'ok')} label="Approvals"
        value={v(String(approvals?.pending ?? 0))}
        sub={approvals?.oldest_age_sec != null ? `oldest ${relativeAge(approvals.oldest_age_sec)}` : approvals ? 'nothing waiting' : undefined}
        href="#requests" linkLabel="Review requests" />
    </div>
  );
}
