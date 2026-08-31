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
- Your debrid (TorBox / RealDebrid) API keys are used by Mycelium itself and
  are not shared with scrapers. All three scrapers are queried for torrent
  results only, and every release is resolved through Mycelium's own debrid
  client.
- The optional Debridio scraper needs its own Debridio API key, which the
  Stremio addon protocol carries in the request URL rather than a header.
  Mycelium scrubs that value, and any URL containing it, from its own logs
  and error messages. Set `DEBRIDIO_SEND_TORBOX_KEY=true` only if you
  deliberately want your TorBox key sent to Debridio as well.
