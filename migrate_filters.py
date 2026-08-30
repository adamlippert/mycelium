"""One-shot translation of the retired boolean filters into the rule model.

Runs once. The retired env vars stay in the user's .env after upgrading, so
re-running would read them again and overwrite any edit the user has since
made in the admin UI, which would make every new setting read-only. The
MIGRATION_MARKER stops that: once migrate() has written its rows, it sets the
marker and every later call is a no-op unless force=True is passed.
"""
import logging

log = logging.getLogger(__name__)

CAM_FAMILY = ["cam", "ts", "tc", "scr", "r5", "ppvrip"]
BLURAY_FAMILY = ["bluray", "bdrip", "brrip"]

# The retired _WEBDL_RE matched web-dl, webrip and web alike, so PREFER_WEBDL
# rewarded all three equally. Listing all three here reproduces today's
# ranking; a user who wants the finer distinction can remove entries in the
# admin UI afterwards.
WEBDL_FAMILY = ["webdl", "webrip", "web"]

MIGRATION_MARKER = "FILTER_RULES_MIGRATED"

# Retired settings could spell a value differently from the new vocabulary.
# _QUALITY_PATTERNS matched "2160p|4k|uhd", so all three meant 2160p.
_VALUE_ALIASES = {
    "resolution": {"4k": "2160p", "uhd": "2160p"},
}

# Retired key -> the key that replaces it, for the stale-.env warning.
RETIRED = {
    "QUALITY_PREFERENCE": "RESOLUTION_PREFERRED",
    "ALLOW_4K": "RESOLUTION_EXCLUDED",
    "EXCLUDE_REMUX": "SOURCE_EXCLUDED",
    "EXCLUDE_BLURAY": "SOURCE_EXCLUDED",
    "EXCLUDE_CAM": "SOURCE_EXCLUDED",
    "STRICT_NO_CAM": "SOURCE_STRICT",
    "EXCLUDE_DV_P5": "VISUAL_TAG_EXCLUDED",
    "PREFER_WEBDL": "SOURCE_PREFERRED",
    "PREFER_HEVC": "ENCODE_PREFERRED",
    "AUDIO_LANGUAGE_PREFERENCE": "LANGUAGE_PREFERRED",
    "EXCLUDE_LANGUAGES": "LANGUAGE_EXCLUDED",
}


def _sanitise(key: str, values: list[str]) -> list[str]:
    """Map known aliases, drop anything the new vocabulary cannot express.

    A migration must never raise. It runs at startup before the admin UI is
    reachable, so an exception here leaves the user unable to fix the value
    that is blocking boot.
    """
    import release_tags as rt
    import settings as _settings

    category = _settings._RULE_LIST_KEYS.get(key)
    if not category:
        return values
    vocabulary = rt.values_for(category)
    aliases = _VALUE_ALIASES.get(category, {})
    out = []
    for raw in values:
        value = aliases.get(raw, raw)
        if value in vocabulary:
            if value not in out:
                out.append(value)
        else:
            log.warning("Migration dropped %r from %s: no equivalent in the new "
                        "%s values. Set it in the admin UI if you need it.",
                        raw, key, category)
    return out


def migrate(dry_run: bool = False, force: bool = False) -> dict:
    """Translate the eleven retired settings into the new rule rows.

    Runs once, guarded by MIGRATION_MARKER. Without the guard, every startup
    would re-read the retired env vars (they are never removed from the
    user's .env by an upgrade) and clobber any edit the user has since made
    to the new settings in the admin UI, which would make all 35 of them
    silently read-only. Returns what was (or, in dry_run, would be) written.

    settings is imported lazily, not at module level: some tests pop
    "settings" out of sys.modules to force a reload, and a module-level
    import here would keep pointing at the stale pre-pop object, silently
    missing monkeypatches applied to the module a later `import settings`
    call actually resolves to. filter_rules.py and streams.py import settings
    this way for the same reason.
    """
    import settings as _settings

    if not force and _settings.get(MIGRATION_MARKER, False):
        log.debug("Filter rules already migrated; skipping")
        return {}

    out: dict = {}

    resolution_preferred = _sanitise(
        "RESOLUTION_PREFERRED", list(_settings.get("QUALITY_PREFERENCE", []) or []))
    if resolution_preferred:
        out["RESOLUTION_PREFERRED"] = resolution_preferred

    resolution_excluded = []
    if _settings.get("ALLOW_4K", True) is False:
        resolution_excluded.append("2160p")
    resolution_excluded = _sanitise("RESOLUTION_EXCLUDED", resolution_excluded)
    if resolution_excluded:
        out["RESOLUTION_EXCLUDED"] = resolution_excluded

    source_excluded = []
    if _settings.get("EXCLUDE_REMUX", False):
        source_excluded.append("remux")
    if _settings.get("EXCLUDE_BLURAY", False):
        source_excluded.extend(BLURAY_FAMILY)
    if _settings.get("EXCLUDE_CAM", False):
        source_excluded.extend(CAM_FAMILY)
    source_excluded = _sanitise("SOURCE_EXCLUDED", source_excluded)
    if source_excluded:
        out["SOURCE_EXCLUDED"] = source_excluded

    if _settings.get("PREFER_WEBDL", False):
        out["SOURCE_PREFERRED"] = _sanitise("SOURCE_PREFERRED", list(WEBDL_FAMILY))
    if _settings.get("PREFER_HEVC", False):
        out["ENCODE_PREFERRED"] = _sanitise("ENCODE_PREFERRED", ["hevc"])
    if _settings.get("EXCLUDE_DV_P5", False):
        out["VISUAL_TAG_EXCLUDED"] = _sanitise("VISUAL_TAG_EXCLUDED", ["dv_only"])

    if _settings.get("STRICT_NO_CAM", False):
        out["SOURCE_STRICT"] = True

    language_preferred = _sanitise(
        "LANGUAGE_PREFERRED", list(_settings.get("AUDIO_LANGUAGE_PREFERENCE", []) or []))
    if language_preferred:
        out["LANGUAGE_PREFERRED"] = language_preferred
    language_excluded = _sanitise(
        "LANGUAGE_EXCLUDED", list(_settings.get("EXCLUDE_LANGUAGES", []) or []))
    if language_excluded:
        out["LANGUAGE_EXCLUDED"] = language_excluded

    if not dry_run:
        for key, value in out.items():
            _settings.set(key, value)
        _settings.set(MIGRATION_MARKER, True)
        log.info("Filter migration wrote %d rule row(s)", len(out))
    return out


def warn_stale_env() -> list[str]:
    """Name retired keys the user actually set, so the warning means something.

    Probing config attributes warns everyone, because config.py always defines
    them with defaults. A warning that fires for every user trains people to
    ignore warnings. Checking os.environ also catches a key explicitly set to
    a falsy value, such as EXCLUDE_BLURAY=false, which a truthiness check on
    the parsed config value would miss.
    """
    import os

    messages = []
    for old, new in RETIRED.items():
        if old in os.environ:
            messages.append(
                f"{old} in your .env is no longer read; it was replaced by {new}. "
                f"Remove it to silence this warning."
            )
    for message in messages:
        log.warning("%s", message)
    return messages
