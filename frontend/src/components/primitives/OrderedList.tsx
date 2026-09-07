import { Button } from './Button';
import { Select } from './Select';
import type { Option } from './Select';

export function OrderedList({
  value,
  onChange,
  options,
  label,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  options: Option[];
  label: string;
}) {
  const move = (i: number, d: -1 | 1) => {
    const next = [...value];
    const [item] = next.splice(i, 1);
    next.splice(i + d, 0, item);
    onChange(next);
  };
  const unused = options.filter((o) => !value.includes(o.value));
  const name = (v: string) => options.find((o) => o.value === v)?.label ?? v;
  return (
    <div className="w-full max-w-md space-y-1">
      <ol className="space-y-1">
        {value.map((v, i) => (
          <li key={v} className="flex items-center gap-2 rounded border border-border bg-bg px-2 py-1 text-xs">
            <span className="w-4 text-muted">{i + 1}</span>
            <span className="flex-1">{name(v)}</span>
            <Button variant="ghost" aria-label={`Move ${name(v)} up`} disabled={i === 0} onClick={() => move(i, -1)}>&uarr;</Button>
            <Button variant="ghost" aria-label={`Move ${name(v)} down`} disabled={i === value.length - 1} onClick={() => move(i, 1)}>&darr;</Button>
            <Button variant="ghost" aria-label={`Remove ${name(v)}`} onClick={() => onChange(value.filter((x) => x !== v))}>&times;</Button>
          </li>
        ))}
      </ol>
      {unused.length > 0 && (
        <Select label={`Add to ${label}`} value="" placeholder="Add..." options={unused} onChange={(v) => v && onChange([...value, v])} />
      )}
    </div>
  );
}
