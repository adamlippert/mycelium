export function Chip({
  label,
  selected = false,
  onClick,
  onRemove,
}: {
  label: string;
  selected?: boolean;
  onClick?: () => void;
  onRemove?: () => void;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs font-medium ${
        selected
          ? 'bg-accent border-accent text-white'
          : 'border-border text-muted hover:text-body'
      }`}
      style={selected ? undefined : { background: 'var(--surface-subtle)' }}
    >
      <button type="button" onClick={onClick} aria-pressed={onClick ? selected : undefined}>
        {label}
      </button>
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={`Remove ${label}`} className="opacity-60 hover:opacity-100">
          &times;
        </button>
      )}
    </span>
  );
}
