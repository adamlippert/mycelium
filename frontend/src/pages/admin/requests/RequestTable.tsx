import type { ReactNode } from 'react';
import type { AdminRequestRow } from '../../../api';
import { Pill, statusLabel, statusToPillState } from '../../../components/primitives';

const REQUEST_LABEL: Record<string, string> = { pending: 'Pending', approved: 'Approved', denied: 'Denied' };

export function RequestTable({ rows, sort, order, onSort, onOpen, renderActions, loading }: {
  rows: AdminRequestRow[]; sort: string; order: 'asc' | 'desc'; onSort: (col: string) => void;
  onOpen: (imdb: string) => void; renderActions: (row: AdminRequestRow) => ReactNode; loading: boolean;
}) {
  const th = 'px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted';
  const header = (key: string, label: string) => (
    <th className={th}>
      <button type="button" aria-label={`Sort by ${label.toLowerCase()}`} onClick={() => onSort(key)} className="hover:text-body">
        {label}{sort === key ? (order === 'asc' ? ' ↑' : ' ↓') : ''}
      </button>
    </th>
  );
  return (
    <div className={`overflow-x-auto rounded-xl border border-border ${loading ? 'opacity-60' : ''}`}>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            {header('title', 'Title')}{header('user', 'User')}{header('created', 'Requested')}
            <th className={th}>Status</th><th className={th}>Library</th>
            {header('reviewed', 'Reviewed')}<th className={th}>Note</th><th className={th}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b border-border last:border-0 hover:bg-white/[0.03]">
              <td className="px-3 py-2">
                <button type="button" onClick={() => onOpen(r.imdb_id)} className="text-left font-medium hover:underline">
                  <span aria-hidden="true">{r.media_type === 'movie' ? '\u{1F3AC}' : '\u{1F4FA}'}</span>
                  <span className="sr-only">{r.media_type === 'movie' ? 'movie' : 'series'}</span>
                  {' '}<span>{r.title}</span>
                </button>
                <div className="font-mono text-[10px] text-muted">{r.imdb_id}</div>
              </td>
              <td className="px-3 py-2 text-xs"><span>{r.username}</span></td>
              <td className="px-3 py-2 text-xs text-muted">{r.created_at.slice(0, 16)}</td>
              <td className="px-3 py-2"><Pill state={statusToPillState(r.status)}>{REQUEST_LABEL[r.status] || r.status}</Pill></td>
              <td className="px-3 py-2">
                {r.library_status
                  ? <Pill state={statusToPillState(r.library_status)}>{statusLabel(r.library_status)}</Pill>
                  : <span className="text-xs text-muted">not in library</span>}
              </td>
              <td className="px-3 py-2 text-xs text-muted">{r.reviewer ? <><span>{r.reviewer}</span> {r.reviewed_at?.slice(0, 16)}</> : ''}</td>
              <td className="max-w-[12rem] truncate px-3 py-2 text-xs" title={r.note || ''}>{r.note}</td>
              <td className="px-3 py-2">{renderActions(r)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
