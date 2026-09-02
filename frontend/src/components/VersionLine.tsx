import { loginFlags } from '../api';

/** Which build is this? Read from the app-version meta tag _spa_index()
 * embeds, so it is correct before any API call resolves and works on the
 * pre-auth login page too. Shared by the login page and the app shell so the
 * two cannot drift apart. */
export function VersionLine({ className = '' }: { className?: string }) {
  const version = loginFlags().appVersion;
  return (
    <span
      data-testid="app-version"
      className={`inline-flex items-center gap-2 font-mono text-[10px] text-muted ${className}`}
    >
      {/* Deliberately neutral, not the success colour: nothing here checks
          whether anything is actually healthy. */}
      <span className="h-1.5 w-1.5 rounded-full bg-muted/60" />
      mycelium{version ? ` v${version}` : ''} &middot; self-hosted
    </span>
  );
}
