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
    # Every _env(...)/_env_int(...) call with a literal name, regardless of
    # how the result is assigned: a plain `VAR = _env(...)`, a list
    # comprehension (`VAR = [x for x in _env(...).split(...)]`), a float()
    # or bool expression wrapped around it, all count. The old regex only
    # matched the first form and silently missed every filter-rule category
    # key (RESOLUTION_PREFERRED and friends) plus RETRY_BACKOFF_MINUTES.
    src = open(os.path.join(_ROOT, "config.py")).read()
    return set(re.findall(r'_env\w*\(\s*"([A-Z][A-Z0-9_]+)"', src))


def _rule_keys():
    # The seven-category, four-state filter-rule model plus its strict
    # toggles (RESOLUTION_PREFERRED/_EXCLUDED/_REQUIRED/_INCLUDED/_STRICT and
    # its six siblings): all real config.py variables, all editable from the
    # admin Filtering rules tab, which is not built from settings.SECTIONS
    # (see settings.py's own comment on SETTING_GROUPS) so they need this
    # separate source rather than the settings.SECTIONS scan below.
    group = next(g for g in settings.SETTING_GROUPS if g["id"] == "filter_rules")
    return set(group["keys"])


def test_variable_tiers_match_the_schema_and_config():
    listed = {f["key"]: f for s in settings.SECTIONS for f in s["fields"] if f["kind"] != "custom"}
    rule_keys = _rule_keys()
    supported = {k for k, f in listed.items() if not f.get("advanced")} | rule_keys
    advanced = {k for k, f in listed.items() if f.get("advanced")}
    internal = set(settings._UNLISTED_KEYS)
    deployment = _config_vars() - set(listed) - internal - rule_keys
    assert set(_block("tier: supported")) == supported
    assert set(_block("tier: advanced")) == advanced
    assert set(_block("tier: internal")) == internal
    assert set(_block("tier: deployment")) == deployment
    assert not (supported & advanced) and not (set(listed) & internal) and not (rule_keys & advanced)


def test_frozen_routes_match_the_registered_ones():
    registered = {f"{m} {p}" for m, p in route_table.parse(route_table.sources()) if p.startswith(FROZEN_PREFIXES)}
    assert set(_block("routes")) == registered


def test_every_deprecation_names_a_replacement_and_a_changelog_line():
    import deprecations
    changelog = open(os.path.join(_ROOT, "CHANGELOG.md")).read()
    for old, new in deprecations.DEPRECATED.items():
        assert new and new != old
        assert old in changelog, f"{old} deprecated without a changelog line"
