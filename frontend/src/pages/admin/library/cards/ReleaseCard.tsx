import { useState } from 'react';
import type { LibraryDetail } from '../../../../api';
import { Button } from '../../../../components/primitives';
import { Copy, DrawerCard, Row } from './DrawerCard';
import { ReleasesPanel } from '../ReleasesPanel';

export function ReleaseCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  const r = d.request;
  const [open, setOpen] = useState(false);
  const [lastResult, setLastResult] = useState<{ ok: boolean; message: string } | null>(null);
  if (!r.info_hash && !d.items.length) return null;
  return (
    <DrawerCard title="Release" description="The release in use and the files written for it.">
      {(r.quality || r.source) && <Row label="Quality">{[r.quality, r.source].filter(Boolean).join(' ')}</Row>}
      {r.info_hash && <Row label="Hash"><span className="font-mono">{r.info_hash}</span> <Copy value={r.info_hash} /></Row>}
      {d.items.map((i) => (
        <div key={i.token} className="rounded border border-border p-2 text-xs">
          <Row label="File">{i.strm_path || 'no file'} {i.strm_path && <Copy value={i.strm_path} />}</Row>
          <Row label="Provider">{i.debrid_provider || 'torbox'}{i.torbox_id ? `, TorBox id ${i.torbox_id}` : ', not in TorBox'}</Row>
          <Row label="Played">{i.play_count} times{i.last_played ? `, last ${i.last_played}` : ''}</Row>
          {i.season != null && <Row label="Episode">S{String(i.season).padStart(2, '0')}E{String(i.episode ?? 0).padStart(2, '0')}</Row>}
        </div>
      ))}
      {r.media_type === 'movie' && d.items.length > 0 && (
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => setOpen((v) => !v)}>Pick another release</Button>
          {lastResult && <span className={lastResult.ok ? 'text-ok' : 'text-danger'}>{lastResult.message}</span>}
        </div>
      )}
      {open && <ReleasesPanel imdb={r.imdb_id} onDone={(result) => { setLastResult(result); onDone(); }} onClose={() => setOpen(false)} />}
    </DrawerCard>
  );
}
