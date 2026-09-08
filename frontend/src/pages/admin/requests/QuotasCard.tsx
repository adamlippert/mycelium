import { Link } from 'react-router-dom';
import type { QuotaRow } from '../../../api';

export function QuotasCard({ rows }: { rows: QuotaRow[] }) {
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h3 className="text-[11px] font-semibold uppercase tracking-widest text-muted">Quotas</h3>
      <p className="mt-0.5 text-xs text-muted">Requests this month against each user's monthly cap.</p>
      {rows.length === 0 ? <p className="mt-3 text-sm text-muted">No users to show.</p> : (
        <ul className="mt-3 space-y-1 text-sm">
          {rows.map((r) => {
            const atCap = !r.unlimited && r.used >= r.limit;
            return (
              <li key={r.user_id} className="flex flex-wrap items-center gap-2">
                <span className="w-32 font-medium">{r.username}</span>
                {r.unlimited
                  ? <span className="text-muted">unlimited</span>
                  : <span className={atCap ? 'text-danger' : ''}>{r.used} of {r.limit}</span>}
                {!r.unlimited && !atCap && <span className="text-xs text-muted">{r.remaining} left</span>}
                {!r.unlimited && <span className="text-xs text-muted">resets {r.resets_at.slice(0, 10)}</span>}
                {r.paused && <span className="rounded bg-warn/20 px-1.5 py-0.5 text-[10px] font-semibold text-warn">auto-approve paused</span>}
              </li>
            );
          })}
        </ul>
      )}
      <Link to={{ hash: 'users' }} className="mt-3 inline-block text-xs text-accent-light hover:underline">Edit quotas in Users</Link>
    </section>
  );
}
