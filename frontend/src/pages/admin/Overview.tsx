import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { Card, Pill, StatTile, StatusDot } from '../../components/primitives';

const GIB = 1024 ** 3;

function formatGiB(bytes: number): string {
  return `${(bytes / GIB).toFixed(1)} GiB`;
}

function healthTone(status: string): 'ok' | 'warn' | 'danger' {
  if (status === 'ok') return 'ok';
  if (status === 'down') return 'danger';
  return 'warn';
}

export default function Overview() {
  // Refresh cadence matches the Jinja dashboard: stats + health poll every
  // 30s, everything else loads once and refreshes only on remount.
  const statsQ = useQuery({ queryKey: ['admin-stats'], queryFn: api.stats, refetchInterval: 30_000 });
  const healthQ = useQuery({ queryKey: ['admin-health'], queryFn: api.health, refetchInterval: 30_000 });
  const activityQ = useQuery({ queryKey: ['admin-activity'], queryFn: api.activity });
  const torboxQ = useQuery({ queryKey: ['admin-torbox-list'], queryFn: api.torboxList, retry: false });
  const retryQueueQ = useQuery({ queryKey: ['admin-retry-queue'], queryFn: api.retryQueue, retry: false });
  const webhookQ = useQuery({ queryKey: ['admin-webhook-secret'], queryFn: api.webhookSecret, retry: false });
  const releasesQ = useQuery({ queryKey: ['admin-releases'], queryFn: api.releases });

  const stats = statsQ.data;
  const requests = stats?.requests;
  const activeWanted = stats?.wanted.active ?? 0;
  const qualities: Record<string, number> = stats?.qualities ?? {};
  const qualityEntries = Object.entries(qualities).sort((a, b) => b[1] - a[1]);
  const qualityTotal = qualityEntries.reduce((sum, [, n]) => sum + n, 0) || 1;

  // Queue depth: retry-queue rows + active wanted, when the retry-queue GET
  // is reachable; otherwise fall back to active wanted alone (see report).
  const retryRows = retryQueueQ.data?.items.length;
  const hasRetryQueue = !retryQueueQ.isError && retryRows !== undefined;
  const queueDepth = hasRetryQueue ? retryRows + activeWanted : activeWanted;
  const queueSub = hasRetryQueue ? `${retryRows} retrying · ${activeWanted} wanted` : 'active wanted';

  const torrents = torboxQ.data?.torrents;
  const torboxCount = torrents?.length ?? 0;
  const torboxBytes = (torrents ?? []).reduce((sum, t) => sum + (t.size || 0), 0);

  const events = activityQ.data?.events ?? [];
  const releases = releasesQ.data?.releases ?? [];

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          value={statsQ.isLoading ? '-' : String(requests?.total ?? 0)}
          label="Requests 7d"
          sub={requests ? `${requests.succeeded_7d} ok / ${requests.failed_7d} fail` : undefined}
        />
        <StatTile
          value={statsQ.isLoading ? '-' : String(queueDepth)}
          label="Queue depth"
          sub={statsQ.isLoading ? undefined : queueSub}
        />
        <StatTile
          value={torboxQ.isLoading ? '-' : torboxQ.isError ? 'unavailable' : String(torboxCount)}
          label="TorBox library"
          sub={!torboxQ.isLoading && !torboxQ.isError ? formatGiB(torboxBytes) : undefined}
        />
        <StatTile
          value={statsQ.isLoading ? '-' : String(requests?.failed_7d ?? 0)}
          label="Failures 7d"
          glow={requests && requests.failed_7d > 0 ? 'danger' : undefined}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <div className="mb-3 text-sm font-semibold text-body">Service health</div>
          {healthQ.isLoading ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : (
            <div className="space-y-2">
              {(healthQ.data?.services ?? []).map((s) => (
                <div key={s.name} data-testid="health-service" className="flex items-center gap-2 text-xs">
                  <StatusDot tone={healthTone(s.status)} />
                  <span className="text-body">{s.name}</span>
                  <span className="ml-auto text-muted">{s.status}</span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <div className="mb-3 text-sm font-semibold text-body">Quality distribution</div>
          {statsQ.isLoading ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : qualityEntries.length === 0 ? (
            <p className="text-xs text-muted">No data yet</p>
          ) : (
            <div className="space-y-2">
              {qualityEntries.map(([q, n]) => (
                <div key={q} className="flex items-center gap-2 text-xs">
                  <span className="w-14 flex-none truncate text-muted">{q}</span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{ width: `${Math.round((100 * n) / qualityTotal)}%` }}
                    />
                  </div>
                  <span className="w-6 flex-none text-right text-muted">{n}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <div className="mb-3 text-sm font-semibold text-body">Recent activity</div>
          {activityQ.isLoading ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : events.length === 0 ? (
            <p className="text-xs text-muted">No activity yet</p>
          ) : (
            <div className="space-y-1.5">
              {events.slice(0, 20).map((ev, i) => (
                <div key={i} className="text-xs text-muted">
                  <span>{(ev.created_at || '').slice(0, 16)}</span>{' '}
                  <span className="font-medium text-body">{ev.event}</span>{' '}
                  {ev.title && <span>{ev.title}</span>}
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <div className="mb-3 text-sm font-semibold text-body">Webhook secret</div>
          {webhookQ.isLoading ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : webhookQ.isError || !webhookQ.data ? (
            <p className="text-xs text-muted">unavailable</p>
          ) : (
            <div className="flex items-center gap-2">
              <code className="flex-1 truncate rounded bg-white/5 px-2 py-1.5 text-xs text-body">
                {webhookQ.data.secret}
              </code>
              <button
                type="button"
                onClick={() => navigator.clipboard.writeText(webhookQ.data!.secret)}
                className="rounded border border-border px-2 py-1 text-xs text-muted transition hover:text-white"
              >
                Copy
              </button>
            </div>
          )}
        </Card>
      </div>

      <Card>
        <div className="mb-3 text-sm font-semibold text-body">Releases</div>
        {releasesQ.isLoading ? (
          <p className="text-xs text-muted">Loading…</p>
        ) : releases.length === 0 ? (
          <p className="text-xs text-muted">No releases yet</p>
        ) : (
          <div className="space-y-3">
            {releases.map((rel, i) => (
              <div key={rel.version} className="text-xs">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-semibold text-body">v{rel.version}</span>
                  <span className="text-muted">{rel.date}</span>
                  {i === 0 && <Pill state="ready">current</Pill>}
                </div>
                {rel.notes.length > 0 && (
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted">
                    {rel.notes.map((note, j) => (
                      <li key={j}>{note}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
