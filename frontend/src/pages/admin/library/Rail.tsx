import { Button, MultiSelect, Select } from '../../../components/primitives';
import { PROBLEMS, STATUSES, VIEWS } from './state';
import type { LibraryState } from './state';

const VIEW_LABEL: Record<string, string> = {
  all: 'All', attention: 'Needs attention', wanted: 'Wanted', queue: 'Queue', incomplete: 'Incomplete series', unmirrored: 'Unmirrored',
};
const STATUS_LABEL: Record<string, string> = { success: 'In library', wanted: 'Wanted', upcoming: 'Upcoming', failed: 'Failed', pending: 'Processing' };
const PROBLEM_LABEL: Record<string, string> = {
  failed: 'Failed', wanted: 'Wanted', unplayable: 'Unplayable', missing_episodes: 'Missing episodes',
  in_retry_queue: 'In retry queue', no_requester: 'No requester', not_mirrored: 'Not mirrored',
};

export function Rail({ state, counts, users, mirrorOn, onChange }: {
  state: LibraryState; counts: Record<string, number>; users: { id: number; username: string }[];
  mirrorOn: boolean; onChange: (patch: Partial<LibraryState>) => void;
}) {
  const views = VIEWS.filter((v) => v !== 'unmirrored' || mirrorOn);
  return (
    <aside className="space-y-4">
      <nav aria-label="Library views" className="space-y-0.5">
        {views.map((v) => (
          <button key={v} type="button" onClick={() => onChange({ view: v, page: 1 })} aria-current={state.view === v ? 'page' : undefined}
            className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm ${state.view === v ? 'bg-white/[0.08] text-white' : 'text-muted hover:text-body'}`}>
            <span>{VIEW_LABEL[v]}</span>
            <span className="text-xs text-muted">{counts[v] ?? ''}</span>
          </button>
        ))}
      </nav>
      <div className="space-y-2">
        <input type="search" aria-label="Search titles" placeholder="Title, imdb id or hash" value={state.q}
          onChange={(e) => onChange({ q: e.target.value, page: 1 })} className="w-full rounded border border-border bg-bg px-2 py-1.5 text-xs" />
        <Select label="Type" value={state.type} placeholder="Any type" onChange={(v) => onChange({ type: v, page: 1 })}
          options={[{ value: 'movie', label: 'Movies' }, { value: 'series', label: 'Series' }]} className="w-full" />
        <MultiSelect label="Status" value={state.status} onChange={(v) => onChange({ status: v, page: 1 })}
          options={STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] }))} />
        <Select label="Problem" value={state.problem} placeholder="Any problem" onChange={(v) => onChange({ problem: v, page: 1 })}
          options={PROBLEMS.map((p) => ({ value: p, label: PROBLEM_LABEL[p] }))} className="w-full" />
        <Select label="Requester" value={state.requester} placeholder="Anyone" onChange={(v) => onChange({ requester: v, page: 1 })}
          options={[{ value: 'auto', label: 'Automatic' }, ...users.map((u) => ({ value: String(u.id), label: u.username }))]} className="w-full" />
        <Select label="Added" value={state.added} placeholder="Any time" onChange={(v) => onChange({ added: v, page: 1 })}
          options={[{ value: '24h', label: 'Last 24 hours' }, { value: '7d', label: 'Last 7 days' }, { value: '30d', label: 'Last 30 days' }]} className="w-full" />
        {(state.q || state.type || state.status.length || state.problem || state.requester || state.added) ? (
          <Button variant="ghost" onClick={() => onChange({ q: '', type: '', status: [], problem: '', requester: '', added: '', page: 1 })}>Clear filters</Button>
        ) : null}
      </div>
    </aside>
  );
}
