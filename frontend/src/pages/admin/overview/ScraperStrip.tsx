import type { OverviewPayload } from '../../../api';
import { StatusDot } from '../../../components/primitives';
import { formatLatency } from './format';

const TONE = { ok: 'ok', slow: 'warn', down: 'danger' } as const;

export function ScraperStrip({ scrapers }: { scrapers: OverviewPayload['status']['scrapers'] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs" aria-label="Scraper state">
      {scrapers.map((s) => {
        const tone = s.state in TONE ? TONE[s.state as keyof typeof TONE] : null;
        const dim = s.state === 'disabled' || s.state === 'unknown';
        return (
          <span key={s.name} aria-label={`${s.name}: ${s.state}`} className={`inline-flex items-center gap-1.5 ${dim ? 'opacity-50' : ''}`}>
            {tone ? <StatusDot tone={tone} /> : <span className="block h-[7px] w-[7px] rounded-full bg-white/30" />}
            <span className="text-body">{s.name}</span>
            <span className="font-mono text-[11px] text-muted">
              {s.state === 'ok' || s.state === 'slow' ? formatLatency(s.latency_ms) : s.state}
            </span>
          </span>
        );
      })}
    </div>
  );
}
