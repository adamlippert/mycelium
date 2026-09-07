import { useState } from 'react';
import { Chip } from './Chip';
import type { Option } from './Select';

export function MultiSelect({
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
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const candidates = options.filter(
    (o) => !value.includes(o.value) && (q === '' || o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q)),
  );
  const add = (v: string) => {
    onChange([...value, v]);
    setQuery('');
  };
  return (
    <div className="w-full max-w-md">
      <div className="flex flex-wrap items-center gap-1.5 rounded border border-border bg-bg px-2 py-1">
        {value.map((v) => (
          <Chip key={v} label={options.find((o) => o.value === v)?.label ?? v} selected onRemove={() => onChange(value.filter((x) => x !== v))} />
        ))}
        <input
          type="text"
          aria-label={label}
          value={query}
          placeholder={value.length ? '' : 'Type to search'}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && candidates[0]) {
              e.preventDefault();
              add(candidates[0].value);
            }
          }}
          className="min-w-[6rem] flex-1 bg-transparent py-1 text-xs outline-none"
        />
      </div>
      {q !== '' && candidates.length > 0 && (
        <ul role="listbox" className="mt-1 max-h-40 overflow-auto rounded border border-border bg-card-raised text-xs">
          {candidates.slice(0, 20).map((o) => (
            <li key={o.value} role="option" aria-selected={false} onClick={() => add(o.value)} className="cursor-pointer px-2 py-1 hover:bg-white/[0.06]">
              {o.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
