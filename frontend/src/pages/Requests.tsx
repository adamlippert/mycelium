import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { Pill, StatTile } from '../components/primitives';
import type { PillState } from '../components/primitives';
import { QuotaCard } from '../components/requests/QuotaCard';

export default function Requests() {
  const qc = useQueryClient();
  const { data: sessionData } = useQuery({ queryKey: ['session'], queryFn: api.session });
  const isAdmin = sessionData?.user?.role === 'admin';
  const { data, isLoading } = useQuery({ queryKey: ['my-requests'], queryFn: api.myRequests });
  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deleteRequest(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['my-requests'] });
    },
  });
  const purgeMut = useMutation({
    mutationFn: (id: number) => api.purgeRequest(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['my-requests'] });
    },
  });
  if (isLoading) return <div className="text-muted">Loading…</div>;
  const items = data?.items || [];
  const counts = {
    pending: items.filter((r: any) => r.status === 'pending').length,
    approved: items.filter((r: any) => r.status === 'approved').length,
    denied: items.filter((r: any) => r.status === 'denied').length,
  };
  return (
    <div className="space-y-8">
      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <QuotaCard />
        <StatTile value={String(counts.pending)} label="Awaiting review" glow="warn" />
        <StatTile value={String(counts.approved)} label="Approved" glow="ok" />
        <StatTile value={String(counts.denied)} label="Denied" glow="danger" />
      </div>
      {isAdmin && <PendingApprovalsPanel />}
      <section>
        <h2 className="text-lg font-bold mb-3">My requests</h2>
        {items.length === 0 ? (
          <div className="text-center py-8">
            <div className="text-5xl mb-3">📋</div>
            <h2 className="text-lg font-semibold mb-1">No requests yet</h2>
            <p className="text-muted text-sm">Anything you add from Discover shows up here.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs text-muted uppercase border-b border-border">
              <tr>
                <th className="text-left py-2 px-3">Title</th>
                <th className="text-left py-2 px-3">Type</th>
                <th className="text-left py-2 px-3">Approval</th>
                <th className="text-left py-2 px-3">Library</th>
                <th className="text-left py-2 px-3">Requested</th>
                <th className="text-right py-2 px-3"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((r: any) => (
                <tr key={r.id} className="border-b border-border hover:bg-card">
                  <td className="py-2 px-3 font-medium">{r.title}</td>
                  <td className="py-2 px-3 text-muted">{r.media_type}</td>
                  <td className="py-2 px-3">
                    <StatusPill status={r.status} />
                  </td>
                  <td className="py-2 px-3">
                    <LibraryPill status={r.library_status} />
                  </td>
                  <td className="py-2 px-3 text-muted text-xs">{r.created_at}</td>
                  <td className="py-2 px-3 text-right">
                    <button
                      type="button"
                      onClick={() => { if (confirm(`Forget the request "${r.title}"?\n\nThe files stay in your library.`)) deleteMut.mutate(r.id); }}
                      disabled={deleteMut.isPending}
                      className="px-2 py-1 rounded text-xs text-red-400 hover:bg-red-500/10 disabled:opacity-50"
                      title="Forget the request. Keeps the files in your library."
                    >
                      x
                    </button>
                    {isAdmin && (
                      <button
                        type="button"
                        onClick={() => { if (confirm(`Remove "${r.title}" from the library?\n\nThis deletes its .strm files and it will disappear from Jellyfin and Plex. This cannot be undone.`)) purgeMut.mutate(r.id); }}
                        disabled={purgeMut.isPending}
                        className="ml-1 px-2 py-1 rounded text-xs text-red-400 hover:bg-red-500/10 disabled:opacity-50"
                        title="Remove from library (deletes the .strm files)"
                      >
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <FailedRequestsPanel />
    </div>
  );
}

function FailedRequestsPanel() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['failed-requests'], queryFn: api.failedRequests, refetchInterval: 10000 });
  const retryMut = useMutation({
    mutationFn: (id: number) => api.retryRequest(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['failed-requests'] });
    },
  });

  const items = data?.items || [];
  if (items.length === 0) return null;

  return (
    <section>
      <h2 className="text-lg font-bold mb-3 text-red-400">Failed requests</h2>
      <p className="text-muted text-xs mb-3">
        These requests failed to find a stream. The system retries automatically  -  you can also retry manually.
      </p>
      <table className="w-full text-sm">
        <thead className="text-xs text-muted uppercase border-b border-border">
          <tr>
            <th className="text-left py-2 px-3">Title</th>
            <th className="text-left py-2 px-3">Type</th>
            <th className="text-left py-2 px-3">Error</th>
            <th className="text-left py-2 px-3">Updated</th>
            <th className="text-right py-2 px-3">Action</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r: any) => (
            <tr key={r.id} className="border-b border-border hover:bg-card">
              <td className="py-2 px-3 font-medium">{r.title}</td>
              <td className="py-2 px-3 text-muted">{r.media_type}</td>
              <td className="py-2 px-3 text-red-400 text-xs max-w-xs truncate" title={r.error || ''}>
                {r.error || ' - '}
              </td>
              <td className="py-2 px-3 text-muted text-xs">{r.updated_at}</td>
              <td className="py-2 px-3 text-right">
                <button
                  onClick={() => retryMut.mutate(r.id)}
                  disabled={retryMut.isPending}
                  className="px-3 py-1 rounded bg-accent/20 text-accent text-xs hover:bg-accent/30 disabled:opacity-50"
                >
                  ↺ Retry
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function PendingApprovalsPanel() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ['pending-requests'],
    queryFn: () => api.userRequests('pending'),
    refetchInterval: 15000,
  });
  const approveMut = useMutation({
    mutationFn: (id: number) => api.approveRequest(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pending-requests'] });
      qc.invalidateQueries({ queryKey: ['my-requests'] });
    },
  });
  const denyMut = useMutation({
    mutationFn: ({ id, note }: { id: number; note?: string }) => api.denyRequest(id, note),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pending-requests'] });
    },
  });

  const items = data?.items || [];
  if (items.length === 0) return null;

  return (
    <section>
      <h2 className="text-lg font-bold mb-3 text-warn">Pending approvals</h2>
      <p className="text-muted text-xs mb-3">
        These requests need your approval before they are processed.
      </p>
      <table className="w-full text-sm">
        <thead className="text-xs text-muted uppercase border-b border-border">
          <tr>
            <th className="text-left py-2 px-3">User</th>
            <th className="text-left py-2 px-3">Title</th>
            <th className="text-left py-2 px-3">Type</th>
            <th className="text-left py-2 px-3">IMDb</th>
            <th className="text-left py-2 px-3">Date</th>
            <th className="text-right py-2 px-3">Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r: any) => (
            <tr key={r.id} className="border-b border-border hover:bg-card">
              <td className="py-2 px-3 font-medium">{r.username || `user #${r.user_id}`}</td>
              <td className="py-2 px-3">{r.title}</td>
              <td className="py-2 px-3 text-muted">{r.media_type}</td>
              <td className="py-2 px-3">
                <a href={`https://www.imdb.com/title/${r.imdb_id}/`} target="_blank" rel="noreferrer"
                   className="text-accent hover:underline text-xs">{r.imdb_id}</a>
              </td>
              <td className="py-2 px-3 text-muted text-xs">{r.created_at}</td>
              <td className="py-2 px-3 text-right space-x-2">
                <button
                  onClick={() => approveMut.mutate(r.id)}
                  disabled={approveMut.isPending}
                  className="px-3 py-1 rounded bg-ok/20 text-ok text-xs hover:bg-ok/30 disabled:opacity-50"
                >Approve</button>
                <button
                  onClick={() => {
                    const note = prompt('Reason for denial? (optional)');
                    if (note !== null) denyMut.mutate({ id: r.id, note: note || undefined });
                  }}
                  disabled={denyMut.isPending}
                  className="px-2 py-1 rounded bg-red-500/20 text-red-400 text-xs hover:bg-red-500/30 disabled:opacity-50"
                >Deny</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function statusToPillState(status: string): PillState {
  if (status === 'pending') return 'queued';
  if (status === 'approved' || status === 'success' || status === 'available') return 'ready';
  if (status === 'denied' || status === 'failed') return 'failed';
  return 'lazy';
}

function StatusPill({ status }: { status: string }) {
  return <Pill state={statusToPillState(status)}><span className="capitalize">{status}</span></Pill>;
}

function LibraryPill({ status }: { status: string | null }) {
  if (!status) return <span className="text-xs text-muted">--</span>;
  const labels: Record<string, string> = {
    success: 'In library',
    wanted: 'Wanted',
    upcoming: 'Upcoming',
    failed: 'Failed',
    pending: 'Processing',
  };
  return <Pill state={statusToPillState(status)}>{labels[status] || status}</Pill>;
}
