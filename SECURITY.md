# Security Policy

## Supported versions

Only the latest release receives security fixes. Mycelium is a self-hosted
project; keeping your deployment on the newest tag is the supported
configuration.

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's vulnerability
reporting: go to the repository's **Security** tab and click **Report a
vulnerability** (or open
https://github.com/adamlippert/mycelium/security/advisories/new).

Please do NOT open a public issue for a security problem, and do not include
working exploits in public discussions.

You can expect an initial response within a week. Fixes ship as a normal
release; the advisory is published after a fix is available.

## Scope notes for deployers

- Mycelium is designed to sit behind a reverse proxy (HTTPS) with
  `AUTH_ENABLED=true` for any internet-facing deployment. The setup wizard
  walks through this.
- The session secret is auto-generated and persisted on first start when the
  environment does not provide one; set `AUTH_SESSION_SECRET` yourself if you
  want sessions to survive database restores.
- `/stream/<token>` and `/spore-stream/<token>` are unauthenticated by design
  (media players cannot log in); the random per-item token is the capability.
  Treat those URLs like credentials.
- Debrid API keys configured in Mycelium are sent to the corresponding
  third-party services. The Debridio integration embeds keys in request URLs
  because the Stremio addon protocol has no header authentication; Mycelium
  scrubs these values from its own logs and error messages.
