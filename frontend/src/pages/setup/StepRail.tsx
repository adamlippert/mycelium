/** The content steps as a rail; `current` is the index of the active step,
 * or steps.length once past them (account and done bookends). */
export default function StepRail({ steps, current }: { steps: { id: string; title: string }[]; current: number }) {
  return (
    <div className="flex items-center" role="list" aria-label="setup steps">
      {steps.map((s, i) => {
        const done = current > i;
        const active = current === i;
        return (
          <div key={s.id} className="flex min-w-0 flex-1 items-center" role="listitem">
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
                {done ? '✓' : i + 1}
              </span>
              <span className={`max-w-[4.5rem] truncate text-[10px] tracking-wide ${active ? 'text-body' : 'text-muted'}`} title={s.title}>
                {s.title}
              </span>
            </div>
            {i < steps.length - 1 && <div className={`mb-[18px] h-px flex-1 ${done ? 'bg-ok/40' : 'bg-border'}`} />}
          </div>
        );
      })}
    </div>
  );
}
