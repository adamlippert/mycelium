import { useState } from 'react';

const KEY = 'mycelium.overview.';

function readOpen(id: string): boolean {
  try { return localStorage.getItem(KEY + id) === '1'; } catch { return false; }
}

/** A collapsed reference block: closed by default, state remembered per id,
 *  body rendered through a function so its query can be enabled on open. */
export function ReferenceSection({ id, title, hint, children }: {
  id: 'metrics' | 'endpoints' | 'folders'; title: string; hint: string; children: (open: boolean) => React.ReactNode;
}) {
  const [open, setOpen] = useState(() => readOpen(id));
  const toggle = (next: boolean) => {
    setOpen(next);
    try { localStorage.setItem(KEY + id, next ? '1' : '0'); } catch { /* storage unavailable */ }
  };
  return (
    <details open={open} onToggle={(e) => toggle((e.currentTarget as HTMLDetailsElement).open)}
      className="rounded-xl border border-border bg-card">
      <summary
        className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-semibold text-body"
        onClick={(e) => { e.preventDefault(); toggle(!open); }}
      >
        {title}<span className="text-xs font-normal text-white/30">{hint}</span>
      </summary>
      <div className="px-4 pb-4">{children(open)}</div>
    </details>
  );
}
