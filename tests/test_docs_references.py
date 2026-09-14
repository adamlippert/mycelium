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
                                # config.py (config.py has no matching `= _env(` assignment)
    "RETRY_BACKOFF_MINUTES",   # real config.py variable, but assigned through a list
                                # comprehension (`= [int(x) for x in _env(...)]`), so the
                                # known-vars regex, which only matches `VAR = _env(`, misses it
    # The seven-category, four-state filter rule model (RESOLUTION, SOURCE, ENCODE,
    # VISUAL_TAG, AUDIO_TAG, AUDIO_CHANNELS, LANGUAGE): all real config.py variables,
    # but each is assigned through a list comprehension
    # (`= [v.strip().lower() for v in _env(...)]`), which the known-vars regex misses
    # the same way it misses RETRY_BACKOFF_MINUTES above. Only the `_STRICT` sibling of
    # each category is a plain `= _env(...)` boolean, so those are matched already.
    "RESOLUTION_PREFERRED", "RESOLUTION_EXCLUDED", "RESOLUTION_REQUIRED", "RESOLUTION_INCLUDED",
    "SOURCE_PREFERRED", "SOURCE_EXCLUDED", "SOURCE_REQUIRED", "SOURCE_INCLUDED",
    "ENCODE_PREFERRED", "ENCODE_EXCLUDED", "ENCODE_REQUIRED", "ENCODE_INCLUDED",
    "VISUAL_TAG_PREFERRED", "VISUAL_TAG_EXCLUDED", "VISUAL_TAG_REQUIRED", "VISUAL_TAG_INCLUDED",
    "AUDIO_TAG_PREFERRED", "AUDIO_TAG_EXCLUDED", "AUDIO_TAG_REQUIRED", "AUDIO_TAG_INCLUDED",
    "AUDIO_CHANNELS_PREFERRED", "AUDIO_CHANNELS_EXCLUDED", "AUDIO_CHANNELS_REQUIRED",
    "AUDIO_CHANNELS_INCLUDED",
    "LANGUAGE_PREFERRED", "LANGUAGE_EXCLUDED", "LANGUAGE_REQUIRED", "LANGUAGE_INCLUDED",
}
ROUTE_PREFIXES = ("/webhook", "/stream", "/spore-stream", "/health", "/metrics", "/setup", "/ui/api/", "/internal/")


def _known_vars():
    src = open(os.path.join(_ROOT, "config.py")).read()
    known = set(re.findall(r"^([A-Z][A-Z0-9_]+)\s*=\s*_env", src, re.M))
    known |= {f["key"] for s in settings.SECTIONS for f in s["fields"] if f["kind"] != "custom"}
    known |= set(settings._UNLISTED_KEYS)
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
