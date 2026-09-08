import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { Button, Select } from '../../components/primitives';
import { Rail } from './library/Rail';
import { TitleTable } from './library/TitleTable';
import { TitleDrawer } from './library/TitleDrawer';
import { ActionBar } from './library/ActionBar';
import { parseHash, toHash, toQuery } from './library/state';
import type { LibraryState } from './library/state';

export default function Library() {
  const location = useLocation();
  const navigate = useNavigate();
  const [state, setState] = useState<LibraryState>(() => parseHash(location.hash));
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const query = useMemo(() => toQuery(state), [state]);
  const page = useQuery({ queryKey: ['library', query], queryFn: () => api.library(query), placeholderData: (p) => p });
  const counts = useQuery({ queryKey: ['library-views'], queryFn: api.libraryViews });
  const users = useQuery({ queryKey: ['users'], queryFn: api.users });

  useEffect(() => { navigate({ hash: toHash(state) }, { replace: true }); }, [state, navigate]);
  const update = (patch: Partial<LibraryState>) => setState((s) => ({ ...s, ...patch }));
  const onSort = (col: string) => update({ sort: col, order: state.sort === col && state.order === 'asc' ? 'desc' : 'asc', page: 1 });

  const rows = page.data?.rows || [];
  const total = page.data?.total || 0;
  const first = (state.page - 1) * state.perPage + 1;
  const last = Math.min(total, state.page * state.perPage);

  return (
    <div className="grid gap-6 pb-24 md:grid-cols-[14rem_1fr]">
      <span data-testid="library-hash" hidden>{toHash(state)}</span>
      <Rail state={state} counts={counts.data?.counts || {}} users={users.data?.users || []} mirrorOn={counts.data?.mirror_on ?? false} onChange={update} />
      <main className="space-y-3">
        <TitleTable rows={rows} sort={state.sort} order={state.order} onSort={onSort} selected={selected} loading={page.isFetching}
          onSelect={(id, on) => setSelected((s) => { const n = new Set(s); on ? n.add(id) : n.delete(id); return n; })}
          onSelectAll={(on) => setSelected((s) => (on
            ? new Set([...s, ...rows.map((r) => r.imdb_id)])
            : new Set([...s].filter((id) => !rows.some((r) => r.imdb_id === id)))))}
          onOpen={(id) => update({ open: id })} />
        {!rows.length && !page.isFetching && (
          <p className="text-sm text-muted">Nothing here. {EMPTY[state.view] || ''}</p>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          <span>{total ? `${first} to ${last} of ${total}` : ''}</span>
          <div className="flex items-center gap-2">
            <Select label="Rows per page" value={String(state.perPage)} onChange={(v) => update({ perPage: Number(v), page: 1 })}
              options={[25, 50, 100, 200].map((n) => ({ value: String(n), label: `${n} per page` }))} />
            <Button aria-label="Previous page" disabled={state.page <= 1} onClick={() => update({ page: state.page - 1 })}>Prev</Button>
            <Button aria-label="Next page" disabled={last >= total} onClick={() => update({ page: state.page + 1 })}>Next</Button>
          </div>
        </div>
        {selected.size > 0 && <ActionBar rows={rows} selected={selected} view={state.view} onDone={() => { page.refetch(); counts.refetch(); }} onClear={() => setSelected(new Set())} />}
      </main>
      {state.open && <TitleDrawer key={state.open} imdb={state.open} onClose={() => update({ open: null })} onChanged={() => { page.refetch(); counts.refetch(); }} />}
    </div>
  );
}

const EMPTY: Record<string, string> = {
  attention: 'Titles land here when they failed, stopped playing, or retried three times.',
  wanted: 'Released titles with no release yet, and titles not out yet.',
  queue: 'Titles the processor is working on, waiting to retry, or still hunting episodes for.',
  incomplete: 'Series with episodes still wanted.',
  unmirrored: 'Titles in the library that Radarr or Sonarr do not have yet.',
};
