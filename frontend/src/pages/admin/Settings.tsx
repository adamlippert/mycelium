import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api';
import type { SettingsSection } from '../../api';
import { Button } from '../../components/primitives';
import { CUSTOM_CARDS } from './settings/customCards';
import { SectionView } from './settings/SectionView';
import { asString, countChanges, initialValues, sectionMatches, serialize } from './settings/visibility';
import type { FieldValue, Values } from './settings/visibility';

const ADVANCED_KEY = 'mycelium.settings.advanced';

function readAdvanced(): boolean {
  try { return localStorage.getItem(ADVANCED_KEY) === 'true'; } catch { return false; }
}

export default function Settings() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['admin-settings-schema'], queryFn: api.settingsSchema });
  const sections: SettingsSection[] = useMemo(() => data?.sections || [], [data]);
  const [values, setValues] = useState<Values | null>(null);
  const [initial, setInitial] = useState<Values>({});
  const [active, setActive] = useState<string>('');
  const [query, setQuery] = useState('');
  const [advanced, setAdvanced] = useState(readAdvanced);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    if (!sections.length) return;
    if (values === null) {
      const v = initialValues(sections);
      setValues(v);
      setInitial(v);
      setActive(sections[0].id);
      return;
    }
    // A schema refetch (e.g. after save, to pick up fresh overridden/"env"
    // badges) must not clobber edits in progress: only reset from the new
    // schema when there is nothing unsaved.
    if (countChanges(sections, values, initial) === 0) {
      const v = initialValues(sections);
      setValues(v);
      setInitial(v);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sections]);

  useEffect(() => {
    try { localStorage.setItem(ADVANCED_KEY, advanced ? 'true' : 'false'); } catch { /* private mode */ }
  }, [advanced]);

  const shown = sections.filter((s) => sectionMatches(s, query));
  useEffect(() => {
    if (shown.length && !shown.some((s) => s.id === active)) setActive(shown[0].id);
  }, [query, shown, active]);

  const saveMut = useMutation({
    mutationFn: async () => { if (values) await api.saveSettings(serialize(sections, values, initial)); },
    onSuccess: () => {
      if (values) setInitial(values);
      setSavedAt(Date.now());
      qc.invalidateQueries({ queryKey: ['admin-settings'] });
      qc.invalidateQueries({ queryKey: ['admin-settings-schema'] });
    },
  });

  if (!values) return <p className="text-sm text-muted">Loading...</p>;

  const changes = countChanges(sections, values, initial);
  const restartTouched = sections.some((s) => s.fields.some((f) => !f.hot_reload && f.kind !== 'custom' && asString(values[f.key]) !== asString(initial[f.key])));
  const current = sections.find((s) => s.id === active) || shown[0];
  const onChange = (key: string, next: FieldValue) => { setValues((p) => ({ ...(p as Values), [key]: next })); setSavedAt(null); };

  return (
    <div className="grid gap-6 pb-20 md:grid-cols-[13rem_1fr]">
      <aside className="space-y-3">
        <input type="search" aria-label="Search settings" placeholder="Search settings" value={query} onChange={(e) => setQuery(e.target.value)}
          className="w-full rounded border border-border bg-bg px-2 py-1.5 text-xs" />
        <div role="group" aria-label="Detail level" className="flex rounded border border-border text-xs">
          {(['Simple', 'Advanced'] as const).map((m) => (
            <button key={m} type="button" aria-pressed={advanced === (m === 'Advanced')} onClick={() => setAdvanced(m === 'Advanced')}
              className={`flex-1 py-1 ${advanced === (m === 'Advanced') ? 'bg-accent text-white' : 'text-muted hover:text-body'}`}>{m}</button>
          ))}
        </div>
        <nav aria-label="Settings sections" className="space-y-0.5">
          {shown.map((s) => (
            <button key={s.id} type="button" onClick={() => setActive(s.id)} aria-current={s.id === current?.id ? 'page' : undefined}
              className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm ${s.id === current?.id ? 'bg-white/[0.08] text-white' : 'text-muted hover:text-body'}`}>
              <span aria-hidden="true">{s.icon}</span>{s.title}
            </button>
          ))}
          {!shown.length && <p className="px-2 text-xs text-muted">Nothing matches.</p>}
        </nav>
        <a href="/setup?rerun=1" className="block px-2 text-xs text-accent-light hover:underline">Re-run setup wizard</a>
      </aside>
      <main>
        {current && (
          <SectionView section={current} sections={sections} values={values} onChange={onChange} advanced={advanced} query={query} custom={CUSTOM_CARDS} />
        )}
      </main>
      <div className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-bg/95 px-4 py-3 backdrop-blur md:left-auto">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
          <span className="text-xs text-muted">
            {changes ? `${changes} unsaved change${changes === 1 ? '' : 's'}` : 'Empty a field to clear its override and fall back to the .env value.'}
            {restartTouched && <span className="ml-2 text-warn">A restart-required setting changed; restart the container after saving.</span>}
          </span>
          <div className="flex items-center gap-3">
            {savedAt && !changes && <span className="text-xs text-ok">Saved</span>}
            <Button variant="primary" onClick={() => saveMut.mutate()} loading={saveMut.isPending} loadingLabel="Saving..." disabled={!changes}>Save</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
