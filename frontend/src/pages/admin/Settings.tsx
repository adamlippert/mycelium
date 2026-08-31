import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api';
import type { GenreRule, SettingItem } from '../../api';
import { Card } from '../../components/primitives/Card';
import { Toggle } from '../../components/primitives/Toggle';

type SettingsGroup = { id: string; title: string; items: SettingItem[] };
type FieldValue = string | boolean;

// Mirrors ui.html's `refreshSettings()`: fields matching this pattern are
// never pre-filled, so an empty value at save time means "keep the existing
// value" rather than "clear it" (the same distinction the Jinja page's
// submit handler makes by disabling empty password inputs before posting).
const SECRET_RE = /KEY|TOKEN|SECRET|PASSWORD/;

function isSecretText(item: SettingItem): boolean {
  return item.kind !== 'bool' && item.kind !== 'list' && item.kind !== 'enum' && SECRET_RE.test(item.key);
}

// Mirrors ui.html's `_formatVal()`.
function formatValue(value: unknown, kind: SettingItem['kind']): string {
  if (value === null || value === undefined) return '';
  if (kind === 'list') return Array.isArray(value) ? value.join(',') : String(value);
  if (kind === 'bool') return value ? 'true' : 'false';
  return String(value);
}

function initialFieldValue(item: SettingItem): FieldValue {
  if (item.kind === 'bool') return Boolean(item.value);
  if (isSecretText(item)) return '';
  return formatValue(item.value, item.kind);
}

function fieldAsString(v: FieldValue): string {
  return typeof v === 'boolean' ? (v ? 'true' : 'false') : v;
}

/** Hot-reload lightning vs restart-required warning, plus the override-active
 * marker -- the exact three glyphs ui.html's `refreshSettings()` badges row
 * shows next to every setting key. */
function ItemBadges({ item }: { item: SettingItem }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs">
      {item.hot_reload ? (
        <span title="hot reload">⚡</span>
      ) : (
        <span title="restart required" className="text-warn">⚠</span>
      )}
      {item.overridden && (
        <span title="override active" className="text-accent">✱</span>
      )}
    </span>
  );
}

