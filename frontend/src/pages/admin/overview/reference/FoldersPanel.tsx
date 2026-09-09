import type { StorageFolder } from '../../../../api';

export function FoldersPanel({ folders, loading }: { folders: StorageFolder[] | undefined; loading: boolean }) {
  if (loading) return <p className="text-xs text-muted">Loading…</p>;
  const list = folders ?? [];
  if (list.length === 0) return <p className="text-xs text-muted">Empty</p>;
  return (
    <div className="space-y-1">
      {list.slice(0, 15).map((f) => (
        <div key={f.path} className="flex items-center justify-between gap-2 text-xs">
          <span className="truncate text-muted">{f.path}</span>
          <span className="font-mono text-body">{f.count}</span>
        </div>
      ))}
    </div>
  );
}
