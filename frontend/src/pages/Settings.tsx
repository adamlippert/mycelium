import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { api } from '../api';
import { usePlugins } from '../hooks/usePlugins';
import PluginSettingsCard from '../components/PluginSettingsCard';
import { Card, Toggle } from '../components/primitives';

// Short mono badge for a plugin's icon tile: initials of a multi-word label,
// otherwise the first two characters. Mirrors the abbr convention already
// used for watchlist sources (SourceCard: "TR" for Trakt, "MD" for MDBList).
function pluginAbbr(label: string): string {
  const words = label.trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return label.slice(0, 2).toUpperCase();
}

export default function Settings() {
  const { plugins } = usePlugins();
  const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session });
  const isAdmin = session?.user?.role === 'admin';

  const visiblePlugins = plugins.filter(p => {
    const anyFieldEnabled = (p.user_fields || []).some(f => !!(session?.user as any)?.[f]);
    return anyFieldEnabled || !!p.settings_ui;
  });

  return (
    <div className="space-y-6">
      <ChangePasswordCard />
      <MDBListCard />

      <section className="mb-8">
        <div className="mb-3">
          <h2 className="text-sm font-semibold text-body">Integrations</h2>
          <p className="text-xs text-muted">Watchlist sources and playback targets</p>
        </div>
        {visiblePlugins.length > 0 ? (
          <div className="space-y-4">
            {visiblePlugins.map(plugin => (
              <PluginCard key={plugin.name} plugin={plugin} session={session} />
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted">No integrations connected yet.</p>
        )}
      </section>

      <section>
        <div className="mb-3">
          <h2 className="text-sm font-semibold text-body">Preferences</h2>
          <p className="text-xs text-muted">Applies to your account only</p>
        </div>
        <div className="space-y-4">
          <PreferencesCard />
          {isAdmin && <NotificationsCard />}
        </div>
      </section>
    </div>
  );
}

function PluginCard({ plugin, session }: {
  plugin: ReturnType<typeof usePlugins>['plugins'][number];
  session: any;
}) {
  const hasFields = plugin.user_fields?.length > 0;
  const hasUi = !!plugin.settings_ui;

  // User-field toggles: only show if the admin has already enabled at least one
  // field for this user. This keeps toggles admin-controlled  -  users can turn
  // off what they have access to, but cannot self-grant new access.
  const anyFieldEnabled = hasFields &&
    plugin.user_fields.some(f => !!(session?.user as any)?.[f]);

  if (!anyFieldEnabled && !hasUi) return null;

  return (
    <Card className="space-y-4">
      <div className="flex items-center gap-3">
        <span
          className="flex h-9 w-9 flex-none items-center justify-center rounded-lg border font-mono text-[11px] font-bold"
          style={{
            background: 'rgba(97,82,223,0.15)',
            borderColor: 'rgba(159,146,255,0.3)',
            color: '#c7c2ff',
          }}
        >
          {pluginAbbr(plugin.label)}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-medium text-body">{plugin.label}</h2>
          {plugin.description && (
            <p className="mt-0.5 text-xs text-muted">{plugin.description}</p>
          )}
        </div>
      </div>

      {anyFieldEnabled && <PluginUserFieldsSection plugin={plugin} />}
      {hasUi && <PluginSettingsCard plugin={plugin} embedded />}
    </Card>
  );
}

function PluginUserFieldsSection({ plugin }: { plugin: ReturnType<typeof usePlugins>['plugins'][number] }) {
  const qc = useQueryClient();
  const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session });
  const mutation = useMutation({
    mutationFn: (fields: Record<string, boolean>) => api.setPluginFields(fields),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['session'] }),
  });

  return (
    <div className="flex flex-wrap gap-4">
      {plugin.user_fields.map(field => {
        const label = plugin.user_field_labels?.[field] || field;
        const value = !!(session?.user as any)?.[field];
        return (
          <div
            key={field}
            className={`flex items-center gap-2 ${mutation.isPending ? 'pointer-events-none opacity-50' : ''}`}
          >
            <span className="text-sm text-muted">{label}</span>
            <Toggle
              checked={value}
              onChange={(next) => mutation.mutate({ [field]: next })}
              label={label}
            />
          </div>
        );
      })}
    </div>
  );
}

