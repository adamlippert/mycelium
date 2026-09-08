import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { Button, Select } from '../../components/primitives';
import { Rail } from './requests/Rail';
import { RequestTable } from './requests/RequestTable';
import { RowActions } from './requests/RowActions';
import { QuotasCard } from './requests/QuotasCard';
import { AutoApproveCard } from './requests/AutoApproveCard';
import { parseHash, toHash, toQuery } from './requests/state';
import type { RequestsState } from './requests/state';
import { TitleDrawer } from './library/TitleDrawer';

const EMPTY: Record<string, string> = {
  pending: 'No requests waiting for review', approved: 'No approved requests yet',
  denied: 'Nothing denied', all: 'No one has requested anything yet',
};

export default function Requests() {
  const location = useLocation();
  const navigate = useNavigate();
  const [state, setState] = useState<RequestsState>(() => parseHash(location.hash));
  const query = useMemo(() => toQuery(state), [state]);
  const page = useQuery({ queryKey: ['admin-requests', query], queryFn: () => api.adminRequests(query), placeholderData: (p) => p });
  const counts = useQuery({ queryKey: ['admin-request-views'], queryFn: api.adminRequestViews });
  const users = useQuery({ queryKey: ['users'], queryFn: api.users });
  const quotas = useQuery({ queryKey: ['admin-quotas'], queryFn: api.adminQuotas });
  useEffect(() => { navigate({ hash: toHash(state) }, { replace: true }); }, [state, navigate]);
  const update = useCallback((patch: Partial<RequestsState>) => setState((s) => ({ ...s, ...patch })), []);
  const refetchAll = useCallback(() => { page.refetch(); counts.refetch(); quotas.refetch(); }, [page, counts, quotas]);
  const closeDrawer = useCallback(() => update({ open: null }), [update]);
  const onSort = (col: string) => update({ sort: col, order: state.sort === col && state.order === 'asc' ? 'desc' : 'asc', page: 1 });
  const rows = page.data?.rows || [];
  const total = page.data?.total || 0;
  const first = (state.page - 1) * state.perPage + 1;
  const last = Math.min(total, state.page * state.perPage);
  const overQuotaUsers = new Set(
    (quotas.data?.rows || []).filter((r) => !r.unlimited && r.used >= r.limit).map((r) => r.user_id),
  );

  return (
    <div className="grid gap-6 md:grid-cols-[14rem_1fr]">
      <Rail state={state} counts={counts.data?.counts || {}} users={users.data?.users || []} onChange={update} />
      <main className="space-y-3">
        <RequestTable rows={rows} sort={state.sort} order={state.order} onSort={onSort} loading={page.isFetching}
          onOpen={(id) => update({ open: id })}
          renderActions={(r) => <RowActions row={r} overQuota={overQuotaUsers.has(r.user_id)} onDone={refetchAll} />} />
        {!rows.length && !page.isFetching && <p className="text-sm text-muted">{EMPTY[state.view]}</p>}
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          <span>{total ? `${first} to ${last} of ${total}` : ''}</span>
          <div className="flex items-center gap-2">
            <Select label="Rows per page" value={String(state.perPage)} onChange={(v) => update({ perPage: Number(v), page: 1 })}
              options={[25, 50, 100, 200].map((n) => ({ value: String(n), label: `${n} per page` }))} />
            <Button aria-label="Previous page" disabled={state.page <= 1} onClick={() => update({ page: state.page - 1 })}>Prev</Button>
            <Button aria-label="Next page" disabled={last >= total} onClick={() => update({ page: state.page + 1 })}>Next</Button>
          </div>
        </div>
        <QuotasCard rows={quotas.data?.rows || []} />
        <AutoApproveCard />
      </main>
      {state.open && <TitleDrawer key={state.open} imdb={state.open} onClose={closeDrawer} onChanged={refetchAll} />}
    </div>
  );
}
