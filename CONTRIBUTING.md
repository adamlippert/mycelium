# Contributing

Thanks for looking. Mycelium is a self-hosted media pipeline, and most
useful contributions start as a bug report from someone running it in a
setup nobody else has.

## Reporting a bug

Open an issue with the version from the app footer (`mycelium vX.Y.Z`), what
you expected, what happened, and the relevant lines from `docker logs
mycelium`. **Scrub API keys and tokens before pasting logs.** Mycelium
redacts its own credentials from log lines, but the surrounding output is
yours to check.

For anything that looks like a security problem, do not open a public
issue: see [SECURITY.md](SECURITY.md).

## Getting set up

```bash
git clone https://github.com/adamlippert/mycelium.git
cd mycelium
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

cd frontend && npm install && cd ..
```

Run the three suites the way CI does:

```bash
python -m pytest tests/ -q            # backend
cd frontend && npx vitest run         # SPA
cd frontend && npx tsc --noEmit       # types, must stay at zero errors
cd spore-stream && go test ./...      # streaming front
```

## The shape of a change

- **Tests come with the change**, in the same commit. The suites are the
  only thing standing between a refactor and a silent regression in a
  pipeline most contributors cannot run end to end.
- **A test must fail without the fix.** A test written after the code that
  passes either way protects nothing. Break the implementation on purpose
  and confirm the test notices.
- **Explain the why in comments, not the what.** Much of this codebase deals
  with third-party behaviour that is not obvious from the code: rate limits,
  retention policies, media-server quirks. Those are the comments worth
  writing.
- **No em-dashes** anywhere in code, comments, or commit messages. A spaced
  double hyphen or a comma.
- **The repository is public.** No keys, tokens, or IP addresses in code,
  tests, fixtures, or commit messages.

## Frontend builds are committed

The built SPA under `static/app/` is checked in, because the Dockerfile
copies it when the npm build is skipped. If you change anything under
`frontend/src`, run `npm run build` and commit the result alongside your
source change, or the image ships a stale UI.

## Areas worth knowing about

- `catbox.py` -- lazy materialization. Torrents are added to the debrid
  provider at playback and released after idle, which is a policy
  requirement rather than an optimisation. Read the comments before changing
  the timing.
- `spore-stream/` -- the Go streaming front. Its byte math is pinned by
  golden fixtures generated from the Python implementation
  (`spore-stream/testdata/generate.py`); if you change one side, regenerate
  and check the other.
- `filter_rules.py` -- the four-state release filter. Each category votes
  independently over the whole candidate pool, so behaviour does not depend
  on rule order.

## Commits and pull requests

Conventional-commit prefixes (`feat:`, `fix:`, `docs:`, `perf:`, `test:`,
`chore:`). Say what changed and why it mattered; the diff already says how.

Open pull requests against `main`. CI runs all four checks above and they
must be green.
