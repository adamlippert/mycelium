import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api';
import type { PillState } from '../../components/primitives';
import { Card, DataTable, Pill, StatusDot } from '../../components/primitives';
import type { Column } from '../../components/primitives';

type ScraperRow = {
  name: string;
  latency_ms: number | null;
  state: 'ok' | 'slow' | 'down' | 'unknown' | 'disabled';
  samples: number;
};

/** "212 ms" under 1000ms, "1.4 s" at/over 1000ms, "-" when there is no sample yet. */
export function formatLatency(ms: number | null): string {
  if (ms == null) return '-';
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms)} ms`;
}

const PILL_BY_STATE: Record<ScraperRow['state'], PillState> = {
  ok: 'ready',
  slow: 'queued',
  down: 'failed',
  unknown: 'lazy',
  disabled: 'lazy',
};

function ScraperStatusDot({ state }: { state: ScraperRow['state'] }) {
  // 'unknown' has no signal to color yet, so it renders a plain dim dot
  // instead of borrowing the danger glow meant for a confirmed-down scraper.
  if (state === 'unknown' || state === 'disabled') {
    return <span className="block h-[7px] w-[7px] flex-none rounded-full bg-white/20" />;
  }
  const tone = state === 'ok' ? 'ok' : state === 'slow' ? 'warn' : 'danger';
  return <StatusDot tone={tone} />;
}

/** Ported from the Jinja `zileanSync()`/`zileanImport()`/`zileanStatus()` controls. */
function ZileanPanel() {
  const qc = useQueryClient();
  const [msg, setMsg] = useState('');
  const { data } = useQuery({
    queryKey: ['zilean-status'],
    queryFn: api.zileanStatus,
    // Mirrors the Jinja panel: only poll quickly while a sync/import is running.
    refetchInterval: (q) => (q.state.data?.syncing || q.state.data?.importing ? 3000 : false),
  });

  const syncMut = useMutation({
    mutationFn: () => api.zileanSync(),
    onSuccess: (r) => {
      if (r.error) {
        setMsg(r.error);
        return;
      }
      setMsg('Sync started...');
      qc.invalidateQueries({ queryKey: ['zilean-status'] });
    },
  });
  const importMut = useMutation({
    mutationFn: () => api.zileanImport(),
    onSuccess: (r) => {
      if (r.error) {
        setMsg(r.error);
        return;
      }
      setMsg('Import started...');
      qc.invalidateQueries({ queryKey: ['zilean-status'] });
    },
  });

  if (!data) {
    return (
      <Card>
        <p className="text-xs text-muted">Loading...</p>
      </Card>
    );
  }

  if (data.mode !== 'native') {
    return (
      <Card>
        <div className="mb-2 text-sm font-semibold text-body">Zilean native index</div>
        <p className="text-xs text-muted">mode: {data.mode} (native index inactive)</p>
      </Card>
    );
  }

  const err = data.last_import_error || data.last_error;

  return (
    <Card>
      <div className="mb-2 text-sm font-semibold text-body">Zilean native index</div>
      <div className="mb-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => {
            if (confirm('Start a Zilean native hashlist sync? The first run can take a while.')) {
              setMsg('');
              syncMut.mutate();
            }
          }}
          disabled={syncMut.isPending || data.syncing}
          className="rounded bg-accent px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
        >
          Sync now
        </button>
        <button
          type="button"
          onClick={() => {
            if (
              confirm(
                'Import from the external Zilean Postgres database configured above? This can take a while for 1M+ rows.',
              )
            ) {
              setMsg('');
              importMut.mutate();
            }
          }}
          disabled={importMut.isPending || data.importing}
          className="rounded border border-border px-3 py-1.5 text-sm hover:bg-bg disabled:opacity-50"
        >
          Import from Postgres
        </button>
      </div>
      <div className="font-mono text-xs text-muted">
        {(data.total_hashes ?? 0)} hash(es) - last sync: {data.last_synced_at || 'never'} (
        {data.last_status || 'never'}, +{data.last_new_hashes ?? 0})
        {data.last_import_at && ` - last import: ${data.last_import_at} (${data.last_import_count} rows)`}
        {data.syncing && ' - syncing...'}
        {data.importing && ' - importing...'}
      </div>
      {err && !data.syncing && !data.importing && <div className="mt-1 text-xs text-danger">{err}</div>}
      {msg && <div className="mt-2 font-mono text-xs text-muted">{msg}</div>}
    </Card>
  );
}

export default function Scrapers() {
  const { data } = useQuery({
    queryKey: ['scraper-health'],
    queryFn: api.scraperHealth,
    refetchInterval: 30_000,
  });

  const rows = data?.scrapers ?? [];

  const columns: Column<ScraperRow>[] = [
    {
      key: 'name',
      header: 'Scraper',
      render: (s) => (
        <span className="flex items-center gap-2">
          <ScraperStatusDot state={s.state} />
          <span className="text-body">{s.name}</span>
        </span>
      ),
    },
    {
      key: 'latency',
      header: 'Median latency',
      render: (s) => <span className="font-mono text-xs text-body">{formatLatency(s.latency_ms)}</span>,
    },
    {
      key: 'state',
      header: 'State',
      render: (s) => <Pill state={PILL_BY_STATE[s.state]}>{s.state}</Pill>,
    },
    {
      key: 'samples',
      header: 'Samples',
      align: 'right',
      render: (s) => <span className="text-xs text-muted">{s.samples}</span>,
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="mb-3 text-lg font-bold">Scraper health</h2>
        <DataTable columns={columns} rows={rows} empty="No scraper activity yet" />
      </div>
      <ZileanPanel />
    </div>
  );
}
