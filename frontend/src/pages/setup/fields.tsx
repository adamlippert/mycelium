import type { ReactNode } from 'react';

/** Shared field chrome for the wizard's text/password inputs - visual parity
 * with setup.html's .field/label/input rules, ids kept identical to the
 * template for 1:1 traceability against the field inventory. */
export function TextField({
  id,
  label,
  value,
  onChange,
  placeholder,
  type = 'text',
  required,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: 'text' | 'password';
  required?: boolean;
  hint?: ReactNode;
}) {
  return (
    <div className="mb-3.5">
      <label htmlFor={id} className="mb-1 block text-[11px] font-bold uppercase tracking-wider text-muted">
        {label} {required && <span className="text-danger">*</span>}
      </label>
      <input
        id={id}
        name={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        className="w-full rounded-md border border-border bg-card-raised px-3 py-2 text-[13px] text-body
                   outline-none focus:border-accent"
      />
      {hint && <span className="mt-1 block text-[11px] text-muted/70">{hint}</span>}
    </div>
  );
}

export function CheckboxRow({
  id,
  title,
  description,
  checked,
  onChange,
}: {
  id: string;
  title: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label
      htmlFor={id}
      className="flex cursor-pointer items-center gap-2.5 rounded-md p-2 hover:bg-white/[0.04]"
    >
      <input
        id={id}
        name={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 flex-none accent-accent"
      />
      <span>
        <span className="block text-[13px] text-body">{title}</span>
        <span className="block text-[11px] text-muted">{description}</span>
      </span>
    </label>
  );
}
