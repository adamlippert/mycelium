"""Every variable and route the docs name must exist. A removal fails here
until the docs follow."""
import os
import re
import sys

import settings

_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import route_table  # noqa: E402

FILES = ["README.md", "docs/install-guide.html", "docs/INTEGRATIONS.md", "docs/SCALING.md", "docs/RECOVERY.md", "docs/COMPATIBILITY.md", ".env.example"]
# Backticked upper-case tokens that are not Mycelium variables.
NOT_VARIABLES = {
    "PUID", "PGID",            # container user ids, documented as Docker knobs
    "TZ",                      # container timezone
    "GET", "POST", "DELETE",   # HTTP methods in route prose
    "JSON", "URL", "API",      # plain words
    "HEALTHCHECK",             # Docker's own HEALTHCHECK instruction, not a Mycelium variable
    "CMD",                     # Docker's own CMD instruction, not a Mycelium variable
    "APP_VERSION",             # Python attribute in version.py, not an environment variable
    "INFO",                    # example LOG_LEVEL value in a table cell, not a variable name
    "SSO",                     # example OIDC_PROVIDER_NAME value in a table cell
    "NULL",                    # SQL keyword in RECOVERY.md prose
    "REMUX",                   # example release label, not a variable name
    "PLAY_GAP_SEC",            # module constant in egress_estimate.py (a plain int literal,
                                # not read from the environment), not a config.py variable
    "GUNICORN_THREADS", "GUNICORN_PORT",  # read by the Go streaming front / entrypoint
                                           # shell, not by config.py
    "STREAM_FRONT_ENABLED",    # read by the Go streaming front / entrypoint shell, not by
                                # config.py at all (no `_env(...)` call for it there)
}
# RETRY_BACKOFF_MINUTES and the seven-category, four-state filter rule model
# (RESOLUTION_PREFERRED, SOURCE_EXCLUDED, ... down to LANGUAGE_STRICT, 35
# keys) used to need an entry here too: they are real config.py variables,
# but each is assigned through a list comprehension
# (`VAR = [v.strip().lower() for v in _env("VAR", ...).split(",")]`) rather
# than a plain `VAR = _env(...)`, which the old known-vars regex missed
# entirely. `_known_vars()` below now matches every `_env(...)`/`_env_int(...)`
# call regardless of assignment form, so they are found directly and no
# longer need an allow-list entry.
ROUTE_PREFIXES = ("/webhook", "/stream", "/spore-stream", "/health", "/metrics", "/setup", "/ui/api/", "/internal/")


def _known_vars():
    # Every _env(...)/_env_int(...) call with a literal name, regardless of
    # how the result is assigned (plain assignment, list comprehension,
    # float()/bool wrapper, ...). See tests/test_compatibility.py's
    # _config_vars() for the same fix and why the old assignment-anchored
    # regex missed the whole filter-rule model and RETRY_BACKOFF_MINUTES.
    src = open(os.path.join(_ROOT, "config.py")).read()
    known = set(re.findall(r'_env\w*\(\s*"([A-Z][A-Z0-9_]+)"', src))
    known |= {f["key"] for s in settings.SECTIONS for f in s["fields"] if f["kind"] != "custom"}
    known |= set(settings._UNLISTED_KEYS)
    # The filter-rule model has its own admin tab (Filtering rules), built
    # from SETTING_GROUPS rather than SECTIONS; its keys are already caught
    # by the config.py scan above, but naming the group here too keeps this
    # helper self-explanatory about where they are editable.
    known |= set(next(g for g in settings.SETTING_GROUPS if g["id"] == "filter_rules")["keys"])
    return known


def _shape(path):
    return re.sub(r"<[^>]+>", "<x>", path.rstrip("/"))


def test_documented_variables_exist():
    known = _known_vars()
    unknown = {}
    for f in FILES:
        text = open(os.path.join(_ROOT, f), encoding="utf-8").read()
        tokens = set(re.findall(r"`([A-Z][A-Z0-9_]{2,})`", text))
        if f == ".env.example":
            tokens = set(re.findall(r"^([A-Z][A-Z0-9_]+)=", text, re.M))
        bad = tokens - known - NOT_VARIABLES
        if bad:
            unknown[f] = sorted(bad)
    assert unknown == {}


def test_documented_routes_exist():
    registered = {_shape(p) for _, p in route_table.parse(route_table.sources())}
    unknown = {}
    for f in FILES:
        text = open(os.path.join(_ROOT, f), encoding="utf-8").read()
        paths = {m for m in re.findall(r"`((?:/[\w<>:.-]+)+)`", text) if m.startswith(ROUTE_PREFIXES)}
        bad = {p for p in paths if _shape(p) not in registered}
        if bad:
            unknown[f] = sorted(bad)
    assert unknown == {}
