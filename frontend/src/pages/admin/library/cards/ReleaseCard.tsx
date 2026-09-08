import type { LibraryDetail } from '../../../../api';
import { Copy, DrawerCard, Row } from './DrawerCard';

export function ReleaseCard({ d }: { d: LibraryDetail }) {
  const r = d.request;
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
    </DrawerCard>
  );
}
