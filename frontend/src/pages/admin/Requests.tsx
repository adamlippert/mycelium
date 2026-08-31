import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api';
import type { GenreRule, RequestRow } from '../../api';
import type { UserRequest } from '../../types';
import { Card, DataTable, GenreRuleRows, Pill, statusLabel, statusToPillState } from '../../components/primitives';
import type { Column } from '../../components/primitives';

export default function Requests() {
  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-3 text-lg font-bold">Pending approvals</h2>
        <PendingApprovalsPanel />
      </section>
      <section>
        <h2 className="mb-3 text-lg font-bold">All requests</h2>
        <AllRequestsPanel />
      </section>
      <AutoApprovePanel />
    </div>
  );
}

function PendingApprovalsPanel() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ['user-requests', 'pending'],
    queryFn: () => api.userRequests('pending'),
  });
  const approveMut = useMutation({
    mutationFn: (id: number) => api.approveRequest(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['user-requests'] });
      qc.invalidateQueries({ queryKey: ['requests-all'] });
    },
  });
  const denyMut = useMutation({
    mutationFn: ({ id, note }: { id: number; note?: string }) => api.denyRequest(id, note),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['user-requests'] });
      qc.invalidateQueries({ queryKey: ['requests-all'] });
    },
  });

  const rows = data?.items ?? [];

  const columns: Column<UserRequest>[] = [
    {
      key: 'user',
      header: 'User',
      render: (r) => <span className="font-medium">{r.username || `user #${r.user_id}`}</span>,
    },
    { key: 'title', header: 'Title', render: (r) => r.title },
    { key: 'type', header: 'Type', render: (r) => <span className="text-muted">{r.media_type}</span> },
    {
      key: 'imdb',
      header: 'IMDB',
      render: (r) => (
        <a
          href={`https://www.imdb.com/title/${r.imdb_id}/`}
          target="_blank"
          rel="noopener noreferrer"
          className="font-mono text-xs text-accent hover:underline"
        >
          {r.imdb_id}
        </a>
      ),
    },
    {
      key: 'requested',
      header: 'Requested',
      render: (r) => <span className="text-xs text-muted">{r.created_at}</span>,
    },
    {
      key: 'actions',
      header: 'Action',
      align: 'right',
      render: (r) => (
        <>
          <button
            type="button"
            onClick={() => approveMut.mutate(r.id)}
            disabled={approveMut.isPending}
            className="rounded bg-ok/20 px-3 py-1 text-xs text-ok hover:bg-ok/30 disabled:opacity-50"
          >
            Approve
          </button>
          <button
            type="button"
            onClick={() => denyMut.mutate({ id: r.id, note: prompt('Reason?') || '' })}
            disabled={denyMut.isPending}
            className="ml-2 rounded bg-danger/20 px-3 py-1 text-xs text-danger hover:bg-danger/30 disabled:opacity-50"
          >
            Deny
          </button>
        </>
      ),
    },
  ];

  return <DataTable columns={columns} rows={rows} empty="No requests awaiting review" />;
}

const ALL_REQUESTS_PAGE_SIZE = 50;

