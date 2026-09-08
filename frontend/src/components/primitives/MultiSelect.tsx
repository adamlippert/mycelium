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
  const [highlight, setHighlight] = useState<number | null>(null);
  const [closed, setClosed] = useState(false);
  const q = query.trim().toLowerCase();
  const candidates = options.filter(
    (o) => !value.includes(o.value) && (q === '' || o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q)),
  ).slice(0, 20);
  const listVisible = q !== '' && candidates.length > 0 && !closed;
  const optionId = (i: number) => `${label.replace(/\s+/g, '-').toLowerCase()}-multiselect-option-${i}`;
  const add = (v: string) => {
    onChange([...value, v]);
    setQuery('');
    setHighlight(null);
    setClosed(false);
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
          aria-activedescendant={listVisible && highlight !== null && candidates[highlight] ? optionId(highlight) : undefined}
          value={query}
          placeholder={value.length ? '' : 'Type to search'}
          onChange={(e) => {
            setQuery(e.target.value);
            setHighlight(null);
            setClosed(false);
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              if (!listVisible) return;
              e.preventDefault();
              setHighlight((h) => (h === null ? 0 : Math.min(h + 1, candidates.length - 1)));
            } else if (e.key === 'ArrowUp') {
              if (!listVisible) return;
              e.preventDefault();
              setHighlight((h) => (h === null ? candidates.length - 1 : Math.max(Math.min(h - 1, candidates.length - 1), 0)));
            } else if (e.key === 'Enter') {
              const target = listVisible ? (highlight !== null ? candidates[highlight] : candidates[0]) : undefined;
              if (target) {
                e.preventDefault();
                add(target.value);
              }
            } else if (e.key === 'Backspace') {
              if (query === '' && value.length > 0) {
                onChange(value.slice(0, -1));
              }
            } else if (e.key === 'Escape') {
              if (listVisible) {
                e.preventDefault();
                setClosed(true);
              }
            }
          }}
          className="min-w-[6rem] flex-1 bg-transparent py-1 text-xs outline-none"
        />
      </div>
      {listVisible && (
        <ul id={`${label.replace(/\s+/g, '-').toLowerCase()}-multiselect-listbox`} role="listbox" className="mt-1 max-h-40 overflow-auto rounded border border-border bg-card-raised text-xs">
          {candidates.map((o, i) => (
            <li
              key={o.value}
              id={optionId(i)}
              role="option"
              aria-selected={i === highlight}
              onClick={() => add(o.value)}
              className={`cursor-pointer px-2 py-1 hover:bg-white/[0.06] ${i === highlight ? 'bg-white/[0.08]' : ''}`}
            >
              {o.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
