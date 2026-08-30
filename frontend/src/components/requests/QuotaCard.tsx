import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { Card } from '../primitives';

export function QuotaCard() {
  const { data } = useQuery({ queryKey: ['my-quota'], queryFn: api.myQuota, staleTime: 60_000 });

  if (!data || data.unlimited) return null;

  const pct = Math.min(100, Math.round((data.used / Math.max(1, data.limit)) * 100));
  const tone = pct >= 100 ? 'var(--dot-danger)' : pct >= 80 ? 'var(--dot-warn)' : '#6152df';
  const resetDay = data.resets_at.slice(0, 10);
  const daysLeft = Math.max(0, Math.ceil((Date.parse(data.resets_at) - Date.now()) / 86_400_000));

  return (
    <Card>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">Monthly quota</div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="font-mono text-3xl font-semibold text-body">{data.used}</span>
        <span className="text-xs text-muted">of {data.limit} requests</span>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full" style={{ background: 'rgba(255,255,255,0.08)' }}>
        <div data-quota-bar className="h-full rounded-full" style={{ width: `${pct}%`, background: tone }} />
      </div>
      <div className="mt-2 text-[11px] text-muted" title={resetDay}>
        Resets in {daysLeft} {daysLeft === 1 ? 'day' : 'days'}
      </div>
    </Card>
  );
}
