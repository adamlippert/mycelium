import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { Card, StatTile, StatusDot } from '../../components/primitives';

const GIB = 1024 ** 3;

function formatGiB(bytes: number): string {
  return `${(bytes / GIB).toFixed(1)} GiB`;
}

function healthTone(status: string): 'ok' | 'warn' | 'danger' {
  if (status === 'ok') return 'ok';
  if (status === 'down') return 'danger';
  return 'warn';
}

function formatUsageSize(totalGb: number): string {
  if (totalGb > 1000) return `${(totalGb / 1000).toFixed(1)} TB`;
  return `${totalGb.toFixed(1)} GB`;
}

function humanizeState(state: string): string {
  return state.replace(/_/g, ' ');
}

function formatCountdown(sec: number): string {
  if (sec <= 0) return 'now';
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function EndpointRow({ label, hint, value }: { label: string; hint: string; value: string }) {
  return (
    <div>
      <div className="mb-1 text-[11px] text-muted">
        {label} ({hint})
      </div>
      <div className="flex items-center gap-2">
        <code className="flex-1 truncate rounded bg-white/5 px-2 py-1.5 text-xs text-body">{value}</code>
        <button
          type="button"
          onClick={() => navigator.clipboard.writeText(value)}
          className="rounded border border-border px-2 py-1 text-xs text-muted transition hover:text-white"
        >
          Copy
        </button>
      </div>
    </div>
  );
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
  // Load-once cards (fix round 1): no refetchInterval, they refresh on remount only.
  const quotaQ = useQuery({ queryKey: ['admin-torbox-quota'], queryFn: api.torboxQuota, retry: false });
  const metricsQ = useQuery({ queryKey: ['admin-metrics-summary'], queryFn: api.metricsSummary, retry: false });
  const torboxUsageQ = useQuery({ queryKey: ['admin-torbox-usage'], queryFn: api.torboxUsage, retry: false });
  const storageQ = useQuery({ queryKey: ['admin-storage'], queryFn: api.storage, retry: false });
  const libHealthQ = useQuery({ queryKey: ['admin-library-health'], queryFn: api.libraryHealth, retry: false });

  const stats = statsQ.data;
  const requests = stats?.requests;
  // Fix round 1: a tile labelled "7d" must show a 7d number - succeeded + failed
  // over the last 7 days, not requests.total (all-time request count).
  const requests7d = (requests?.succeeded_7d ?? 0) + (requests?.failed_7d ?? 0);
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

  const library = stats?.library;
  const successRate7d = requests ? Math.round(requests.success_rate_7d) : null;

  const events = activityQ.data?.events ?? [];

  const folders = storageQ.data?.folders ?? [];

  const metrics = metricsQ.data;
  const latencyRows = metrics?.latency ?? [];
  const qualityRows = metrics?.quality ?? [];
  const sourceRows = metrics?.sources ?? [];
  const failureRows = metrics?.failures ?? [];
  const uniqueSourceMap = new Map((metrics?.unique_sources ?? []).map((r) => [r.label, r.count]));
  const noMetrics =
    latencyRows.length === 0 && qualityRows.length === 0 && sourceRows.length === 0 && failureRows.length === 0;

  const usage = torboxUsageQ.data?.usage;
  const usageStateEntries = Object.entries(usage?.states ?? {}).sort((a, b) => b[1] - a[1]);
  const usagePlan = torboxUsageQ.data?.plan ?? null;

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile
          value={statsQ.isLoading ? '-' : String(requests7d)}
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
        <StatTile
          value={stats ? `${(stats.egress_bytes_month / 1e12).toFixed(2)} TB` : '-'}
          label="Egress this month"
          sub="TorBox plan floors start at 5 TB"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile
          value={statsQ.isLoading ? '-' : String(library?.movie_count ?? 0)}
          label="Movies"
        />
        <StatTile
          value={statsQ.isLoading ? '-' : String(library?.episode_count ?? 0)}
          label="Episodes"
        />
        <StatTile
          value={statsQ.isLoading ? '-' : String(library?.series_count ?? 0)}
          label="Series"
        />
        <StatTile
          value={statsQ.isLoading ? '-' : String(activeWanted)}
          label="Wanted"
        />
        <StatTile
          value={statsQ.isLoading || successRate7d === null ? '-' : `${successRate7d}%`}
          label="Success rate 7d"
          sub={requests ? `${requests.succeeded_7d} ok - ${requests.failed_7d} fail` : undefined}
          glow="ok"
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
              <div
                data-testid="health-stream-front"
                className="flex items-center gap-2 text-xs"
                title="Which process serves streams. Toggled with the STREAM_FRONT_ENABLED environment variable (Coolify), takes effect on container restart."
              >
                <StatusDot tone={healthQ.data?.stream_front ? 'ok' : 'warn'} />
                <span className="text-body">Streaming front</span>
                <span className="ml-auto text-muted">
                  {healthQ.data?.stream_front ? 'Go (active)' : 'Python fallback'}
                </span>
              </div>
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

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <div className="mb-3 text-sm font-semibold text-body">TorBox quota</div>
          {quotaQ.isLoading ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : !quotaQ.data ? (
            <p className="text-xs text-muted">unavailable</p>
          ) : (
            <div className="space-y-2">
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted">createtorrent / hour</span>
                <span className="font-mono text-body">
                  {quotaQ.data.count} / {quotaQ.data.limit}
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-white/5">
                <div
                  className="h-full rounded-full bg-accent"
                  style={{
                    width: `${Math.min(100, Math.round((100 * quotaQ.data.count) / (quotaQ.data.limit || 1)))}%`,
                  }}
                />
              </div>
              <div className="text-[11px] text-muted">resets in {formatCountdown(quotaQ.data.resets_in_sec)}</div>
              {Object.keys(quotaQ.data.by_reason).length > 0 && (
                <div className="space-y-1 pt-1">
                  {Object.entries(quotaQ.data.by_reason)
                    .sort((a, b) => b[1] - a[1])
                    .map(([reason, n]) => (
                      <div key={reason} className="flex items-center justify-between text-xs">
                        <span className="text-muted">{reason}</span>
                        <span className="font-mono text-body">{n}</span>
                      </div>
                    ))}
                </div>
              )}
            </div>
          )}
        </Card>

        <Card>
          <div className="mb-3 text-sm font-semibold text-body">TorBox Usage</div>
          {torboxUsageQ.isLoading ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : torboxUsageQ.isError || !usage ? (
            <p className="text-xs text-muted">unavailable</p>
          ) : (
            <div className="space-y-2">
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted">torrents</span>
                <span className="font-mono text-body">{usage.torrent_count}</span>
              </div>
              <div className="flex items-baseline justify-between text-xs">
                <span className="text-muted">total size</span>
                <span className="font-mono text-body">{formatUsageSize(usage.total_gb)}</span>
              </div>
              {usagePlan && (
                <div className="flex items-baseline justify-between text-xs">
                  <span className="text-muted">plan</span>
                  <span className="text-body">{usagePlan}</span>
                </div>
              )}
              {usageStateEntries.length > 0 && (
                <div className="space-y-1 pt-1">
                  {usageStateEntries.map(([state, n]) => (
                    <div key={state} className="flex items-center justify-between text-xs">
                      <span className="text-muted">{humanizeState(state)}</span>
                      <span className="font-mono text-body">{n}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>

        <Card>
          <div className="mb-3 text-sm font-semibold text-body">Metrics (30d)</div>
          {metricsQ.isLoading ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : noMetrics ? (
            <p className="text-xs text-muted">No data yet</p>
          ) : (
            <div className="space-y-3">
              {latencyRows.length > 0 && (
                <div>
                  <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">Latency</div>
                  <div className="space-y-1">
                    {latencyRows.map((r) => (
                      <div key={r.label} className="flex items-center justify-between text-xs">
                        <span className="text-muted">{r.label}</span>
                        <span className="font-mono text-body">{r.avg_real != null ? `${r.avg_real.toFixed(1)}s` : '-'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {qualityRows.length > 0 && (
                <div>
                  <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">Quality added</div>
                  <div className="space-y-1">
                    {qualityRows.map((r) => (
                      <div key={r.label} className="flex items-center justify-between text-xs">
                        <span className="text-muted">{r.label}</span>
                        <span className="font-mono text-body">{r.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {sourceRows.length > 0 && (
                <div>
                  <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">Source win rate</div>
                  <div className="space-y-1">
                    {sourceRows.map((r) => (
                      <div key={r.label} className="flex items-center justify-between text-xs">
                        <span className="text-muted">{r.label}</span>
                        <span className="font-mono text-body">
                          {r.count} <span className="text-muted">({uniqueSourceMap.get(r.label) ?? 0} uniq)</span>
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {failureRows.length > 0 && (
                <div>
                  <div className="mb-1 text-[11px] uppercase tracking-wide text-muted">Failures</div>
                  <div className="space-y-1">
                    {failureRows.map((r) => (
                      <div key={r.label} className="flex items-center justify-between text-xs">
                        <span className="text-muted">{r.label}</span>
                        <span className="font-mono text-danger">{r.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
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
          <div className="mb-3 text-sm font-semibold text-body">Integration endpoints</div>
          <div className="space-y-3">
            <EndpointRow
              label="Seerr webhook URL"
              hint="already configured"
              value={`${window.location.origin}/webhook`}
            />
            <EndpointRow
              label="TorBox push notification URL"
              hint="configure in TorBox settings to skip polling"
              value={`${window.location.origin}/torbox-webhook`}
            />
            <EndpointRow
              label="Catbox stream prefix"
              hint=".strm files contain proxy URLs starting with this"
              value={`${window.location.origin}/stream/<token>`}
            />
            <div>
              <div className="mb-1 text-[11px] text-muted">Webhook secret (send as header X-Webhook-Secret)</div>
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
            </div>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <div className="mb-3 text-sm font-semibold text-body">Top folders</div>
          {storageQ.isLoading ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : folders.length === 0 ? (
            <p className="text-xs text-muted">Empty</p>
          ) : (
            <div className="space-y-1">
              {folders.slice(0, 15).map((f) => (
                <div key={f.path} className="flex items-center justify-between gap-2 text-xs">
                  <span className="truncate text-muted">{f.path}</span>
                  <span className="font-mono text-body">{f.count}</span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <div className="mb-3 text-sm font-semibold text-body">Library health</div>
          {libHealthQ.isLoading ? (
            <p className="text-xs text-muted">Loading…</p>
          ) : !libHealthQ.data ? (
            <p className="text-xs text-muted">unavailable</p>
          ) : (
            <div className="flex flex-wrap gap-4">
              <div>
                <div className="font-mono text-lg text-body">{libHealthQ.data.strm_count}</div>
                <div className="text-[11px] text-muted">.strm files</div>
              </div>
              <div>
                <div className="font-mono text-lg text-body">{libHealthQ.data.db_count}</div>
                <div className="text-[11px] text-muted">DB items</div>
              </div>
              <div>
                <div className={`font-mono text-lg ${libHealthQ.data.strm_without_db > 0 ? 'text-warn' : 'text-ok'}`}>
                  {libHealthQ.data.strm_without_db}
                </div>
                <div className="text-[11px] text-muted">strm w/o DB</div>
              </div>
              <div>
                <div className={`font-mono text-lg ${libHealthQ.data.db_without_strm > 0 ? 'text-warn' : 'text-ok'}`}>
                  {libHealthQ.data.db_without_strm}
                </div>
                <div className="text-[11px] text-muted">DB w/o strm</div>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
