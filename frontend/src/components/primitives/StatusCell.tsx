import { Link } from 'react-router-dom';
import { StatusDot } from './StatusDot';

export type StatusTone = 'ok' | 'warn' | 'danger' | 'off';

const TONE_LABEL: Record<StatusTone, string> = { ok: 'ok', warn: 'warning', danger: 'problem', off: 'unavailable' };
const BORDER: Record<StatusTone, string> = {
  ok: 'border-border', warn: 'border-warn/40', danger: 'border-danger/40', off: 'border-border',
};
const GLOW: Record<StatusTone, string> = {
  ok: '', off: '',
  warn: 'rgba(198,178,83,0.4)', danger: 'rgba(209,71,71,0.4)',
};

/** One cell of the Overview status strip: dot, label, number, one reason
 *  line, and a link that renders only when something needs attention. */
export function StatusCell({ tone, label, value, sub, href, linkLabel }: {
  tone: StatusTone; label: string; value: string; sub?: string; href?: string; linkLabel?: string;
}) {
  const alert = tone === 'warn' || tone === 'danger';
  return (
    <div role="group" aria-label={`${label}: ${TONE_LABEL[tone]}`}
      className={`relative flex min-h-[96px] flex-col gap-1.5 overflow-hidden rounded-xl border bg-card px-3.5 py-3 ${BORDER[tone]}`}>
      {alert && (
        <span aria-hidden="true" className="pointer-events-none absolute -right-5 -top-8 h-20 w-28 rounded-full opacity-50 blur-[38px]"
          style={{ background: GLOW[tone] }} />
      )}
      <div className="relative flex items-center gap-2 text-xs text-muted">
        {tone === 'off' ? <span className="block h-[7px] w-[7px] rounded-full bg-white/30" /> : <StatusDot tone={tone} />}
        {label}
      </div>
      <div className="relative font-mono text-xl font-medium text-body">{value}</div>
      {sub && <div className="relative text-[11px] text-muted">{sub}</div>}
      {alert && href && linkLabel && (
        <Link to={{ hash: href.replace(/^#/, '') }} className="relative mt-auto text-[11px] text-accent-light hover:underline">{linkLabel}</Link>
      )}
    </div>
  );
}
