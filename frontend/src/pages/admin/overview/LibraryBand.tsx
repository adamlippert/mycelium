import { Link } from 'react-router-dom';
import type { OverviewPayload, TorBoxUsage } from '../../../api';
import { Card, StatTile } from '../../../components/primitives';
import { formatGiB } from './format';

const nf = new Intl.NumberFormat('en-US');

export function LibraryBand({ library, torbox, loading }: {
  library: OverviewPayload['library'] | undefined; torbox: TorBoxUsage | undefined; loading: boolean;
}) {
  const v = (s: string) => (loading || !library ? '-' : s);
  const q = Object.entries(library?.qualities ?? {}).sort((a, b) => b[1] - a[1]);
  const total = q.reduce((s, [, n]) => s + n, 0) || 1;
  const c = library?.consistency;
  return (
    <div className="grid gap-3 lg:grid-cols-3">
      <Card>
        <div className="mb-3 text-sm font-semibold text-body">Size</div>
        <div className="grid grid-cols-2 gap-2.5">
          <StatTile value={v(nf.format(library?.movies ?? 0))} label="Movies" />
          <StatTile value={v(nf.format(library?.episodes ?? 0))} label="Episodes" sub={library ? `${library.series} series` : undefined} />
          <StatTile value={v(String(library?.wanted ?? 0))} label="Wanted" sub={library ? `${library.upcoming} upcoming` : undefined} />
          <StatTile value={torbox ? formatGiB(torbox.usage.total_bytes) : 'unavailable'} label="On TorBox"
            sub={torbox ? `${torbox.usage.torrent_count} torrents` : undefined} />
        </div>
      </Card>
      <Card>
        <div className="mb-3 text-sm font-semibold text-body">Quality of what landed</div>
        {q.length === 0 ? <p className="text-xs text-muted">No data yet</p> : (
          <div className="space-y-1.5 text-xs">
            {q.map(([label, n]) => (
              <div key={label} className="grid grid-cols-[56px_1fr_40px] items-center gap-2.5">
                <span className="text-muted">{label}</span>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/5">
                  <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round((100 * n) / total)}%` }} />
                </div>
                <span className="text-right font-mono text-body">{Math.round((100 * n) / total)}%</span>
              </div>
            ))}
          </div>
        )}
        <p className="mt-2 text-[11px] text-white/30">Requests that succeeded, by resolution.</p>
      </Card>
      <Card>
        <div className="mb-3 text-sm font-semibold text-body">Consistency</div>
        {!c ? <p className="text-xs text-muted">{loading ? 'Loading…' : 'unavailable'}</p> : (
          <div className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-xs">
            <span className="text-muted">DB items</span><span className="text-right font-mono text-body">{nf.format(c.db_items)}</span>
            <span className="text-muted">strm without DB row</span><span className={`text-right font-mono ${c.strm_without_db > 0 ? 'text-warn' : 'text-body'}`}>{c.strm_without_db}</span>
            <span className="text-muted">DB row without strm</span><span className={`text-right font-mono ${c.db_without_strm > 0 ? 'text-warn' : 'text-body'}`}>{c.db_without_strm}</span>
            <span className="text-muted">Arr mirror</span><span className="text-right font-mono text-body">{c.arr_mirrored}/{c.arr_total}</span>
            <span className="text-muted">Last cleanup</span>
            <span className="text-right font-mono text-body">{c.last_cleanup ? `${c.last_cleanup.ran_at.slice(11, 16)}, ${c.last_cleanup.deleted} removed` : 'never'}</span>
          </div>
        )}
        <Link to={{ hash: 'maintenance' }} className="mt-3 block text-[11px] text-accent-light hover:underline">Run integrity check</Link>
      </Card>
    </div>
  );
}
