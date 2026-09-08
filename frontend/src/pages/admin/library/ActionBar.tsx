import { useState } from 'react';
import { api } from '../../../api';
import type { LibraryRow } from '../../../api';
import { Button } from '../../../components/primitives';

type Op = { label: string; confirm?: (n: number) => string; run: (r: LibraryRow) => Promise<unknown>; queueOnly?: boolean };

const OPS: Op[] = [
  { label: 'Retry', run: (r) => api.retryRequest(r.id) },
  { label: 'Re-resolve', run: async (r) => { const d = await api.libraryDetail(r.imdb_id); await Promise.all(d.items.map((i) => api.reResolve(i.token))); } },
  { label: 'Mirror to arr', run: (r) => api.libraryAction(`/ui/api/library/${r.imdb_id}/mirror`).then((x) => { if (!x.ok) throw new Error(x.message); }) },
  { label: 'Run now', queueOnly: true, run: (r) => api.libraryAction(`/ui/api/library/${r.imdb_id}/retry-now`).then((x) => { if (!x.ok) throw new Error(x.message); }) },
  { label: 'Drop from queue', queueOnly: true, run: (r) => api.libraryAction(`/ui/api/library/${r.imdb_id}/drop-retry`).then((x) => { if (!x.ok) throw new Error(x.message); }) },
  { label: 'Remove from library', confirm: (n) => `Remove ${n} title${n === 1 ? '' : 's'} from the library? Their files, monitoring and requests go too.`, run: (r) => api.purgeRequest(r.id) },
];

export function ActionBar({ rows, selected, view, onDone, onClear }: {
  rows: LibraryRow[]; selected: Set<string>; view: string; onDone: () => void; onClear: () => void;
}) {
  const [progress, setProgress] = useState<{ label: string; done: number; total: number; failures: string[] } | null>(null);
  const targets = rows.filter((r) => selected.has(r.imdb_id));
  const run = async (op: Op) => {
    if (op.confirm && !window.confirm(op.confirm(targets.length))) return;
    const failures: string[] = [];
    let done = 0;
    setProgress({ label: op.label, done, total: targets.length, failures });
    for (const r of targets) {
      try { await op.run(r); done += 1; } catch (e: any) { failures.push(`${r.title}: ${e.message}`); }
      setProgress({ label: op.label, done, total: targets.length, failures: [...failures] });
    }
    onDone();
  };
  return (
    <div className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-bg/95 px-4 py-3 backdrop-blur md:left-auto">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-2 text-sm">
        <span className="mr-2">{selected.size} selected</span>
        {OPS.filter((o) => !o.queueOnly || view === 'queue').map((o) => (
          <Button key={o.label} onClick={() => run(o)} disabled={progress !== null && progress.done + progress.failures.length < progress.total}>{o.label}</Button>
        ))}
        <Button variant="ghost" onClick={onClear}>Clear</Button>
        {progress && (
          <span className="ml-auto text-xs text-muted">
            {progress.label}: {progress.done} of {progress.total} done{progress.failures.length ? `, ${progress.failures.length} failed` : ''}
            {progress.failures.map((f) => <span key={f} className="block text-danger">{f}</span>)}
          </span>
        )}
      </div>
    </div>
  );
}
