import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import type { LogLine } from '../../api';
import { Chip } from '../../components/primitives';

// Refresh policy: this is a live operational tail (the closest thing this
// admin has to a terminal), not a dashboard metric, so a sub-10s cadence is
// justified here specifically. It only runs while this component is mounted
// - hash-switching to another admin tab unmounts Logs and its query along
// with it - and React Query's refetchIntervalInBackground default (false)
// keeps it from polling a backgrounded browser tab. Exported so the test can
// pin the exact cadence instead of re-typing the literal.
export const LOGS_POLL_MS = 5000;

const LEVELS = ['All', 'INFO', 'WARNING', 'ERROR'] as const;
type LevelFilter = (typeof LEVELS)[number];

function levelClass(level: string): string {
  if (level === 'INFO') return 'text-ok';
  if (level === 'WARNING') return 'text-warn';
  if (level === 'ERROR') return 'text-danger';
  return 'text-muted';
}

export default function Logs() {
  const [level, setLevel] = useState<LevelFilter>('All');
  // Ported from the Jinja "Auto: ON/OFF" button - lets the operator pause
  // the tail without leaving the tab (e.g. to read a burst of lines in peace).
  const [auto, setAuto] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const { data, isLoading } = useQuery({
    queryKey: ['admin-logs', level],
    queryFn: () => api.adminLogs(200, level === 'All' ? undefined : level),
    refetchInterval: auto ? LOGS_POLL_MS : false,
  });

  const lines: LogLine[] = data?.lines ?? [];

  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [lines]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop <= el.clientHeight + 40;
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold">Logs</h2>
        <div className="flex flex-wrap items-center gap-2">
          {LEVELS.map((l) => (
            <Chip key={l} label={l} selected={level === l} onClick={() => setLevel(l)} />
          ))}
          <button
            type="button"
            onClick={() => setAuto((a) => !a)}
            className="rounded border border-border px-3 py-1.5 text-xs text-muted hover:bg-bg"
          >
            Auto: {auto ? 'ON' : 'OFF'}
          </button>
        </div>
      </div>
      {isLoading ? (
        <p className="text-xs text-muted">Loading...</p>
      ) : (
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="h-[60vh] overflow-y-auto rounded-xl border border-border bg-card p-3 font-mono text-xs"
        >
          {lines.length === 0 ? (
            <p className="text-muted">No log lines</p>
          ) : (
            lines.map((l, i) => (
              <div key={i} className="whitespace-pre-wrap text-muted">
                <span>{l.time}</span> <span className={levelClass(l.level)}>{l.level}</span>{' '}
                <span>[{l.name}]</span> <span className="text-body">{l.msg}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
