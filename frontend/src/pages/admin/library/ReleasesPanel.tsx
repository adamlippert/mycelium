import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api';
import type { Candidate } from '../../../api';
import { Button } from '../../../components/primitives';
import { DrawerCard } from './cards/DrawerCard';

/** What a cached pack contains, against the episodes the season has. A gappy
 * pack names the missing episodes rather than pretending to be a range. */
export function coverageLabel(episodes: number[] | null | undefined, expected: number[]): { text: string; tone: 'ok' | 'warn' } | null {
  if (!episodes) return null;
  if (episodes.length === 0) return { text: 'no episode found', tone: 'warn' };
  const pad = (n: number) => String(n).padStart(2, '0');
  if (expected.length === 0) return { text: `${episodes.length} episode${episodes.length === 1 ? '' : 's'}`, tone: 'ok' };
  const missing = expected.filter((e) => !episodes.includes(e));
  if (missing.length === 0) return { text: `all ${expected.length} episodes`, tone: 'ok' };
  return { text: `${episodes.length} of ${expected.length}, missing ${missing.map((n) => `E${pad(n)}`).join(', ')}`, tone: 'warn' };
}

function Badge({ tone, children }: { tone: 'ok' | 'muted' | 'warn'; children: React.ReactNode }) {
  const cls = { ok: 'bg-ok/20 text-ok', muted: 'bg-white/10 text-muted', warn: 'bg-warn/20 text-warn' }[tone];
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${cls}`}>{children}</span>;
}

export function ReleasesPanel({ imdb, season, episode, expectedEpisodes = [], onDone, onClose }: {
  imdb: string; season?: number; episode?: number;
  /** Season mode: the episode numbers the season has, for the coverage badge. */
  expectedEpisodes?: number[];
  onDone: (result: { ok: boolean; message: string }) => void; onClose: () => void;
}) {
  const seasonMode = season != null && episode == null;
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['library-candidates', imdb, season, episode], queryFn: () => api.libraryCandidates(imdb, season, episode), retry: false });
  const [picked, setPicked] = useState<Candidate | null>(null);
  const [blacklistOld, setBlacklistOld] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const confirm = async () => {
    if (!picked) return;
    setBusy(true);
    try {
      const body = { info_hash: picked.info_hash, ...(season != null ? (episode != null ? { season, episode } : { season }) : {}), blacklist_old: blacklistOld };
      const r = await api.librarySwap(imdb, body);
      if (r.ok) {
        qc.invalidateQueries({ queryKey: ['library-candidates', imdb, season, episode] });
        onDone(r);
        onClose();
      } else {
        setMsg({ ok: false, text: r.message });
      }
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : 'swap failed' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <DrawerCard title="Releases" description={seasonMode
      ? `Season packs the scrapers found for season ${season}; packs already in use are marked. The badge says which episodes a cached pack contains.`
      : 'What the scrapers found for this title; the current release is marked.'}>
      {q.isLoading && <p className="text-xs text-muted">Asking the scrapers...</p>}
      {q.error && (
        <p className="text-xs text-danger">{(q.error as Error).message} <Button variant="ghost" onClick={() => q.refetch()}>Retry</Button></p>
      )}
      {q.data && q.data.candidates.length === 0 && <p className="text-xs text-muted">The scrapers returned nothing for this title.</p>}
      {q.data && q.data.candidates.length > 0 && (
        <ul className="space-y-1">
          {q.data.candidates.map((c) => (
            <li key={c.info_hash} className={`rounded border border-border p-2 text-xs ${c.kept ? '' : 'opacity-60'}`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="max-w-[22rem] truncate font-mono" title={c.name}>{c.name}</span>
                {c.cached && <Badge tone="ok">cached</Badge>}
                {seasonMode && (() => { const cov = coverageLabel(c.episodes, expectedEpisodes); return cov ? <Badge tone={cov.tone}>{cov.text}</Badge> : null; })()}
                {c.current && <Badge tone="muted">{seasonMode ? 'in use' : 'current'}</Badge>}
                {(!c.current || seasonMode) && <Button onClick={() => { setPicked(c); setMsg(null); }}>Use</Button>}
              </div>
              <div className="mt-1 text-muted">
                {[c.quality, c.source].filter(Boolean).join(' ')}
                {c.size_gb ? <> · <span>{c.size_gb} GB</span></> : ''} · {c.seeders} seeders
                {c.languages.length ? ` · ${c.languages.join(', ')}` : ''} · {c.scrapers.join(', ')}
              </div>
              {!c.kept && <div className="mt-1 text-muted">dropped: {c.rule} = {c.value}</div>}
              {picked?.info_hash === c.info_hash && (
                <div className="mt-2 space-y-1 rounded border border-border bg-bg p-2">
                  <p>{seasonMode
                    ? 'Switch the whole season to this pack? Episodes it contains move to it; episodes it lacks keep their release or stay wanted. Files in Jellyfin stay the same.'
                    : 'Switch to this release? The next play uses it; the file in Jellyfin stays the same.'}</p>
                  {!c.cached && <p className="text-warn">TorBox does not have this yet; the first play adds it and may wait.</p>}
                  <label className="flex items-center gap-2">
                    <input type="checkbox" aria-label={seasonMode ? 'Blacklist the current releases' : 'Blacklist the current release'} checked={blacklistOld} onChange={(e) => setBlacklistOld(e.target.checked)} />
                    {seasonMode ? 'Blacklist the current releases' : 'Blacklist the current release'}
                  </label>
                  <div className="flex items-center gap-2">
                    <Button variant="primary" onClick={confirm} loading={busy} loadingLabel="Switching...">Confirm</Button>
                    <Button variant="ghost" onClick={() => setPicked(null)}>Cancel</Button>
                    {msg && <span className={msg.ok ? 'text-ok' : 'text-danger'}>{msg.text}</span>}
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </DrawerCard>
  );
}
