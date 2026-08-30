export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2">
      <input
        type="checkbox"
        className="sr-only"
        checked={checked}
        aria-label={label}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span
        className={`flex h-[22px] w-[38px] flex-none items-center rounded-full p-[3px] transition-colors ${
          checked ? 'bg-accent' : ''
        }`}
        style={checked ? undefined : { background: 'rgba(255,255,255,0.1)' }}
      >
        <span
          className={`block h-4 w-4 rounded-full transition-transform ${
            checked ? 'translate-x-4' : 'translate-x-0'
          }`}
          style={{ background: checked ? '#fff' : 'rgba(255,255,255,0.55)' }}
        />
      </span>
    </label>
  );
}
