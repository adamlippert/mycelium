import { useState } from 'react';
import { Button } from '../../../../components/primitives';

export function DrawerCard({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h3 className="text-[11px] font-semibold uppercase tracking-widest text-muted">{title}</h3>
      {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
      <div className="mt-3 space-y-2 text-sm">{children}</div>
    </section>
  );
}

export function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-2 text-xs">
      <span className="text-muted">{label}</span>
      <span className="break-all">{children}</span>
    </div>
  );
}

/** A button whose result line appears next to it, the way Settings' Test buttons work. */
export function ActionButton({ label, run, onDone, variant = 'default', confirm }: {
  label: string; run: () => Promise<{ ok: boolean; message: string }>; onDone?: () => void;
  variant?: 'default' | 'primary' | 'ghost'; confirm?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const go = async () => {
    if (confirm && !window.confirm(confirm)) return;
    setBusy(true);
    try {
      const r = await run();
      setMsg({ ok: r.ok, text: r.message });
      if (r.ok) onDone?.();
    } catch (e: any) {
      setMsg({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="inline-flex items-center gap-2">
      <Button variant={variant} onClick={go} loading={busy} loadingLabel="Working...">{label}</Button>
      {msg && <span className={`text-xs ${msg.ok ? 'text-ok' : 'text-danger'}`}>{msg.text}</span>}
    </span>
  );
}

export function Copy({ value }: { value: string }) {
  const [done, setDone] = useState(false);
  return <Button variant="ghost" aria-label={`Copy ${value.slice(0, 12)}`} onClick={() => { navigator.clipboard?.writeText(value); setDone(true); }}>{done ? 'Copied' : 'Copy'}</Button>;
}
