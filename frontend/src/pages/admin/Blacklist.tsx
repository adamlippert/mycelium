import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api';
import type { BlacklistItem } from '../../api';
import { DataTable } from '../../components/primitives';
import type { Column } from '../../components/primitives';

export default function Blacklist() {
  const qc = useQueryClient();
  const [query, setQuery] = useState('');
  const { data } = useQuery({ queryKey: ['blacklist'], queryFn: api.blacklist });
  const clearMut = useMutation({
    mutationFn: (infoHash: string) => api.blacklistClear(infoHash),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['blacklist'] }),
  });

  const allRows = data?.items ?? [];
  const q = query.trim().toLowerCase();
  const rows = q
    ? allRows.filter(
        (i) => i.info_hash.toLowerCase().includes(q) || (i.last_error || '').toLowerCase().includes(q),
      )
    : allRows;

  const columns: Column<BlacklistItem>[] = [
    {
      key: 'hash',
      header: 'Hash',
      render: (i) => (
        <span className="font-mono text-xs" title={i.info_hash}>
          {i.info_hash.slice(0, 16)}...
        </span>
      ),
    },
    { key: 'failures', header: 'Failures', render: (i) => <span className="font-mono">{i.fail_count}</span> },
    {
      key: 'error',
      header: 'Last Error',
      render: (i) => (
        <span
          className="block max-w-xs overflow-hidden text-ellipsis whitespace-nowrap text-xs text-muted"
          title={i.last_error || ''}
        >
          {i.last_error || '-'}
        </span>
      ),
    },
    {
      key: 'try',
      header: 'Last Try',
      render: (i) => <span className="text-xs text-muted">{(i.last_attempt || '').slice(0, 16)}</span>,
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (i) => (
        <button
          type="button"
          onClick={() => {
            if (confirm('Clear blacklist for this hash? Mycelium will try it again next time.')) {
              clearMut.mutate(i.info_hash);
            }
          }}
          disabled={clearMut.isPending}
          className="rounded border border-border px-3 py-1 text-xs hover:bg-bg disabled:opacity-50"
        >
          Clear
        </button>
      ),
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold">Failed-hash Blacklist</h2>
        <span className="text-xs text-muted">Hashes are blacklisted after repeated failed add attempts</span>
      </div>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search..."
        className="w-full max-w-sm rounded border border-border bg-bg px-3 py-2 text-sm"
      />
      <DataTable columns={columns} rows={rows} empty="No blacklisted hashes" />
    </div>
  );
}
