export function StatusDot({ tone }: { tone: 'ok' | 'warn' | 'danger' }) {
  return (
    <span
      className="block h-[7px] w-[7px] flex-none rounded-full"
      style={{
        background: `var(--dot-${tone})`,
        boxShadow: `0 0 8px var(--dot-${tone})`,
      }}
    />
  );
}