function AllRequestsPanel() {
  const qc = useQueryClient();
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const { data } = useQuery({ queryKey: ['requests-all'], queryFn: api.requestsAll });
  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deleteRequest(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['requests-all'] }),
  });
  const purgeMut = useMutation({
    mutationFn: (id: number) => api.purgeRequest(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['requests-all'] }),
  });

  const allRows = data?.items ?? [];
  const q = query.trim().toLowerCase();
  const filtered = q
    ? allRows.filter((r) => r.title.toLowerCase().includes(q) || r.imdb_id.toLowerCase().includes(q))
    : allRows;
  // Only one page goes into the DOM; the endpoint returns up to 5,000 rows
  // and mounting them all as <tr> nodes froze the tab.
  const totalPages = Math.max(1, Math.ceil(filtered.length / ALL_REQUESTS_PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const rows = filtered.slice((safePage - 1) * ALL_REQUESTS_PAGE_SIZE, safePage * ALL_REQUESTS_PAGE_SIZE);

  const columns: Column<RequestRow>[] = [
    { key: 'title', header: 'Title', render: (r) => <span className="font-medium">{r.title || '-'}</span> },
    {
      key: 'imdb',
      header: 'IMDB',
      render: (r) => <span className="font-mono text-xs text-muted">{r.imdb_id || '-'}</span>,
    },
    { key: 'type', header: 'Type', render: (r) => <span className="text-muted">{r.media_type || '-'}</span> },
    {
      key: 'status',
      header: 'Status',
      render: (r) => {
        const st = r.status || 'pending';
        return <Pill state={statusToPillState(st)}>{statusLabel(st)}</Pill>;
      },
    },
    {
      key: 'added',
      header: 'Added',
      render: (r) => <span className="text-xs text-muted">{(r.created_at || '').slice(0, 16)}</span>,
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (r) => (
        <>
          <button
            type="button"
            title="Forget the request record. Keeps the files in your library."
            onClick={() => {
              if (confirm(`Forget the request "${r.title}"?\n\nThe files stay in your library.`)) {
                deleteMut.mutate(r.id);
              }
            }}
            disabled={deleteMut.isPending}
            className="rounded border border-border px-3 py-1 text-xs hover:bg-bg disabled:opacity-50"
          >
            Delete
          </button>
          <button
            type="button"
            title="Delete the .strm files too. Removes the title from Jellyfin/Plex."
            onClick={() => {
              if (
                confirm(
                  `Remove "${r.title}" from the library?\n\nThis deletes its .strm files and it will disappear from Jellyfin and Plex. This cannot be undone.`,
                )
              ) {
                purgeMut.mutate(r.id);
              }
            }}
            disabled={purgeMut.isPending}
            className="ml-2 rounded bg-danger/20 px-3 py-1 text-xs text-danger hover:bg-danger/30 disabled:opacity-50"
          >
            Remove from library
          </button>
        </>
      ),
    },
  ];

  return (
    <div className="space-y-3">
      <input
        type="text"
        value={query}
        onChange={(e) => { setQuery(e.target.value); setPage(1); }}
        placeholder="Search..."
        className="w-full max-w-sm rounded border border-border bg-bg px-3 py-2 text-sm"
      />
      <DataTable columns={columns} rows={rows} empty="No requests" />
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={safePage === 1}
            className="rounded border border-border px-3 py-1 text-sm text-muted hover:text-white disabled:opacity-30 transition"
          >
            Prev
          </button>
          <span className="text-sm text-muted">{safePage} / {totalPages}</span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={safePage === totalPages}
            className="rounded border border-border px-3 py-1 text-sm text-muted hover:text-white disabled:opacity-30 transition"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function AutoApprovePanel() {
  const qc = useQueryClient();
  const [msg, setMsg] = useState('');
  const { data } = useQuery({ queryKey: ['auto-approve-rules'], queryFn: api.autoApproveGenreRules });
  const { data: movieGenres } = useQuery({ queryKey: ['genres', 'movie'], queryFn: () => api.genres('movie') });
  const { data: tvGenres } = useQuery({ queryKey: ['genres', 'tv'], queryFn: () => api.genres('tv') });

  const [rules, setRules] = useState<GenreRule[] | null>(null);
  const effectiveRules = rules ?? data?.rules ?? [];

  const saveMutation = useMutation({
    mutationFn: (r: GenreRule[]) => api.setAutoApproveGenreRules(r),
    onSuccess: () => { setMsg('Saved.'); qc.invalidateQueries({ queryKey: ['auto-approve-rules'] }); },
    onError: (e: Error) => setMsg(`Error: ${e.message}`),
  });
  const runMutation = useMutation({
    mutationFn: api.runAutoApproveNow,
    onSuccess: () => setMsg('Started in the background - check logs for progress.'),
    onError: (e: Error) => setMsg(`Error: ${e.message}`),
  });

  const addRule = () => {
    const genres = movieGenres?.genres || [];
    const first = genres[0];
    setRules([
      ...effectiveRules,
      {
        media_type: 'movie', genre_id: first?.id || 0, genre_name: first?.name || '',
        year_from: null, year_to: null, enabled: true,
      },
    ]);
  };

  const updateRule = (i: number, patch: Partial<GenreRule>) => {
    const next = effectiveRules.map((r, idx) => (idx === i ? { ...r, ...patch } : r));
    setRules(next);
  };

  const removeRule = (i: number) => {
    setRules(effectiveRules.filter((_, idx) => idx !== i));
  };

  return (
    <section>
      <h2 className="mb-3 text-lg font-bold">Auto-approve (genres + favorite actors)</h2>
      <Card className="space-y-4">
        <p className="text-sm text-muted">
          Automatically request titles matching enabled genre rules (year-ranged) and any
          user&apos;s followed actors, up to the daily caps in Settings &gt; Auto-approve.
        </p>

        <GenreRuleRows
          rules={effectiveRules}
          movieGenres={movieGenres?.genres || []}
          tvGenres={tvGenres?.genres || []}
          onUpdate={updateRule}
          onRemove={removeRule}
        />

        <div className="flex flex-wrap gap-2">
          <button onClick={addRule} className="rounded border border-border px-3 py-1.5 text-sm hover:bg-bg">
            + Add genre rule
          </button>
          <button
            onClick={() => saveMutation.mutate(effectiveRules)}
            disabled={saveMutation.isPending}
            className="rounded bg-accent px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
          >
            {saveMutation.isPending ? 'Saving...' : 'Save rules'}
          </button>
          <button
            onClick={() => runMutation.mutate()}
            disabled={runMutation.isPending}
            className="rounded border border-border px-3 py-1.5 text-sm hover:bg-bg disabled:opacity-50"
          >
            Run now
          </button>
        </div>

        {msg && <div className="font-mono text-xs text-muted">{msg}</div>}
      </Card>
    </section>
  );
}
