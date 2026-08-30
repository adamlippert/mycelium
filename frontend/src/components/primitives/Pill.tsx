export const PILL_STATES = ['ready', 'materializing', 'queued', 'failed', 'lazy'] as const;

export type PillState = (typeof PILL_STATES)[number];

export function Pill({ state, children }: { state: PillState; children: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-2 py-1
                 text-[10px] font-medium leading-none tracking-wide"
      style={{
        background: `var(--pill-${state}-bg)`,
        color: `var(--pill-${state}-fg)`,
        borderColor: `var(--pill-${state}-border)`,
      }}
    >
      {children}
    </span>
  );
}
