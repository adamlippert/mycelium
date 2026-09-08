import { Button, Select } from '../../../components/primitives';
import { VIEWS } from './state';
import type { RequestsState } from './state';

const VIEW_LABEL: Record<string, string> = { pending: 'Pending', approved: 'Approved', denied: 'Denied', all: 'All' };

export function Rail({ state, counts, users, onChange }: {
  state: RequestsState; counts: Record<string, number>; users: { id: number; username: string }[];
  onChange: (patch: Partial<RequestsState>) => void;
}) {
  const active = state.q || state.user || state.type || state.added;
  return (
    <aside className="space-y-4">
      <nav aria-label="Request views" className="space-y-0.5">
        {VIEWS.map((v) => (
          <button key={v} type="button" onClick={() => onChange({ view: v, page: 1 })} aria-current={state.view === v ? 'page' : undefined}
            className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm ${state.view === v ? 'bg-white/[0.08] text-white' : 'text-muted hover:text-body'}`}>
            <span>{VIEW_LABEL[v]}</span>
            <span className="text-xs text-muted">{counts[v] ?? ''}</span>
          </button>
        ))}
      </nav>
      <div className="space-y-2">
        <input type="search" aria-label="Search requests" placeholder="Title or imdb id" value={state.q}
          onChange={(e) => onChange({ q: e.target.value, page: 1 })} className="w-full rounded border border-border bg-bg px-2 py-1.5 text-xs" />
        <Select label="User" value={state.user} placeholder="Anyone" onChange={(v) => onChange({ user: v, page: 1 })}
          options={users.map((u) => ({ value: String(u.id), label: u.username }))} className="w-full" />
        <Select label="Type" value={state.type} placeholder="Any type" onChange={(v) => onChange({ type: v, page: 1 })}
          options={[{ value: 'movie', label: 'Movies' }, { value: 'series', label: 'Series' }]} className="w-full" />
        <Select label="Added" value={state.added} placeholder="Any time" onChange={(v) => onChange({ added: v, page: 1 })}
          options={[{ value: '24h', label: 'Last 24 hours' }, { value: '7d', label: 'Last 7 days' }, { value: '30d', label: 'Last 30 days' }]} className="w-full" />
        {active ? <Button variant="ghost" onClick={() => onChange({ q: '', user: '', type: '', added: '', page: 1 })}>Clear filters</Button> : null}
      </div>
    </aside>
  );
}
