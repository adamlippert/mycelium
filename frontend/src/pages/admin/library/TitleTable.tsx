import type { LibraryRow } from '../../../api';
import { Pill, statusLabel, statusToPillState } from '../../../components/primitives';

function Badge({ title, tone, children }: { title: string; tone: 'danger' | 'warn' | 'ok' | 'muted'; children: React.ReactNode }) {
  const cls = { danger: 'bg-danger/20 text-danger', warn: 'bg-warn/20 text-warn', ok: 'bg-ok/20 text-ok', muted: 'bg-white/10 text-muted' }[tone];
  return <span title={title} className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${cls}`}>{children}</span>;
}

export function TitleTable({ rows, sort, order, onSort, selected, onSelect, onSelectAll, onOpen, loading }: {
  rows: LibraryRow[]; sort: string; order: 'asc' | 'desc'; onSort: (col: string) => void;
  selected: Set<string>; onSelect: (row: LibraryRow, on: boolean) => void; onSelectAll: (on: boolean) => void;
  onOpen: (imdb: string) => void; loading: boolean;
}) {
  const header = (key: string, label: string) => (
    <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted">
      <button type="button" aria-label={`Sort by ${label.toLowerCase()}`} onClick={() => onSort(key)} className="hover:text-body">
        {label}{sort === key ? (order === 'asc' ? ' ↑' : ' ↓') : ''}
      </button>
    </th>
  );
  const allOn = rows.length > 0 && rows.every((r) => selected.has(r.imdb_id));
  return (
    <div className={`overflow-x-auto rounded-xl border border-border ${loading ? 'opacity-60' : ''}`}>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            <th className="px-3 py-2"><input type="checkbox" aria-label="Select all on this page" checked={allOn} onChange={(e) => onSelectAll(e.target.checked)} /></th>
            {header('title', 'Title')}{header('status', 'Status')}
            <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted">Release</th>
            {header('requester', 'Requester')}
            <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted">Flags</th>
            {header('updated', 'Updated')}
            {header('created', 'Added')}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.imdb_id} className="cursor-pointer border-b border-border last:border-0 hover:bg-white/[0.03]" onClick={() => onOpen(r.imdb_id)}>
              <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                <input type="checkbox" aria-label={`Select ${r.title}`} checked={selected.has(r.imdb_id)} onChange={(e) => onSelect(r, e.target.checked)} />
              </td>
              <td className="px-3 py-2">
                <div className="font-medium">
                  <span aria-hidden="true">{r.media_type === 'movie' ? '\u{1F3AC}' : '\u{1F4FA}'}</span>
                  <span className="sr-only">{r.media_type === 'movie' ? 'movie' : 'series'}</span>
                  {' '}<span>{r.title}</span>
                </div>
                <div className="font-mono text-[10px] text-muted">{r.imdb_id}</div>
              </td>
              <td className="px-3 py-2">
                <Pill state={statusToPillState(r.status)}>{statusLabel(r.status)}</Pill>
                {r.error && <div className="mt-1 max-w-xs truncate text-[11px] text-muted" title={r.error}>{r.error}</div>}
              </td>
              <td className="px-3 py-2 font-mono text-[11px] text-muted">{[r.quality, r.source].filter(Boolean).join(' ')}</td>
              <td className="px-3 py-2 text-xs">{r.requester}</td>
              <td className="space-x-1 px-3 py-2">
                {r.playability && <Badge title={r.playability.last_fail_reason || r.playability.status} tone={r.playability.status === 'degraded' ? 'danger' : 'warn'}>play</Badge>}
                {r.missing_episodes > 0 && <Badge title={`${r.missing_episodes} missing episodes`} tone="warn">{r.missing_episodes} missing</Badge>}
                {r.retry && <Badge title={`retry attempt ${r.retry.attempt}`} tone="warn">retry {r.retry.attempt}</Badge>}
                {r.arr_mirrored && <Badge title="mirrored in the arr" tone="ok">arr</Badge>}
                {r.in_torbox && <Badge title="in TorBox" tone="muted">tb</Badge>}
              </td>
              <td className="px-3 py-2 text-xs text-muted">{r.updated_at.slice(0, 16)}</td>
              <td className="px-3 py-2 text-xs text-muted">{r.created_at.slice(0, 10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
