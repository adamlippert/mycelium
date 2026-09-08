import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api';
import type { GenreRule } from '../../api';
import type { UserRequest } from '../../types';
import { Card, DataTable, GenreRuleRows } from '../../components/primitives';
import type { Column } from '../../components/primitives';

export default function Requests() {
  return (
    <div className="space-y-8">
      <p className="text-sm text-muted">
        Looking for a title? <Link to={{ hash: 'library' }} className="text-accent-light hover:underline">Open the Library tab.</Link>
      </p>
      <section>
        <h2 className="mb-3 text-lg font-bold">Pending approvals</h2>
        <PendingApprovalsPanel />
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
