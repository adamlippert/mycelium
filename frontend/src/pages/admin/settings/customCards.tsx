import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../../../api';
import type { GenreRule } from '../../../api';
import { Button, GenreRuleRows } from '../../../components/primitives';
import type { FieldValue, Values } from './visibility';

type CardProps = { values: Values; onChange: (key: string, next: FieldValue) => void };

/** Ported from the pre-native-admin `frontend/src/pages/Admin.tsx`
 * `DiscoverGenreTabsPanel`. */
export function GenreTabs(_props: CardProps) {
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
    <div className="space-y-4">
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
        <Button onClick={addTab}>+ Add genre tab</Button>
        <Button variant="primary" onClick={() => saveMutation.mutate(effectiveTabs)} loading={saveMutation.isPending} loadingLabel="Saving...">
          Save tabs
        </Button>
      </div>

      {msg && <div className="font-mono text-xs text-muted">{msg}</div>}
    </div>
  );
}

/** `POST /ui/set-password`: the legacy admin-only shared fallback password
 * (`auth.set_password`, no current-password check). Distinct from a user's
 * own password, changed under Settings > Account via `POST
 * /ui/api/me/password` (which does require the current password). */
export function LegacyPassword(_props: CardProps) {
  const [password, setPassword] = useState('');
  const [msg, setMsg] = useState('');

  const mutation = useMutation({
    mutationFn: (pw: string) => api.setLegacyPassword(pw),
    onSuccess: () => { setMsg('Updated.'); setPassword(''); },
    onError: (e: Error) => setMsg(`Error: ${e.message}`),
  });

  const submit = () => {
    if (password.length < 6) {
      setMsg('Password must be at least 6 characters');
      return;
    }
    mutation.mutate(password);
  };

  return (
    <div>
      <div className="mb-2 text-sm font-semibold">Legacy password</div>
      <p className="mb-3 text-xs text-muted">
        Sets the single shared fallback password used for password login. Distinct
        from each user&apos;s own password under Settings &gt; Account.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="password"
          aria-label="Legacy password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="New password (min 6 characters)"
          autoComplete="new-password"
          className="w-full max-w-xs rounded border border-border bg-bg px-2 py-1 text-xs"
        />
        <Button variant="primary" onClick={submit} loading={mutation.isPending} loadingLabel="Saving...">
          Update legacy password
        </Button>
      </div>
      {msg && <p className="mt-2 text-xs text-muted">{msg}</p>}
    </div>
  );
}

export function AutoAddNow(_props: CardProps) {
  const [msg, setMsg] = useState('');
  const mut = useMutation({
    mutationFn: api.autoAddNow,
    onSuccess: (r) => setMsg(r.message || 'Started.'),
    onError: (e: Error) => setMsg(`Error: ${e.message}`),
  });
  return (
    <div>
      <div className="mb-2 text-sm font-semibold">Auto-add now</div>
      <p className="mb-3 text-xs text-muted">
        Trigger the auto-add scheduler immediately. Pulls all enabled categories (trending,
        popular, per-service top lists) and queues new items.
      </p>
      <Button variant="primary" onClick={() => mut.mutate()} loading={mut.isPending} loadingLabel="Starting...">
        Run auto-add now
      </Button>
      {msg && <p className="mt-2 text-xs text-muted">{msg}</p>}
    </div>
  );
}

export function WebhookSecret(_props: CardProps) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['webhook-secret'], queryFn: api.webhookSecret });
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const rotate = useMutation({
    mutationFn: api.rotateWebhookSecret,
    onSuccess: () => {
      setConfirming(false);
      setCopied(false);
      setMsg('Rotated. Update Seerr, Radarr, Sonarr and the Jellyfin webhook plugin within 24 hours.');
      qc.invalidateQueries({ queryKey: ['webhook-secret'] });
      qc.invalidateQueries({ queryKey: ['admin-webhook-secret'] });
    },
    onError: (e: unknown) => setMsg(e instanceof Error ? e.message : 'rotate failed'),
  });
  const secret = data?.secret || '';
  const fromEnv = data?.source === 'env';
  const until = data?.previous_valid_until ? new Date(data.previous_valid_until) : null;
  return (
    <div className="grid gap-2 sm:grid-cols-[minmax(0,14rem)_1fr]">
      <div>
        <span className="text-sm font-medium">Webhook secret</span>
        <div className="mt-1 text-xs text-muted">Paste this into Seerr's webhook as the X-Webhook-Secret header. Generated once; set WEBHOOK_SECRET in the environment to choose your own.</div>
      </div>
      <div>
        <div className="flex items-center gap-2">
          <input type="text" readOnly aria-label="Webhook secret" value={secret} className="w-full max-w-md rounded border border-border bg-bg px-2 py-1 font-mono text-xs" />
          <Button onClick={() => { navigator.clipboard?.writeText(secret); setCopied(true); }}>{copied ? 'Copied' : 'Copy'}</Button>
          <Button onClick={() => { setConfirming(true); setMsg(null); }} disabled={fromEnv || confirming || rotate.isPending}
            title={fromEnv ? 'Set in the environment; change WEBHOOK_SECRET there' : undefined}>Rotate</Button>
        </div>
        {fromEnv && <p className="mt-1 text-xs text-muted">Set in the environment: change WEBHOOK_SECRET there and restart.</p>}
        {until && <p className="mt-1 text-xs text-muted">Previous secret valid until {until.toLocaleString()}.</p>}
        {confirming && (
          <div className="mt-2 rounded border border-border p-2 text-xs">
            <p>Issue a new secret? The current one keeps working for 24 hours. Update Seerr, Radarr, Sonarr and the Jellyfin webhook plugin in that window.</p>
            <div className="mt-2 flex gap-2">
              <Button variant="primary" onClick={() => rotate.mutate()} disabled={rotate.isPending}>{rotate.isPending ? 'Rotating...' : 'Confirm'}</Button>
              <Button onClick={() => setConfirming(false)}>Cancel</Button>
            </div>
          </div>
        )}
        {msg && <p className="mt-2 text-xs text-muted">{msg}</p>}
      </div>
    </div>
  );
}

export function FilterRulesLink(_props: CardProps) {
  return (
    <div className="grid gap-2 sm:grid-cols-[minmax(0,14rem)_1fr]">
      <div>
        <span className="text-sm font-medium">Filter rules</span>
        <div className="mt-1 text-xs text-muted">Which resolutions, sources, encodes, tags and languages are preferred, excluded or required.</div>
      </div>
      <Link to={{ hash: 'filter-rules' }} className="text-sm text-accent-light hover:underline">Open the Filter rules tab</Link>
    </div>
  );
}

export const CUSTOM_CARDS = { WebhookSecret, FilterRulesLink, GenreTabs, AutoAddNow, LegacyPassword };
