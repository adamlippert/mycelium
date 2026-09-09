import type { MetricsSummary } from '../../../../api';

export function MetricsPanel({ metrics, loading }: { metrics: MetricsSummary | undefined; loading: boolean }) {
  const latencyRows = metrics?.latency ?? [];
  const qualityRows = metrics?.quality ?? [];
  const sourceRows = metrics?.sources ?? [];
  const failureRows = metrics?.failures ?? [];
  const uniqueSourceMap = new Map((metrics?.unique_sources ?? []).map((r) => [r.label, r.count]));
  const noMetrics =
    latencyRows.length === 0 && qualityRows.length === 0 && sourceRows.length === 0 && failureRows.length === 0;

  if (loading) return <p className="text-xs text-muted">Loading…</p>;
  if (noMetrics) return <p className="text-xs text-muted">No data yet</p>;
  return (
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
  );
}
