import { useState } from 'react';
import type { SettingsField, SettingsSection } from '../../../api';
import { Button, MultiSelect, OrderedList, Select, Toggle } from '../../../components/primitives';
import type { Endpoint } from './FieldList';
import { Picker } from './Picker';
import { SECRET_CLEARED } from './visibility';
import type { FieldValue, Values } from './visibility';

const INPUT = 'w-full max-w-md rounded border border-border bg-bg px-2 py-1 text-xs';

function Badges({ field }: { field: SettingsField }) {
  return (
    <span className="ml-2 inline-flex gap-1 align-middle">
      {!field.hot_reload && <span className="rounded bg-warn/20 px-1.5 text-[10px] font-semibold uppercase text-warn">restart</span>}
      {!field.overridden && field.value !== '' && field.value !== null && field.value !== false && (
        <span className="rounded bg-white/10 px-1.5 text-[10px] font-semibold uppercase text-muted" title="value comes from .env or the default">env</span>
      )}
    </span>
  );
}

function Help({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 110;
  return (
    <div className="mt-1 text-xs text-muted">
      {long && !open ? `${text.slice(0, 100).trimEnd()}...` : text}
      {long && (
        <button type="button" onClick={() => setOpen((o) => !o)} className="ml-1 text-accent-light hover:underline" aria-label={open ? 'Less' : 'More'}>
          {open ? 'less' : 'more'}
        </button>
      )}
    </div>
  );
}

function isValidUrl(v: string): boolean {
  if (!v) return true;
  try {
    const u = new URL(v);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

export function Control({
  field, value, onChange, values, sections, endpoint = 'settings',
}: {
  field: SettingsField;
  value: FieldValue;
  onChange: (next: FieldValue) => void;
  values: Values;
  sections: SettingsSection[];
  endpoint?: Endpoint;
}) {
  const [reveal, setReveal] = useState(false);
  const cleared = value === SECRET_CLEARED;
  const str = cleared ? '' : typeof value === 'string' ? value : '';
  switch (field.kind) {
    case 'bool':
      return <Toggle checked={Boolean(value)} onChange={onChange} label={field.label} />;
    case 'select':
      return <Select label={field.label} value={str} onChange={onChange} options={field.options || []} placeholder={field.placeholder ?? undefined} />;
    case 'multiselect':
      return <MultiSelect label={field.label} value={Array.isArray(value) ? value : []} onChange={onChange} options={field.options || []} />;
    case 'ordered':
      return <OrderedList label={field.label} value={Array.isArray(value) ? value : []} onChange={onChange} options={field.options || []} />;
    case 'int':
    case 'float':
      return (
        <span className="inline-flex items-center gap-2">
          <input type="number" aria-label={field.label} value={str} min={field.min ?? undefined} max={field.max ?? undefined}
            step={field.kind === 'float' ? '0.1' : '1'} onChange={(e) => onChange(e.target.value)} className={`${INPUT} max-w-[8rem]`} />
          {field.unit && <span className="text-xs text-muted">{field.unit}</span>}
        </span>
      );
    case 'secret':
      return (
        <span className="inline-flex w-full max-w-md items-center gap-2">
          <input type={reveal ? 'text' : 'password'} aria-label={field.label} value={str} autoComplete="new-password"
            placeholder={cleared ? '(cleared, will remove on save)' : field.value ? '(already set, type to replace)' : '(not set)'}
            onChange={(e) => onChange(e.target.value)} className={INPUT} />
          <Button variant="ghost" aria-label={`${reveal ? 'Hide' : 'Show'} ${field.label}`} onClick={() => setReveal((r) => !r)}>{reveal ? 'Hide' : 'Show'}</Button>
          {field.value === true && (
            <Button variant="ghost" aria-label={`Clear ${field.label}`} onClick={() => onChange(SECRET_CLEARED)}>Clear</Button>
          )}
        </span>
      );
    default: {
      if (field.picker) return <Picker field={field} value={str} onChange={onChange} values={values} sections={sections} endpoint={endpoint} />;
      const bad = field.kind === 'url' && !isValidUrl(str);
      return (
        <span className="inline-flex w-full max-w-md flex-col gap-1">
          <input type="text" aria-label={field.label} value={str} placeholder={field.placeholder ?? (field.kind === 'list' ? 'comma,separated' : undefined)}
            onChange={(e) => onChange(e.target.value)} className={`${INPUT} ${field.kind === 'path' ? 'font-mono' : ''} ${bad ? 'border-danger' : ''}`} />
          {bad && <span className="text-xs text-danger">Enter a full http or https address.</span>}
        </span>
      );
    }
  }
}

export function SettingField({
  field, value, onChange, values, sections, dimmed = false, endpoint = 'settings',
}: {
  field: SettingsField;
  value: FieldValue;
  onChange: (next: FieldValue) => void;
  values: Values;
  sections: SettingsSection[];
  dimmed?: boolean;
  endpoint?: Endpoint;
}) {
  return (
    <div data-testid={`field-${field.key}`} className={`grid gap-2 border-b border-border py-3 last:border-0 sm:grid-cols-[minmax(0,14rem)_1fr] ${dimmed ? 'opacity-40' : ''}`}>
      <div>
        <span className="text-sm font-medium">{field.label}</span>
        <Badges field={field} />
        <Help text={field.help} />
      </div>
      <div className="flex items-start">
        <Control field={field} value={value} onChange={onChange} values={values} sections={sections} endpoint={endpoint} />
      </div>
    </div>
  );
}
