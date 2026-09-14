"""docs/COMPATIBILITY.md is the promise; these tests keep it equal to the
code. A variable in config.py that is in no tier, a route missing from the
frozen list, or a deprecated name without a replacement fails here."""
import os
import re
import sys

import settings

_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import route_table  # noqa: E402

DOC = open(os.path.join(_ROOT, "docs", "COMPATIBILITY.md"), encoding="utf-8").read()
FROZEN_PREFIXES = ("/webhook", "/torbox-webhook", "/stream/", "/spore-stream/", "/internal/", "/health", "/healthz", "/metrics", "/setup", "/docs/")


def _block(marker):
    m = re.search(rf"<!-- {marker} -->\s*```\n(.*?)```", DOC, re.S)
    assert m, f"missing block {marker}"
    return [l.strip() for l in m.group(1).splitlines() if l.strip()]


def _config_vars():
    src = open(os.path.join(_ROOT, "config.py")).read()
    return set(re.findall(r"^([A-Z][A-Z0-9_]+)\s*=\s*_env", src, re.M))


def test_variable_tiers_match_the_schema_and_config():
    listed = {f["key"]: f for s in settings.SECTIONS for f in s["fields"] if f["kind"] != "custom"}
    supported = {k for k, f in listed.items() if not f.get("advanced")}
    advanced = {k for k, f in listed.items() if f.get("advanced")}
    internal = set(settings._UNLISTED_KEYS)
    deployment = _config_vars() - set(listed) - internal
    assert set(_block("tier: supported")) == supported
    assert set(_block("tier: advanced")) == advanced
    assert set(_block("tier: internal")) == internal
    assert set(_block("tier: deployment")) == deployment
    assert not (supported & advanced) and not (set(listed) & internal)


def test_frozen_routes_match_the_registered_ones():
    registered = {f"{m} {p}" for m, p in route_table.parse(route_table.sources()) if p.startswith(FROZEN_PREFIXES)}
    assert set(_block("routes")) == registered


def test_every_deprecation_names_a_replacement_and_a_changelog_line():
    import deprecations
    changelog = open(os.path.join(_ROOT, "CHANGELOG.md")).read()
    for old, new in deprecations.DEPRECATED.items():
        assert new and new != old
        assert old in changelog, f"{old} deprecated without a changelog line"
