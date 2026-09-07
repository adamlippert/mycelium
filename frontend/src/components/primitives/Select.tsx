export type Option = { value: string; label: string };

export function Select({
  value,
  onChange,
  options,
  label,
  placeholder,
  className = '',
}: {
  value: string;
  onChange: (next: string) => void;
  options: Option[];
  label: string;
  placeholder?: string;
  className?: string;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`rounded border border-border bg-bg px-2 py-1 text-xs ${className}`.trim()}
    >
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}
