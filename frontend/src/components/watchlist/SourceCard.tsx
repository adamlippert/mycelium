import { Card, Pill } from '../primitives';

export function SourceCard({
  abbr,
  name,
  detail,
  connected,
  onSync,
  syncing = false,
}: {
  abbr: string;
  name: string;
  detail: string;
  connected: boolean;
  onSync?: () => void;
  syncing?: boolean;
}) {
  return (
    <Card className="flex items-center gap-3">
      <span
        className="flex h-9 w-9 flex-none items-center justify-center rounded-lg border font-mono text-[11px] font-bold"
        style={{
          background: 'rgba(97,82,223,0.15)',
          borderColor: 'rgba(159,146,255,0.3)',
          color: '#c7c2ff',
        }}
      >
        {abbr}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="text-sm font-medium text-body">{name}</span>
          <Pill state={connected ? 'ready' : 'lazy'}>{connected ? 'Connected' : 'Not connected'}</Pill>
        </span>
        {detail && <span className="mt-0.5 block truncate text-[11px] text-muted">{detail}</span>}
      </span>
      {onSync && (
        <button
          type="button"
          onClick={onSync}
          disabled={syncing}
          className="flex-none rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-body
                     hover:border-accent-light/50 disabled:opacity-50"
        >
          {syncing ? 'Syncing...' : 'Sync now'}
        </button>
      )}
    </Card>
  );
}
