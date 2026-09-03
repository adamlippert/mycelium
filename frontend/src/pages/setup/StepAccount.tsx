import type { Dispatch, SetStateAction } from 'react';

export type Account = { username: string; password: string; confirm: string };

export const EMPTY_ACCOUNT: Account = { username: '', password: '', confirm: '' };

/** Shown only when authentication is on and this install has no credential of
 * any kind. Without it, finishing the wizard marks setup complete and closes
 * the first-admin window, leaving an install nobody can log into. */
export default function StepAccount({
  account,
  setAccount,
}: {
  account: Account;
  setAccount: Dispatch<SetStateAction<Account>>;
}) {
  const field =
    'w-full rounded-lg border border-border bg-bg px-4 py-2.5 text-sm text-white outline-none focus:border-accent';
  const label = 'mb-1 block text-[10px] font-semibold uppercase tracking-wider text-muted';

  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">Create your admin account</h2>
      <p className="mb-4 text-[13px] leading-relaxed text-muted">
        Authentication is turned on for this install, so it needs an account before it can
        be used. This one is an administrator.
      </p>
      <div className="space-y-3">
        <div>
          <label htmlFor="setup-username" className={label}>
            Username
          </label>
          <input
            id="setup-username"
            type="text"
            autoComplete="username"
            value={account.username}
            onChange={(e) => setAccount((a) => ({ ...a, username: e.target.value }))}
            className={field}
          />
        </div>
        <div>
          <label htmlFor="setup-password" className={label}>
            Password
          </label>
          <input
            id="setup-password"
            type="password"
            autoComplete="new-password"
            value={account.password}
            onChange={(e) => setAccount((a) => ({ ...a, password: e.target.value }))}
            className={field}
          />
        </div>
        <div>
          <label htmlFor="setup-confirm" className={label}>
            Confirm password
          </label>
          <input
            id="setup-confirm"
            type="password"
            autoComplete="new-password"
            value={account.confirm}
            onChange={(e) => setAccount((a) => ({ ...a, confirm: e.target.value }))}
            className={field}
          />
        </div>
      </div>
      <p className="mt-4 text-[13px] leading-relaxed text-muted">
        Keep these somewhere safe. There is no password reset, and this account is the only
        way in until you add another.
      </p>
    </div>
  );
}
