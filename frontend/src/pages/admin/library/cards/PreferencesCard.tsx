import { useState } from 'react';
import type { LibraryDetail } from '../../../../api';
import { Toggle } from '../../../../components/primitives';
import { ACTIONS } from '../actions';
import { ActionButton, DrawerCard, Row } from './DrawerCard';

export function PreferencesCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  const o = d.override;
  const [form, setForm] = useState({ quality_preference: o?.quality_preference || '', allow_4k: Boolean(o?.allow_4k), prefer_hevc: Boolean(o?.prefer_hevc), notes: o?.notes || '' });
  return (
    <DrawerCard title="Preferences" description="Overrides for this title only; blank means the global rules apply.">
      <Row label="Resolution"><input aria-label="Preferred resolution" value={form.quality_preference} placeholder="e.g. 1080p" onChange={(e) => setForm({ ...form, quality_preference: e.target.value })} className="w-full max-w-xs rounded border border-border bg-bg px-2 py-1 text-xs" /></Row>
      <Row label="Allow 4K"><Toggle label="Allow 4K" checked={form.allow_4k} onChange={(v) => setForm({ ...form, allow_4k: v })} /></Row>
      <Row label="Prefer HEVC"><Toggle label="Prefer HEVC" checked={form.prefer_hevc} onChange={(v) => setForm({ ...form, prefer_hevc: v })} /></Row>
      <Row label="Notes"><input aria-label="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="w-full max-w-xs rounded border border-border bg-bg px-2 py-1 text-xs" /></Row>
      <div className="flex gap-2">
        <ActionButton label="Save" variant="primary" run={() => ACTIONS.saveOverride(d, form)} onDone={onDone} />
        {o && <ActionButton label="Clear" run={() => ACTIONS.clearOverride(d)} onDone={onDone} />}
      </div>
    </DrawerCard>
  );
}
