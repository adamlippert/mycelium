// Ten content steps (Welcome and Done are bookends, not rail entries - see
// the report's "12 panes, not 10" deviation note). Filtered to the first six
// in Lite mode, mirroring setup.html's totalVisible = STEPS - 4.
const CONTENT_STEPS: { n: number; label: string }[] = [
  { n: 1, label: 'TorBox' },
  { n: 2, label: 'Jellyfin' },
  { n: 3, label: 'Seerr' },
  { n: 4, label: 'Quality' },
  { n: 5, label: 'Catbox' },
  { n: 6, label: 'Notify' },
  { n: 7, label: 'Trakt' },
  { n: 8, label: 'Subtitles' },
  { n: 9, label: 'Zilean' },
  { n: 10, label: 'Radarr' },
];
const LITE_VISIBLE_MAX = 6;

export default function StepRail({ step, lite }: { step: number; lite: boolean }) {
  const visible = lite ? CONTENT_STEPS.filter((s) => s.n <= LITE_VISIBLE_MAX) : CONTENT_STEPS;
  return (
    <div className="flex items-center" role="list" aria-label="setup steps">
      {visible.map((s, i) => {
        const done = step > s.n;
        const active = step === s.n;
        return (
          <div key={s.n} className="flex min-w-0 flex-1 items-center" role="listitem">
            <div className="flex w-14 flex-none flex-col items-center gap-1.5">
              <span
                className={`flex h-7 w-7 flex-none items-center justify-center rounded-full text-[11px] font-semibold ${
                  done
                    ? 'border border-ok/45 bg-ok/20 text-ok'
                    : active
                      ? 'border border-accent-light bg-accent text-white shadow-[0_0_0_4px_rgba(97,82,223,0.18)]'
                      : 'border border-border bg-white/[0.04] text-muted'
                }`}
              >
                {done ? '✓' : s.n}
              </span>
              <span className={`text-[10px] tracking-wide ${active ? 'text-body' : 'text-muted'}`}>
                {s.label}
              </span>
            </div>
            {i < visible.length - 1 && (
              <div className={`mb-[18px] h-px flex-1 ${done ? 'bg-ok/40' : 'bg-border'}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}
