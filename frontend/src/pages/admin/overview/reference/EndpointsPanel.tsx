import { Link } from 'react-router-dom';

export function EndpointRow({ label, hint, value }: { label: string; hint: string; value: string }) {
  return (
    <div>
      <div className="mb-1 text-[11px] text-muted">
        {label} ({hint})
      </div>
      <div className="flex items-center gap-2">
        <code className="flex-1 truncate rounded bg-white/5 px-2 py-1.5 text-xs text-body">{value}</code>
        <button
          type="button"
          onClick={() => navigator.clipboard.writeText(value)}
          className="rounded border border-border px-2 py-1 text-xs text-muted transition hover:text-white"
        >
          Copy
        </button>
      </div>
    </div>
  );
}

export function EndpointsPanel({ secret, loading, error }: {
  secret: { secret: string } | undefined; loading: boolean; error: boolean;
}) {
  return (
    <div className="space-y-3">
      <EndpointRow
        label="Seerr webhook URL"
        hint="already configured"
        value={`${window.location.origin}/webhook`}
      />
      <EndpointRow
        label="TorBox push notification URL"
        hint="configure in TorBox settings to skip polling"
        value={`${window.location.origin}/torbox-webhook`}
      />
      <EndpointRow
        label="Catbox stream prefix"
        hint=".strm files contain proxy URLs starting with this"
        value={`${window.location.origin}/stream/<token>`}
      />
      <div>
        <div className="mb-1 text-[11px] text-muted">Webhook secret (send as header X-Webhook-Secret)</div>
        {loading ? (
          <p className="text-xs text-muted">Loading…</p>
        ) : error || !secret ? (
          <p className="text-xs text-muted">unavailable</p>
        ) : (
          <div className="flex items-center gap-2">
            <code className="flex-1 truncate rounded bg-white/5 px-2 py-1.5 text-xs text-body">
              {secret.secret}
            </code>
            <button
              type="button"
              onClick={() => navigator.clipboard.writeText(secret.secret)}
              className="rounded border border-border px-2 py-1 text-xs text-muted transition hover:text-white"
            >
              Copy
            </button>
          </div>
        )}
      </div>
      <p className="text-[11px] text-white/30">
        Also on <Link to={{ hash: 'settings' }} className="text-accent-light hover:underline">Settings</Link>, where the secret can be rotated.
      </p>
    </div>
  );
}