function ItemControl({
  item,
  value,
  onChange,
}: {
  item: SettingItem;
  value: FieldValue;
  onChange: (next: FieldValue) => void;
}) {
  const inputClass = 'w-full max-w-xs rounded border border-border bg-bg px-2 py-1 text-xs';

  if (item.kind === 'bool') {
    return <Toggle checked={Boolean(value)} onChange={onChange} label={item.key} />;
  }
  if (item.kind === 'enum') {
    return (
      <select
        aria-label={item.key}
        value={value as string}
        onChange={(e) => onChange(e.target.value)}
        className={inputClass}
      >
        {(item.options || []).map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    );
  }
  if (item.kind === 'list') {
    return (
      <input
        type="text"
        aria-label={item.key}
        value={value as string}
        placeholder="comma,separated"
        onChange={(e) => onChange(e.target.value)}
        className={inputClass}
      />
    );
  }
  const secret = isSecretText(item);
  const placeholder = secret
    ? item.value
      ? '(already set - type to replace)'
      : '(not set)'
    : undefined;
  return (
    <input
      type={secret ? 'password' : 'text'}
      aria-label={item.key}
      value={value as string}
      placeholder={placeholder}
      autoComplete={secret ? 'new-password' : undefined}
      onChange={(e) => onChange(e.target.value)}
      className={inputClass}
    />
  );
}

/** The `mode` group's card in ui.html: two radio tiles (Full / Lite) instead
 * of a normal key/value row, since LITE_MODE is the one setting that changes
 * which schedulers even start. */
function ModeCard({ isLite, onChange }: { isLite: boolean; onChange: (next: boolean) => void }) {
  const tile = (active: boolean) =>
    `flex cursor-pointer flex-col gap-1.5 rounded-lg border-2 p-3 ${
      active ? 'border-accent bg-accent/10' : 'border-border'
    }`;
  return (
    <Card className="border-2 border-accent">
      <div className="mb-3 flex items-center gap-2">
        <span className="text-sm font-semibold">Deployment mode</span>
        <span className="text-xs text-warn">⚠ restart required</span>
      </div>
      <div role="radiogroup" aria-label="Deployment mode" className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className={tile(!isLite)}>
          <span className="flex items-center gap-2">
            <input type="radio" name="lite-mode-toggle" checked={!isLite} onChange={() => onChange(false)} />
            <span className="text-sm font-semibold">Full</span>
          </span>
          <span className="text-xs text-muted">
            Full SPA + all schedulers + plugins (webplayer, trakt). For users who browse and
            request via the Mycelium interface.
          </span>
        </label>
        <label className={tile(isLite)}>
          <span className="flex items-center gap-2">
            <input type="radio" name="lite-mode-toggle" checked={isLite} onChange={() => onChange(true)} />
            <span className="text-sm font-semibold">Lite</span>
          </span>
          <span className="text-xs text-muted">
            Webhook + processor + /admin only. No SPA schedulers, no plugins. For
            Seerr/Jellyfin-only deployments.
          </span>
        </label>
      </div>
    </Card>
  );
}

function GroupCard({
  group,
  values,
  onChangeItem,
}: {
  group: SettingsGroup;
  values: Record<string, FieldValue>;
  onChangeItem: (key: string, next: FieldValue) => void;
}) {
  return (
    <Card>
      <div className="mb-3 text-sm font-semibold">{group.title}</div>
      <div className="space-y-2.5">
        {group.items.map((item) => (
          <div
            key={item.key}
            className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2.5 last:border-0 last:pb-0"
          >
            <div className="flex items-center gap-1.5">
              <code className="text-xs">{item.key}</code>
              <ItemBadges item={item} />
            </div>
            <ItemControl
              item={item}
              value={values[item.key] ?? initialFieldValue(item)}
              onChange={(next) => onChangeItem(item.key, next)}
            />
          </div>
        ))}
      </div>
    </Card>
  );
}

function GenreRuleRows({
  rules,
  movieGenres,
  tvGenres,
  onUpdate,
  onRemove,
}: {
  rules: GenreRule[];
  movieGenres: Array<{ id: number; name: string }>;
  tvGenres: Array<{ id: number; name: string }>;
  onUpdate: (i: number, patch: Partial<GenreRule>) => void;
  onRemove: (i: number) => void;
}) {
  return (
    <div className="space-y-2">
      {rules.map((rule, i) => {
        const genres = rule.media_type === 'movie' ? movieGenres : tvGenres;
        return (
          <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg bg-bg p-2">
            <button
              type="button"
              onClick={() => onUpdate(i, { enabled: !rule.enabled })}
              className={`flex h-5 w-9 flex-none items-center rounded-full px-0.5 transition-colors ${
                rule.enabled ? 'bg-accent' : 'bg-border'
              }`}
            >
              <div
                className={`h-4 w-4 rounded-full bg-white shadow transition-transform ${
                  rule.enabled ? 'translate-x-4' : 'translate-x-0'
                }`}
              />
            </button>
            <select
              value={rule.media_type}
              onChange={(e) => {
                const mt = e.target.value as 'movie' | 'tv';
                const g = (mt === 'movie' ? movieGenres : tvGenres)?.[0];
                onUpdate(i, { media_type: mt, genre_id: g?.id || 0, genre_name: g?.name || '' });
              }}
              className="rounded border border-border bg-card px-2 py-1 text-xs"
            >
              <option value="movie">Movies</option>
              <option value="tv">Shows</option>
            </select>
            <select
              value={rule.genre_id}
              onChange={(e) => {
                const g = genres.find((x) => x.id === Number(e.target.value));
                onUpdate(i, { genre_id: g?.id || 0, genre_name: g?.name || '' });
              }}
              className="rounded border border-border bg-card px-2 py-1 text-xs"
            >
              {genres.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
            <input
              type="number"
              placeholder="From year"
              value={rule.year_from ?? ''}
              onChange={(e) => onUpdate(i, { year_from: e.target.value ? Number(e.target.value) : null })}
              className="w-24 rounded border border-border bg-card px-2 py-1 text-xs"
            />
            <span className="text-xs text-muted">to</span>
            <input
              type="number"
              placeholder="To year"
              value={rule.year_to ?? ''}
              onChange={(e) => onUpdate(i, { year_to: e.target.value ? Number(e.target.value) : null })}
              className="w-24 rounded border border-border bg-card px-2 py-1 text-xs"
            />
            <button
              type="button"
              onClick={() => onRemove(i)}
              className="ml-auto rounded px-2 py-1 text-xs text-danger hover:bg-danger/10"
            >
              Remove
            </button>
          </div>
        );
      })}
    </div>
  );
}

/** Ported from the pre-native-admin `frontend/src/pages/Admin.tsx`
 * `DiscoverGenreTabsPanel`, restyled onto the shared `Card` primitive. */
function DiscoverGenreTabsPanel() {
  const qc = useQueryClient();
  const [msg, setMsg] = useState('');
  const { data } = useQuery({ queryKey: ['discover-genre-tabs-config'], queryFn: api.genreTabsConfig });
  const { data: movieGenres } = useQuery({ queryKey: ['genres', 'movie'], queryFn: () => api.genres('movie') });
  const { data: tvGenres } = useQuery({ queryKey: ['genres', 'tv'], queryFn: () => api.genres('tv') });

  const [tabs, setTabs] = useState<GenreRule[] | null>(null);
  const effectiveTabs = tabs ?? data?.tabs ?? [];

  const saveMutation = useMutation({
    mutationFn: (t: GenreRule[]) => api.setGenreTabsConfig(t),
    onSuccess: () => {
      setMsg('Saved.');
      qc.invalidateQueries({ queryKey: ['discover-genre-tabs-config'] });
      qc.invalidateQueries({ queryKey: ['genre-tabs'] });
    },
    onError: (e: Error) => setMsg(`Error: ${e.message}`),
  });

  const addTab = () => {
    const genres = movieGenres?.genres || [];
    const first = genres[0];
    setTabs([
      ...effectiveTabs,
      {
        media_type: 'movie', genre_id: first?.id || 0, genre_name: first?.name || '',
        year_from: null, year_to: null, enabled: true,
      },
    ]);
  };
  const updateTab = (i: number, patch: Partial<GenreRule>) => {
    setTabs(effectiveTabs.map((t, idx) => (idx === i ? { ...t, ...patch } : t)));
  };
  const removeTab = (i: number) => {
    setTabs(effectiveTabs.filter((_, idx) => idx !== i));
  };

  return (
    <Card className="space-y-4">
      <div className="text-sm font-semibold">Discover genre tabs</div>
      <p className="text-xs text-muted">
        Extra rows shown on the Discover page for browsing by genre, optionally bounded by a
        year range. Purely for browsing - use Auto-approve in Requests above to also
        auto-download.
      </p>

      <GenreRuleRows
        rules={effectiveTabs}
        movieGenres={movieGenres?.genres || []}
        tvGenres={tvGenres?.genres || []}
        onUpdate={updateTab}
        onRemove={removeTab}
      />

      <div className="flex flex-wrap gap-2">
        <button onClick={addTab} className="rounded border border-border px-3 py-1.5 text-xs hover:bg-bg">
          + Add genre tab
        </button>
        <button
          onClick={() => saveMutation.mutate(effectiveTabs)}
          disabled={saveMutation.isPending}
          className="rounded bg-accent px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
        >
          {saveMutation.isPending ? 'Saving...' : 'Save tabs'}
        </button>
      </div>

      {msg && <div className="font-mono text-xs text-muted">{msg}</div>}
    </Card>
  );
}

export default function Settings() {
  const { data } = useQuery({ queryKey: ['admin-settings'], queryFn: api.settings });
  const [values, setValues] = useState<Record<string, FieldValue> | null>(null);
  const [restartInitial, setRestartInitial] = useState<Record<string, string>>({});
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [autoAddMsg, setAutoAddMsg] = useState('');

  const groups: SettingsGroup[] = (data?.groups || []).filter((g) => g.id !== 'filter_rules');

  useEffect(() => {
    if (!data || values) return;
    const v: Record<string, FieldValue> = {};
    const restart: Record<string, string> = {};
    groups.forEach((g) => {
      g.items.forEach((item) => {
        const initial = initialFieldValue(item);
        v[item.key] = initial;
        if (!item.hot_reload) restart[item.key] = fieldAsString(initial);
      });
    });
    setValues(v);
    setRestartInitial(restart);
    // groups is derived from data on every render; re-running this effect is
    // gated on `values` above, so keying it off `data` alone is sufficient.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const saveMut = useMutation({
    mutationFn: async () => {
      if (!values) return;
      const fields: Record<string, string> = {};
      groups.forEach((g) => {
        g.items.forEach((item) => {
          const v = values[item.key] ?? initialFieldValue(item);
          if (isSecretText(item) && v === '') return; // untouched secret -- keep existing value
          fields[`setting_${item.key}`] = fieldAsString(v);
        });
      });
      await api.saveSettings(fields);
    },
    onSuccess: () => setSavedAt(Date.now()),
  });

  const autoAddMut = useMutation({
    mutationFn: api.autoAddNow,
    onSuccess: (r) => setAutoAddMsg(r.message || 'Started.'),
    onError: (e: Error) => setAutoAddMsg(`Error: ${e.message}`),
  });

  if (!values) {
    return <p className="text-sm text-muted">Loading...</p>;
  }

  const dirty = Object.keys(restartInitial).some(
    (key) => fieldAsString(values[key] ?? '') !== restartInitial[key],
  );

  const modeGroup = groups.find((g) => g.id === 'mode');
  const modeItem = modeGroup?.items.find((i) => i.key === 'LITE_MODE');
  const restGroups = groups.filter((g) => g.id !== 'mode');

  return (
    <div className="space-y-4 pb-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-bold">Runtime settings</h2>
        <a href="/setup?rerun=1" className="text-xs text-accent hover:underline">
          🧙 Re-run setup wizard
        </a>
      </div>

      {dirty && (
        <div className="rounded-lg border-l-4 border-warn bg-warn/10 px-4 py-3 text-sm text-warn">
          ⚠ You changed at least one restart-required setting. Run{' '}
          <code>docker compose restart mycelium</code> after saving for it to take effect.
        </div>
      )}

      {modeItem && (
        <ModeCard
          isLite={Boolean(values.LITE_MODE)}
          onChange={(next) => setValues((prev) => ({ ...(prev as Record<string, FieldValue>), LITE_MODE: next }))}
        />
      )}

      {restGroups.map((g) => (
        <GroupCard
          key={g.id}
          group={g}
          values={values}
          onChangeItem={(key, next) =>
            setValues((prev) => ({ ...(prev as Record<string, FieldValue>), [key]: next }))
          }
        />
      ))}

      <Card>
        <div className="mb-2 text-sm font-semibold">Auto-add now</div>
        <p className="mb-3 text-xs text-muted">
          Trigger the auto-add scheduler immediately. Pulls all enabled categories (trending,
          popular, per-service top lists) and queues new items.
        </p>
        <button
          type="button"
          onClick={() => autoAddMut.mutate()}
          disabled={autoAddMut.isPending}
          className="rounded bg-accent px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
        >
          {autoAddMut.isPending ? 'Starting...' : '▶ Run auto-add now'}
        </button>
        {autoAddMsg && <p className="mt-2 text-xs text-muted">{autoAddMsg}</p>}
      </Card>

      <DiscoverGenreTabsPanel />

      <div className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 border-t border-border bg-bg/95 px-1 py-3 backdrop-blur">
        <span className="text-xs text-muted">
          Empty a field to clear the override and fall back to the .env value.
        </span>
        <div className="flex items-center gap-3">
          {savedAt && !saveMut.isPending && <span className="text-xs text-ok">Saved</span>}
          <button
            type="button"
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending}
            className="rounded bg-accent px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            {saveMut.isPending ? 'Saving...' : '💾 Save all'}
          </button>
        </div>
      </div>
    </div>
  );
}
