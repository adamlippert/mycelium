const GLOW: Record<string, string> = {
  accent: 'rgba(97,82,223,0.5)',
  ok: 'rgba(37,140,96,0.4)',
  warn: 'rgba(198,178,83,0.4)',
  danger: 'rgba(209,71,71,0.4)',
};

export function StatTile({
  value,
  label,
  sub,
  glow,
}: {
  value: string;
  label: string;
  sub?: string;
  glow?: 'accent' | 'ok' | 'warn' | 'danger';
}) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-border bg-card p-4">
      {glow && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -right-5 -top-8 h-20 w-28 rounded-full opacity-50 blur-[38px]"
          style={{ background: GLOW[glow] }}
        />
      )}
      <div className="relative font-mono text-2xl font-semibold text-body">{value}</div>
      <div className="relative mt-1 text-xs text-muted">{label}</div>
      {sub && <div className="relative mt-1 text-[11px] text-muted">{sub}</div>}
    </div>
  );
}