function PreferencesCard() {
  const qc = useQueryClient();
  const { data: session } = useQuery({ queryKey: ['session'], queryFn: api.session });
  const clickJellyfin = !!(session?.user as any)?.library_click_jellyfin;
  const jellyfinUrl = session?.jellyfin_url;

  const mutation = useMutation({
    mutationFn: (prefs: Record<string, boolean | string>) => api.setPreferences(prefs),
    onError: () => {
      // Revert optimistic update on failure
      qc.invalidateQueries({ queryKey: ['session'] });
    },
  });

  const toggle = () => {
    const newVal = !clickJellyfin;
    // Optimistic update: immediately flip in the shared session cache so
    // Library.tsx (which reads the same cache) picks it up without a reload.
    qc.setQueryData(['session'], (old: any) =>
      old ? { ...old, user: { ...old.user, library_click_jellyfin: newVal } } : old,
    );
    mutation.mutate({ library_click_jellyfin: newVal });
  };

  const [includeLang, setIncludeLang] = useState((session?.user as any)?.discover_language_include || '');
  const [excludeLang, setExcludeLang] = useState((session?.user as any)?.discover_language_exclude || '');
  useEffect(() => {
    setIncludeLang((session?.user as any)?.discover_language_include || '');
    setExcludeLang((session?.user as any)?.discover_language_exclude || '');
  }, [session]);

  const saveLanguages = () => {
    mutation.mutate({
      discover_language_include: includeLang,
      discover_language_exclude: excludeLang,
    });
  };

  return (
    <div className="bg-card rounded-lg border border-border p-6">
      <div className="space-y-3">
        <label className="flex items-start gap-3 cursor-pointer select-none" onClick={toggle}>
          <div className="mt-0.5 flex-shrink-0">
            <div className={`w-10 h-5 rounded-full transition-colors flex items-center px-0.5
                ${clickJellyfin ? 'bg-accent' : 'bg-border'}`}
            >
              <div className={`w-4 h-4 rounded-full bg-white shadow transition-transform
                ${clickJellyfin ? 'translate-x-5' : 'translate-x-0'}`} />
            </div>
          </div>
          <div>
            <div className="text-sm font-medium">Open library items in Jellyfin</div>
            <div className="text-xs text-muted mt-0.5">
              Clicking a poster in the Library tab opens the item in Jellyfin web instead of showing the detail modal.
              {!jellyfinUrl && (
                <span className="text-warn ml-1">(Jellyfin URL not configured)</span>
              )}
            </div>
          </div>
        </label>

        <div className="border-t border-border pt-3">
          <div className="text-sm font-medium mb-1">Discover language filter</div>
          <p className="text-xs text-muted mb-2">
            Comma-separated ISO 639-1 codes (e.g. <code>en,nl</code>). Only-include takes priority over exclude.
            Leave both empty to show everything.
          </p>
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              type="text"
              value={includeLang}
              onChange={(e) => setIncludeLang(e.target.value)}
              placeholder="Only show (e.g. en,nl)"
              className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm
                         placeholder:text-muted focus:outline-none focus:border-accent"
            />
            <input
              type="text"
              value={excludeLang}
              onChange={(e) => setExcludeLang(e.target.value)}
              placeholder="Hide (e.g. ru,hi)"
              className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm
                         placeholder:text-muted focus:outline-none focus:border-accent"
            />
            <button
              onClick={saveLanguages}
              disabled={mutation.isPending}
              className="px-3 py-1.5 rounded bg-accent text-sm font-semibold disabled:opacity-50 whitespace-nowrap"
            >
              {mutation.isPending ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


function NotificationsCard() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['settings'], queryFn: api.settings });
  const group = data?.groups.find((g) => g.id === 'notifications');
  const valueOf = (key: string) => group?.items.find((i) => i.key === key)?.value;

  const [notifySuccess, setNotifySuccess] = useState(true);
  const [notifyFailure, setNotifyFailure] = useState(true);
  const [discordUrl, setDiscordUrl] = useState('');
  const [telegramToken, setTelegramToken] = useState('');
  const [telegramChat, setTelegramChat] = useState('');
  const [msg, setMsg] = useState('');

  useEffect(() => {
    if (!group) return;
    setNotifySuccess(!!valueOf('NOTIFY_ON_SUCCESS'));
    setNotifyFailure(!!valueOf('NOTIFY_ON_FAILURE'));
    setDiscordUrl(valueOf('DISCORD_WEBHOOK_URL') || '');
    setTelegramToken(valueOf('TELEGRAM_BOT_TOKEN') || '');
    setTelegramChat(valueOf('TELEGRAM_CHAT_ID') || '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const saveMutation = useMutation({
    mutationFn: () => api.setNotificationSettings({
      NOTIFY_ON_SUCCESS: notifySuccess,
      NOTIFY_ON_FAILURE: notifyFailure,
      DISCORD_WEBHOOK_URL: discordUrl,
      TELEGRAM_BOT_TOKEN: telegramToken,
      TELEGRAM_CHAT_ID: telegramChat,
    }),
    onSuccess: () => { setMsg('Saved.'); qc.invalidateQueries({ queryKey: ['settings'] }); },
    onError: (e: any) => setMsg(`Error: ${e.message}`),
  });

  return (
    <div className="bg-card rounded-lg border border-border p-6">
      <h2 className="text-base font-bold mb-1">Notifications</h2>
      <p className="text-muted text-xs mb-4">
        Discord and/or Telegram alerts when a request succeeds or fails. Admin-only.
      </p>
      <div className="space-y-3 max-w-lg">
        <div className="flex gap-4">
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={notifySuccess} onChange={(e) => setNotifySuccess(e.target.checked)} />
            Notify on success
          </label>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={notifyFailure} onChange={(e) => setNotifyFailure(e.target.checked)} />
            Notify on failure
          </label>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Discord webhook URL</label>
          <input
            type="text"
            value={discordUrl}
            onChange={(e) => setDiscordUrl(e.target.value)}
            placeholder="https://discord.com/api/webhooks/..."
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm
                       placeholder:text-muted focus:outline-none focus:border-accent"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-xs text-muted mb-1">Telegram bot token</label>
            <input
              type="text"
              value={telegramToken}
              onChange={(e) => setTelegramToken(e.target.value)}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent"
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">Telegram chat id</label>
            <input
              type="text"
              value={telegramChat}
              onChange={(e) => setTelegramChat(e.target.value)}
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent"
            />
          </div>
        </div>
        <button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="px-4 py-2 rounded-lg bg-accent hover:bg-accent/90 disabled:opacity-60 font-semibold text-sm"
        >
          {saveMutation.isPending ? 'Saving...' : 'Save'}
        </button>
        {msg && <p className="text-xs text-muted">{msg}</p>}
      </div>
    </div>
  );
}


function MDBListCard() {
  const qc = useQueryClient();
  const { data: status } = useQuery({ queryKey: ['mdblist-status'], queryFn: api.mdblistStatus });
  const { data: listsData } = useQuery({
    queryKey: ['mdblist-lists'],
    queryFn: api.mdblistLists,
    enabled: !!status?.connected,
  });
  const [apiKey, setApiKey] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    setSelected((status?.list_ids || '').split(',').filter(Boolean));
  }, [status]);

  const connectMutation = useMutation({
    mutationFn: () => api.mdblistConnect(apiKey),
    onSuccess: () => { setApiKey(''); qc.invalidateQueries({ queryKey: ['mdblist-status'] }); },
    onError: (e: any) => setMsg(`Error: ${e.message}`),
  });
  const disconnectMutation = useMutation({
    mutationFn: api.mdblistDisconnect,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['mdblist-status'] }),
  });
  const setListsMutation = useMutation({
    mutationFn: (ids: string[]) => api.mdblistSetLists(ids),
    onSuccess: () => setMsg('Lists saved.'),
  });
  const syncMutation = useMutation({
    mutationFn: api.mdblistSync,
    onSuccess: (data) => setMsg(`Queued ${data.added} new item${data.added === 1 ? '' : 's'}.`),
    onError: (e: any) => setMsg(`Error: ${e.message}`),
  });

  const toggleList = (id: string) => {
    const next = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id];
    setSelected(next);
    setListsMutation.mutate(next);
  };

  return (
    <div className="bg-card rounded-lg border border-border p-6">
      <h2 className="text-base font-bold mb-1">MDBList</h2>
      <p className="text-muted text-xs mb-4">
        Connect your MDBList API key (from{' '}
        <a href="https://mdblist.com/preferences" target="_blank" rel="noreferrer" className="text-accent underline">
          mdblist.com/preferences
        </a>) to sync your lists and auto-request new items.
      </p>

      {status?.connected ? (
        <div className="space-y-3">
          {listsData?.lists && listsData.lists.length > 0 && (
            <div className="space-y-1">
              <p className="text-xs text-muted mb-1">Lists to sync:</p>
              {listsData.lists.map((l) => (
                <label key={l.id} className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selected.includes(String(l.id))}
                    onChange={() => toggleList(String(l.id))}
                  />
                  {l.name}
                </label>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => syncMutation.mutate()}
              disabled={syncMutation.isPending}
              className="px-3 py-1.5 rounded bg-accent text-sm font-semibold disabled:opacity-50"
            >
              {syncMutation.isPending ? 'Syncing...' : 'Sync now'}
            </button>
            <button
              onClick={() => disconnectMutation.mutate()}
              disabled={disconnectMutation.isPending}
              className="px-3 py-1.5 rounded border border-danger text-danger text-sm font-medium disabled:opacity-50"
            >
              Disconnect
            </button>
          </div>
          {msg && <p className="text-xs text-muted">{msg}</p>}
        </div>
      ) : (
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="MDBList API key"
            className="flex-1 bg-bg border border-border rounded-lg px-3 py-2 text-sm
                       placeholder:text-muted focus:outline-none focus:border-accent"
          />
          <button
            onClick={() => connectMutation.mutate()}
            disabled={connectMutation.isPending || !apiKey}
            className="px-4 py-2 rounded-lg bg-accent hover:bg-accent/90 disabled:opacity-60 font-semibold text-sm whitespace-nowrap"
          >
            {connectMutation.isPending ? 'Connecting...' : 'Connect'}
          </button>
        </div>
      )}
    </div>
  );
}


function ChangePasswordCard() {
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  const mutation = useMutation({
    mutationFn: () => api.changePassword(current, password),
    onSuccess: () => {
      setSuccess(true);
      setCurrent(''); setPassword(''); setConfirm('');
      setTimeout(() => setSuccess(false), 3000);
    },
    onError: (e: any) => setError(e.message || 'Failed to change password'),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password.length < 6) { setError('At least 6 characters required'); return; }
    if (password !== confirm) { setError('Passwords do not match'); return; }
    mutation.mutate();
  };

  return (
    <div className="bg-card rounded-lg border border-border p-6">
      <h2 className="text-base font-bold mb-4">Change password</h2>
      {success && <p className="text-ok text-sm mb-3">Password changed successfully.</p>}
      <form onSubmit={submit} className="space-y-3 max-w-sm">
        <div>
          <label className="block text-xs text-muted mb-1">Current password</label>
          <input type="password" value={current} onChange={e => setCurrent(e.target.value)}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent" />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">New password</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent" />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Confirm new password</label>
          <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent" />
        </div>
        {error && <p className="text-danger text-xs">{error}</p>}
        <button type="submit" disabled={mutation.isPending}
          className="px-4 py-2 rounded-lg bg-accent hover:bg-accent/90 disabled:opacity-60 font-semibold text-sm">
          {mutation.isPending ? 'Saving...' : 'Change password'}
        </button>
      </form>
    </div>
  );
}
