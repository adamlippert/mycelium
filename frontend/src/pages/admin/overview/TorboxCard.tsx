import type { OverviewPayload, TorBoxUsage } from '../../../api';
import { Card } from '../../../components/primitives';
import { formatCountdown, formatGiB, relativeAge } from './format';

function Row({ k, v, tone }: { k: string; v: string; tone?: 'warn' | 'ok' }) {
  return (<><span className="text-muted">{k}</span><span className={`text-right font-mono ${tone === 'warn' ? 'text-warn' : tone === 'ok' ? 'text-ok' : 'text-body'}`}>{v}</span></>);
}

function ago(iso: string): string {
  const sec = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 1000));
  return `${relativeAge(sec)} ago`;
}

const STATE_LABEL: Record<string, string> = { completed: 'Ready', cached: 'Ready', downloading: 'Downloading', stalled: 'Stalled', meta_dl: 'Fetching metadata', uploading: 'Seeding', paused: 'Paused' };

export function TorboxCard({ adds, byReason, usage, streamFront, recentStreams, last429At, idleMinutes }: {
  adds: OverviewPayload['status']['torbox_adds'] | undefined; byReason: Record<string, number> | undefined;
  usage: TorBoxUsage | undefined; streamFront: boolean | undefined; recentStreams: number | undefined;
  last429At: string | null | undefined; idleMinutes: number | null;
}) {
  const states = Object.entries(usage?.usage.states ?? {}).sort((a, b) => b[1] - a[1]);
  return (
    <Card>
      <div className="mb-3 text-sm font-semibold text-body">TorBox</div>
      <div className="grid gap-5 text-xs lg:grid-cols-3">
        <div>
          {adds ? (
            <>
              <div className="mb-2 flex items-baseline justify-between"><span className="text-muted">Uncached adds this hour</span><span className="font-mono text-body">{adds.uncached} / {adds.limit}</span></div>
              <div className="h-1.5 overflow-hidden rounded-full bg-white/5"><div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(100, Math.round((100 * adds.uncached) / (adds.limit || 1)))}%` }} /></div>
              <p className="mt-1.5 text-[11px] text-white/30">{adds.cached} cached adds this hour, not limited by TorBox. Resets in {formatCountdown(adds.resets_in_sec)}.</p>
              {byReason && Object.keys(byReason).length > 0 && (
                <div className="mt-2.5 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1">
                  {Object.entries(byReason).sort((a, b) => b[1] - a[1]).map(([k, n]) => <Row key={k} k={k} v={String(n)} />)}
                </div>
              )}
            </>
          ) : <p className="text-muted">unavailable</p>}
        </div>
        <div className="grid grid-cols-[1fr_auto] content-start gap-x-4 gap-y-1">
          {usage ? (
            <>
              <Row k="Torrents" v={String(usage.usage.torrent_count)} />
              <Row k="Total size" v={formatGiB(usage.usage.total_bytes)} />
              {usage.plan && <Row k="Plan" v={usage.plan} />}
              {states.map(([s, n]) => <Row key={s} k={STATE_LABEL[s] ?? s} v={String(n)} tone={s === 'stalled' ? 'warn' : undefined} />)}
            </>
          ) : <span className="text-muted">unavailable</span>}
        </div>
        <div className="grid grid-cols-[1fr_auto] content-start gap-x-4 gap-y-1">
          <Row k="Stream front" v={streamFront === undefined ? '-' : streamFront ? 'Go' : 'Flask'} tone={streamFront ? 'ok' : undefined} />
          <Row k="Streamed in last 15 min" v={recentStreams === undefined ? '-' : String(recentStreams)} />
          <Row k="Idle cleanup" v={idleMinutes ? `after ${idleMinutes} min` : '-'} />
          <Row k="Last 429" v={last429At === undefined ? '-' : last429At ? ago(last429At) : 'none since start'} />
        </div>
      </div>
    </Card>
  );
}
