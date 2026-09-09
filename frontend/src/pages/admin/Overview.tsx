import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { StatusStrip } from './overview/StatusStrip';
import { ScraperStrip } from './overview/ScraperStrip';
import { ActivityBand } from './overview/ActivityBand';
import { LibraryBand } from './overview/LibraryBand';
import { TorboxCard } from './overview/TorboxCard';
import { ReferenceSection } from './overview/ReferenceSection';
import { MetricsPanel } from './overview/reference/MetricsPanel';
import { EndpointsPanel } from './overview/reference/EndpointsPanel';
import { FoldersPanel } from './overview/reference/FoldersPanel';

function Band({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3" aria-label={title}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">{title}</h2>
        {hint && <span className="text-xs text-white/30">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

export default function Overview() {
  const overviewQ = useQuery({ queryKey: ['admin-overview'], queryFn: api.overview, refetchInterval: 30_000 });
  const healthQ = useQuery({ queryKey: ['admin-health'], queryFn: api.health, refetchInterval: 30_000 });
  const activityQ = useQuery({ queryKey: ['admin-activity'], queryFn: api.activity, refetchInterval: 60_000 });
  const torboxUsageQ = useQuery({ queryKey: ['admin-torbox-usage'], queryFn: api.torboxUsage, retry: false });
  const quotaQ = useQuery({ queryKey: ['admin-torbox-quota'], queryFn: api.torboxQuota, retry: false });
  const o = overviewQ.data;

  return (
    <div className="space-y-7">
      <Band title="Right now" hint="refreshes every 30 s; quiet rows stay quiet">
        <StatusStrip status={o?.status} services={healthQ.data?.services} loading={overviewQ.isLoading} error={overviewQ.isError} />
        {o && <ScraperStrip scrapers={o.status.scrapers} />}
      </Band>
      <Band title="Activity" hint="what people did, and what it cost">
        <ActivityBand activity={o?.activity} events={activityQ.data?.events} loading={overviewQ.isLoading} />
      </Band>
      <Band title="Library" hint="what is on the shelf">
        <LibraryBand library={o?.library} torbox={torboxUsageQ.data} loading={overviewQ.isLoading} />
      </Band>
      <Band title="TorBox">
        <TorboxCard adds={o?.status.torbox_adds} byReason={quotaQ.data?.by_reason} usage={torboxUsageQ.data}
          streamFront={healthQ.data?.stream_front} recentStreams={o?.torbox.recent_streams} last429At={o?.torbox.last_429_at} idleMinutes={null} />
      </Band>
      <Band title="Reference" hint="collapsed by default; state remembered">
        <div className="space-y-3">
          <ReferenceSection id="metrics" title="Metrics, 30 days" hint="latency, quality added, source win rate, failures">
            {(open) => <MetricsLoader open={open} />}
          </ReferenceSection>
          <ReferenceSection id="endpoints" title="Integration endpoints" hint="Seerr, TorBox, Catbox prefix, webhook secret">
            {(open) => <EndpointsLoader open={open} />}
          </ReferenceSection>
          <ReferenceSection id="folders" title="Top folders" hint="largest media folders by strm count">
            {(open) => <FoldersLoader open={open} />}
          </ReferenceSection>
        </div>
      </Band>
    </div>
  );
}

function MetricsLoader({ open }: { open: boolean }) {
  const q = useQuery({ queryKey: ['admin-metrics-summary'], queryFn: api.metricsSummary, retry: false, enabled: open });
  return <MetricsPanel metrics={q.data} loading={q.isLoading} />;
}
function EndpointsLoader({ open }: { open: boolean }) {
  const q = useQuery({ queryKey: ['admin-webhook-secret'], queryFn: api.webhookSecret, retry: false, enabled: open });
  return <EndpointsPanel secret={q.data} loading={q.isLoading} error={q.isError} />;
}
function FoldersLoader({ open }: { open: boolean }) {
  const q = useQuery({ queryKey: ['admin-storage'], queryFn: api.storage, retry: false, enabled: open });
  return <FoldersPanel folders={q.data?.folders} loading={q.isLoading} />;
}
