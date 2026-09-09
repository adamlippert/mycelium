import { Link } from 'react-router-dom';
import type { ActivityEvent, OverviewPayload } from '../../../api';
import { Card, StatTile } from '../../../components/primitives';
import { formatTB } from './format';

type PillTone = 'ok' | 'warn' | 'danger' | 'neutral';

/** One entry per event name db.log_activity() is called with (grep -rn
 * 'log_activity("' *.py from the repo root), plus 'swapped'/'upgraded' which
 * release_swap.swap() logs through a variable. Unknown names render without
 * a pill rather than erroring. */
const PILLS: Record<string, { label: string; tone: PillTone }> = {
  played: { label: 'play', tone: 'ok' },
  swapped: { label: 'swap', tone: 'neutral' },
  upgraded: { label: 'upgrade', tone: 'neutral' },
  added: { label: 'request', tone: 'ok' },
  requested: { label: 'request', tone: 'ok' },
  approved: { label: 'request', tone: 'ok' },
  wanted: { label: 'wanted', tone: 'warn' },
  failed: { label: 'failed', tone: 'danger' },
  scraper: { label: 'scraper', tone: 'danger' },
  cleanup: { label: 'job', tone: 'neutral' },
  purged: { label: 'removed', tone: 'neutral' },
  dedup_removed: { label: 'removed', tone: 'neutral' },
  found: { label: 'found', tone: 'ok' },
  consolidated: { label: 'consolidated', tone: 'neutral' },
  recovery: { label: 'recovery', tone: 'neutral' },
  quota_warn: { label: 'quota', tone: 'warn' },
  watchdog: { label: 'watchdog', tone: 'danger' },
};
const PILL_CLASS: Record<PillTone, string> = {
  ok: 'text-ok border-ok/40', warn: 'text-warn border-warn/40', danger: 'text-danger border-danger/40', neutral: 'text-muted border-border',
};

export function eventPill(event: string) {
  return PILLS[event] ?? null;
}

function clock(ts: string): string {
  const m = ts.match(/(\d{2}):(\d{2})/);
  return m ? `${m[1]}:${m[2]}` : ts;
}

export function ActivityBand({ activity, events, loading, errors }: {
  activity: OverviewPayload['activity'] | undefined; events: ActivityEvent[] | undefined; loading: boolean;
  errors: string[] | undefined;
}) {
  const p = activity?.plays;
  const r = activity?.requests_7d;
  const e = activity?.egress;
  const playsOff = (errors ?? []).includes('plays');
  const baseOff = (errors ?? []).includes('base');
  // loading or a wholly missing payload keeps the pre-existing "-"; a named
  // block that failed (while the rest of the payload loaded fine) reads
  // "unavailable" instead of the block's fake zero default.
  const v = (s: string, blockOff: boolean) => (loading || !activity ? '-' : blockOff ? 'unavailable' : s);
  return (
    <div className="grid gap-3 lg:grid-cols-[1.1fr_1fr]">
      <Card>
        <div className="mb-3 text-sm font-semibold text-body">Watching and requesting</div>
        <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }}>
          <StatTile value={v(String(p?.today ?? 0), playsOff)} label="Plays today" sub={p && !playsOff ? `${p.titles_today} titles` : undefined} />
          <StatTile value={v(String(p?.week ?? 0), playsOff)} label="Plays this week" sub={p && !playsOff ? `${p.titles_week} titles` : undefined} />
          <StatTile value={v(String(r?.total ?? 0), baseOff)} label="Requests 7d" sub={r && !baseOff ? `${r.succeeded} ok, ${r.failed} failed` : undefined}
            glow={r && r.failed > 0 && !baseOff ? 'danger' : undefined} />
          <StatTile value={v(r ? `${Math.round(r.success_rate)}%` : '-', baseOff)} label="Success rate 7d" glow="ok" />
          <StatTile value={v(e ? formatTB(e.proxied_bytes + e.estimated_bytes) : '-', baseOff)} label="Egress this month"
            sub={e && !baseOff ? `${formatTB(e.proxied_bytes)} proxied, ${formatTB(e.estimated_bytes)} estimated` : undefined} />
        </div>
      </Card>
      <Card>
        <div className="mb-3 text-sm font-semibold text-body">Recent activity</div>
        {events === undefined ? (
          <p className="text-xs text-muted">Loading…</p>
        ) : events.length === 0 ? (
          <p className="text-xs text-muted">No activity yet</p>
        ) : (
          <div className="divide-y divide-border text-xs">
            {events.slice(0, 8).map((ev) => {
              const pill = eventPill(ev.event);
              return (
                <div key={ev.id} className="grid grid-cols-[52px_1fr_auto] items-baseline gap-2.5 py-1.5 first:pt-0">
                  <span className="font-mono text-[11px] text-white/30">{clock(ev.created_at)}</span>
                  <span className="min-w-0 truncate text-muted">
                    <span className="font-medium text-body">{ev.title}</span>{ev.message ? ` ${ev.message}` : ''}
                  </span>
                  {pill && <span className={`rounded-full border px-1.5 py-px text-[10px] uppercase tracking-wide ${PILL_CLASS[pill.tone]}`}>{pill.label}</span>}
                </div>
              );
            })}
          </div>
        )}
        <Link to={{ hash: 'logs' }} className="mt-3 block text-[11px] text-accent-light hover:underline">All activity</Link>
      </Card>
    </div>
  );
}
