import { useLocation } from 'react-router-dom';
import { api, csrfToken } from '../api';
import { BrandMark } from '../components/shell/BrandMark';

/** The ?next= param, sanitised the same way the server sanitises the
 * submitted "next" form field (login_submit in app.py): must start with a
 * single "/", otherwise treated as absent. Returns '' when absent so the
 * OIDC link can tell "no next" apart from "next is /". */
function rawNext(search: string): string {
  const raw = new URLSearchParams(search).get('next') || '';
  if (!raw.startsWith('/') || raw.startsWith('//')) return '';
  return raw;
}

/** Mirrors templates/login.html: error=oidc gets its own message, any other
 * truthy error value is a generic invalid-credentials banner. */
function errorMessage(search: string): string | null {
  const err = new URLSearchParams(search).get('error');
  if (!err) return null;
  if (err === 'oidc') return 'SSO sign-in failed. Try again or use password.';
  return 'Invalid credentials.';
}

export default function Login() {
  const location = useLocation();
  const raw = rawNext(location.search);
  const next = raw || '/';
  const error = errorMessage(location.search);
  const flags = api.loginFlags();
  const oidcHref = raw ? `/login/oidc?next=${encodeURIComponent(raw)}` : '/login/oidc';
  const showOrDivider = flags.oidcEnabled && flags.passwordEnabled;
  const showPasswordForm = flags.passwordEnabled || !flags.oidcEnabled;

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-6">
      <div className="pointer-events-none absolute inset-0 opacity-25 blur-3xl" aria-hidden="true">
        <div className="absolute left-[22%] top-[28%] h-72 w-72 rounded-full bg-accent" />
        <div className="absolute right-[18%] top-[8%] h-72 w-72 rounded-full bg-accent-light" />
        <div className="absolute bottom-[6%] left-[42%] h-72 w-72 rounded-full bg-danger" />
      </div>

      <div className="relative w-full max-w-sm rounded-2xl border border-border bg-card/90 p-8 shadow-2xl backdrop-blur">
        <div className="mb-6 flex flex-col items-center gap-3 text-center">
          <div className="flex items-center gap-2.5">
            <BrandMark />
            <span className="font-mono text-2xl font-bold tracking-wide text-white">
              myc<span className="text-accent-pale">3</span>l<span className="text-accent-pale">1</span>um
            </span>
          </div>
          <span className="text-xs text-muted">the hidden network beneath your media library</span>
        </div>

        {error && (
          <div className="mb-4 rounded border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
            {error}
          </div>
        )}

        {flags.oidcEnabled && (
          <>
            <a
              href={oidcHref}
              className="mb-4 block rounded-lg border border-border bg-card-raised py-2.5 text-center
                         text-sm font-semibold text-body hover:bg-card-raised/80"
            >
              Continue with {flags.oidcProvider}
            </a>
            {showOrDivider && (
              <div className="mb-4 flex items-center gap-3 text-[10px] font-semibold uppercase tracking-wider text-muted">
                <span className="h-px flex-1 bg-border" />
                or
                <span className="h-px flex-1 bg-border" />
              </div>
            )}
          </>
        )}

        {showPasswordForm && (
          <form method="post" action="/login" className="space-y-3">
            <input type="hidden" name="csrf_token" value={csrfToken()} />
            <input type="hidden" name="next" value={next} />
            <div>
              <label
                htmlFor="login-username"
                className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-muted"
              >
                Username
              </label>
              <input
                id="login-username"
                type="text"
                name="username"
                autoComplete="username"
                autoFocus
                required
                className="w-full rounded-lg border border-border bg-bg px-4 py-2.5 text-sm text-white
                           outline-none focus:border-accent"
              />
            </div>
            <div>
              <label
                htmlFor="login-password"
                className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-muted"
              >
                Password
              </label>
              <input
                id="login-password"
                type="password"
                name="password"
                autoComplete="current-password"
                required
                className="w-full rounded-lg border border-border bg-bg px-4 py-2.5 text-sm text-white
                           outline-none focus:border-accent"
              />
            </div>
            <button
              type="submit"
              className="mt-1 w-full rounded-lg bg-accent py-2.5 text-sm font-semibold text-white
                         hover:bg-accent/90"
            >
              Sign in
            </button>
          </form>
        )}

        <div className="mt-6 flex items-center justify-center gap-2 font-mono text-[10px] text-muted">
          <span className="h-1.5 w-1.5 rounded-full bg-ok" />
          <span>mycelium{flags.appVersion ? ` v${flags.appVersion}` : ''} &middot; self-hosted</span>
        </div>
      </div>
    </div>
  );
}
