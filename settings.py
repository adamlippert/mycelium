"""Runtime-editable settings overlay.

Reads DB-stored overrides first, falls back to the static config module
values loaded from .env at startup. Type-aware: bool keys are normalised,
list keys split on commas, integer values parsed.

UI sections come from SECTIONS, with SETTING_GROUPS derived from it for
the Filter rules tab.
"""
from __future__ import annotations

import logging

import config as _config
import db
import release_tags as _rt
import streams as _streams

log = logging.getLogger(__name__)

# Type hints per key  -  drives parsing of stored strings.
_BOOL_KEYS = {
    "PREFER_SMALLER_FILES",
    "EXCLUDE_UNDERSIZED_RELEASES",
    "EXCLUDE_UNDERSIZED_STRICT",
    "CATBOX_MODE",
    "CATBOX_PRELOAD",
    "ALLOW_4K",
    "EXCLUDE_REMUX",
    "EXCLUDE_BLURAY",
    "EXCLUDE_CAM",
    "STRICT_NO_CAM",
    "PREFER_WEBDL",
    "PREFER_HEVC",
    "ZILEAN_ENABLED",
    "CATCHUP_ENABLED",
    "CATBOX_LAZY_ADD",
    "CATBOX_PRELOAD",
    "AUTO_UPGRADE_ENABLED",
    "SEASON_PACK_CONSOLIDATION_ENABLED",
    "NOTIFY_ON_SUCCESS",
    "NOTIFY_ON_FAILURE",
    "MULTI_DEBRID_ENABLED",
    "WEBDAV_ENABLED",
    "AUTH_ENABLED",
    # Without this the UI toggle stores the string "false", which is truthy,
    # so switching OIDC off would leave it on.
    "OIDC_ENABLED",
    "TRUSTED_PROXY_AUTH",
    "LITE_MODE",
    "DEBRIDIO_ENABLED",
    "ARR_SYNC_ENABLED",
    "ARR_SYNC_PURGE_ENABLED",
    "DISK_SYNC_ENABLED",
    "ARR_STUBS_ENABLED",
    "FILTER_RULES_MIGRATED",
    "SEERR_REPORT_STATUS",
}
_LIST_KEYS = {
    "MAX_SIZE_GB_BY_RESOLUTION",
    "QUALITY_PREFERENCE",
    "AUDIO_LANGUAGE_PREFERENCE",
    "EXCLUDE_LANGUAGES",
    "OPENSUBTITLES_LANGUAGES",
    "SORT_ORDER",
}
_RULE_PREFIX_BY_CATEGORY = {
    "resolution": "RESOLUTION",
    "source": "SOURCE",
    "encode": "ENCODE",
    "visual_tag": "VISUAL_TAG",
    "audio_tag": "AUDIO_TAG",
    "audio_channels": "AUDIO_CHANNELS",
    "language": "LANGUAGE",
}
_RULE_STATES = ("PREFERRED", "EXCLUDED", "REQUIRED", "INCLUDED")

# key -> category, used by set() to validate each value against that
# category's vocabulary, the same way _LANGUAGE_LIST_KEYS works.
_RULE_LIST_KEYS: dict[str, str] = {
    f"{prefix}_{state}": category
    for category, prefix in _RULE_PREFIX_BY_CATEGORY.items()
    for state in _RULE_STATES
}
_RULE_STRICT_KEYS = {f"{p}_STRICT" for p in _RULE_PREFIX_BY_CATEGORY.values()}

# Not set(_RULE_LIST_KEYS): `set` is shadowed by this module's own set()
# function below. It works at first import, since this line runs before that
# name is bound, but importlib.reload(settings) rebinds `set` to the builtin
# for the duration of the reload and then re-executes this line against the
# module-level def, raising TypeError. {*_RULE_LIST_KEYS} sidesteps the name
# entirely.
_LIST_KEYS |= {*_RULE_LIST_KEYS}
_BOOL_KEYS |= _RULE_STRICT_KEYS

# List keys whose values must each be a code detect_languages() can actually
# produce (streams.LANGUAGE_CODES). Checked in set() below, the same way
# _ENUM_KEYS is checked, so a typo like AUDIO_LANGUAGE_PREFERENCE=english
# fails loudly instead of silently becoming a preference that never matches.
_LANGUAGE_LIST_KEYS = {
    "AUDIO_LANGUAGE_PREFERENCE",
    "EXCLUDE_LANGUAGES",
}
_FLOAT_KEYS = {
    "AUTO_ADD_MIN_RATING",
}
# Keys with a fixed set of valid values  -  rendered as a <select> in the UI
# instead of free text, so a typo can't silently produce an invalid setting.
_ENUM_KEYS: dict[str, list[str]] = {
    "ZILEAN_MODE": ["external", "native"],
}
_INT_KEYS = {
    "ZILEAN_PG_PORT",
    "MIN_SEEDERS",
    "MAX_SIZE_GB",
    "WEB_PLAYER_MAX_SIZE_GB",
    "CATBOX_IDLE_MINUTES",
    "CATBOX_GC_INTERVAL_MINUTES",
    "TORBOX_POLL_INTERVAL_SEC",
    "TORBOX_POLL_TIMEOUT_SEC",
    "JELLYFIN_REFRESH_DELAY_SEC",
    "MERGE_VERSIONS_INTERVAL_HOURS",
    "CLEANUP_INTERVAL_HOURS",
    "STRM_GENERATOR_INTERVAL_HOURS",
    "MONITOR_INTERVAL_HOURS",
    "MOVIE_SYNC_INTERVAL_MINUTES",
    "MAX_RETRY_ATTEMPTS",
    "BACKUP_INTERVAL_HOURS",
    "BLACKLIST_FAIL_THRESHOLD",
    "TRENDING_PRECACHE_COUNT",
    "TRENDING_CHECK_INTERVAL_HOURS",
    "TRENDING_TV_COUNT",
    "POPULAR_MOVIE_COUNT",
    "POPULAR_TV_COUNT",
    "NETFLIX_NL_TOP_COUNT",
    "PRIME_NL_TOP_COUNT",
    "DISNEY_NL_TOP_COUNT",
    "AUTO_ADD_MIN_VOTES",
    "AUTO_UPGRADE_INTERVAL_HOURS",
    "SEASON_PACK_CHECK_INTERVAL_HOURS",
    "RETRY_QUEUE_INTERVAL_MINUTES",
    "HEALTH_CACHE_SECONDS",
    "CONTINUE_WATCHING_INTERVAL_MINUTES",
    "CATCHUP_DELAY_SEC",
    "CATCHUP_TAKE",
    "TRAKT_AUTO_REQUEST_CAP",
    "MDBLIST_AUTO_REQUEST_CAP",
    "AUTO_APPROVE_DAILY_LIMIT",
    "AUTO_APPROVE_ACTOR_DAILY_LIMIT",
    "AUTO_APPROVE_INTERVAL_HOURS",
    "DEBRIDIO_MAX_RESULTS",
    "SEERR_DECLINE_WANTED_AFTER_DAYS",
    "ARR_SYNC_INTERVAL_MINUTES", "DISK_SYNC_INTERVAL_MINUTES",
}

# Keys that take effect on the next access (no restart).
HOT_RELOAD = {
    "TORBOX_API_KEY",
    "TORBOX_BASE_URL",
    "JELLYFIN_URL",
    "JELLYFIN_API_KEY",
    "JELLYFIN_MEDIA_PATH",
    "SEERR_URL",
    "SEERR_API_KEY",
    "SEERR_REPORT_STATUS",
    "SEERR_DECLINE_WANTED_AFTER_DAYS",
    "TMDB_API_KEY",
    "ZILEAN_URL",
    "ZILEAN_ENABLED",
    "ZILEAN_MODE",
    "ZILEAN_PG_HOST", "ZILEAN_PG_PORT", "ZILEAN_PG_DB", "ZILEAN_PG_USER", "ZILEAN_PG_PASSWORD",
    # CATBOX_MODE is not here: the schedulers gate on it at boot, so a flip needs a restart.
    "CATBOX_LAZY_ADD",
    "CATBOX_IDLE_MINUTES",
    "QUALITY_PREFERENCE",
    "ALLOW_4K",
    "EXCLUDE_REMUX",
    "EXCLUDE_BLURAY",
    "EXCLUDE_CAM",
    "STRICT_NO_CAM",
    "EXCLUDE_UNDERSIZED_RELEASES",
    "EXCLUDE_UNDERSIZED_STRICT",
    "PREFER_WEBDL",
    "PREFER_HEVC",
    "MIN_SEEDERS",
    "MAX_SIZE_GB",
    "MAX_SIZE_GB_BY_RESOLUTION",
    "PREFER_SMALLER_FILES",
    "AUDIO_LANGUAGE_PREFERENCE",
    "EXCLUDE_LANGUAGES",
    "SORT_ORDER",
    "OPENSUBTITLES_LANGUAGES",
    "OPENSUBTITLES_API_KEY",
    "OPENSUBTITLES_USER_AGENT",
    "BLACKLIST_FAIL_THRESHOLD",
    "WEB_PLAYER_MAX_SIZE_GB",
    "NOTIFY_ON_SUCCESS",
    "NOTIFY_ON_FAILURE",
    "DISCORD_WEBHOOK_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "AUTO_UPGRADE_ENABLED",
    "SEASON_PACK_CONSOLIDATION_ENABLED",
    # WEBDAV_ENABLED is not here: the WebDAV server is gated on it at boot, so a flip needs a restart.
    "MULTI_DEBRID_ENABLED",
    "REALDEBRID_API_KEY",
    "AUTH_ENABLED",
    "AUTH_USERNAME",
    "AUTH_PASSWORD",
    "AUTH_PASSWORD_HASH",
    "TRUSTED_PROXY_AUTH",
    "TRUSTED_PROXY_USER_HEADER",
    "TRUSTED_PROXY_NETWORKS",
    "TRENDING_TV_COUNT", "POPULAR_MOVIE_COUNT", "POPULAR_TV_COUNT",
    "NETFLIX_NL_TOP_COUNT", "PRIME_NL_TOP_COUNT", "DISNEY_NL_TOP_COUNT",
    "AUTO_ADD_MIN_RATING", "AUTO_ADD_MIN_VOTES", "AUTO_ADD_REGION",
    "AUTO_APPROVE_DAILY_LIMIT", "AUTO_APPROVE_ACTOR_DAILY_LIMIT", "AUTO_APPROVE_GENRE_RULES",
    "DISCOVER_GENRE_TABS",
    "RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY",
    "ARR_SYNC_ENABLED", "ARR_SYNC_PURGE_ENABLED", "RADARR_ROOT_FOLDER", "SONARR_ROOT_FOLDER",
    "RADARR_QUALITY_PROFILE", "SONARR_QUALITY_PROFILE",
    "ARR_STUBS_ENABLED", "ARR_STUB_PATH", "DISK_SYNC_ENABLED",
    "TRAKT_CLIENT_ID", "TRAKT_CLIENT_SECRET", "TRAKT_AUTO_REQUEST_CAP",
    "MDBLIST_AUTO_REQUEST_CAP",
    "DEBRIDIO_ENABLED", "DEBRIDIO_API_KEY", "DEBRIDIO_BASE_URL",
    "DEBRIDIO_MAX_RESULTS", "DEBRIDIO_CONFIG_TOKEN",
}

# The 35 rule keys from Task 4 (_RULE_LIST_KEYS' 28 + _RULE_STRICT_KEYS' 7)
# are hot-reloadable: filter_rules.load_rules() reads every one of them live
# on every rank_streams call, the same as EXCLUDE_UNDERSIZED_STRICT and
# SORT_ORDER above. Only EXCLUDE_UNDERSIZED_STRICT and SORT_ORDER were added
# when those two shipped; the 35 were never added, which left the admin UI
# telling users to restart after every filter edit when nothing needed one.
HOT_RELOAD |= {*_RULE_LIST_KEYS} | _RULE_STRICT_KEYS

# Region list for AUTO_ADD_REGION. Mirrors frontend/src/components/shell/RegionPicker.tsx.
_REGIONS = [
    ("NL", "Netherlands"), ("BE", "Belgium"), ("ZA", "South Africa"), ("US", "United States"),
    ("GB", "United Kingdom"), ("DE", "Germany"), ("FR", "France"), ("ES", "Spain"),
    ("IT", "Italy"), ("AU", "Australia"), ("CA", "Canada"), ("BR", "Brazil"), ("IN", "India"),
    ("JP", "Japan"), ("KR", "South Korea"), ("SE", "Sweden"), ("NO", "Norway"),
    ("DK", "Denmark"), ("PT", "Portugal"), ("PL", "Poland"),
]

# Option resolvers: a field whose options come from a vocabulary defined
# elsewhere names the resolver instead of listing values.
_OPTION_RESOLVERS = {
    "languages": lambda: [{"value": c, "label": c} for c in _streams.LANGUAGE_CODES],
    "sort_criteria": lambda: [{"value": c, "label": c.replace("_", " ")} for c in _streams.SORT_CRITERIA],
    "regions": lambda: [{"value": c, "label": n} for c, n in _REGIONS],
    "zilean_mode": lambda: [{"value": "external", "label": "External service"},
                            {"value": "native", "label": "Native index"}],
}


def _f(key, label, help, kind=None, *, options=None, placeholder=None, unit=None,
       min=None, max=None, advanced=False, depends_on=None, test=None, picker=None,
       component=None, readonly=False):
    """One field declaration. kind defaults from the type buckets; pass it
    only to refine (url, path, secret, select, multiselect, ordered) or for
    a custom card."""
    if kind is None:
        kind = ("bool" if key in _BOOL_KEYS else "int" if key in _INT_KEYS
                else "float" if key in _FLOAT_KEYS else "list" if key in _LIST_KEYS
                else "select" if key in _ENUM_KEYS else "str")
    return {"key": key, "label": label, "help": help, "kind": kind, "options": options,
            "placeholder": placeholder, "unit": unit, "min": min, "max": max,
            "advanced": advanced, "depends_on": depends_on, "test": test, "picker": picker,
            "component": component, "readonly": readonly}


def _custom(component, label=""):
    return _f(f"__{component}", label, "", "custom", component=component)


SECTIONS = [
    {
        "id": "mode", "title": "Mode", "icon": "⚙",
        "description": "How this Mycelium runs: full or lite, and whether titles are fetched on demand.",
        "fields": [
            _f("LITE_MODE", "Lite mode",
               "Run only the webhook, the processor and this admin: no Discover, no schedulers, no plugins. For Seerr and Jellyfin-only setups. Restart after changing."),
            _f("CATBOX_MODE", "Catbox mode",
               "Add a torrent to TorBox only when someone presses play, and drop it again after idling. Needed for the on-demand library and the arr stub files. Restart after changing."),
            _f("CATBOX_HOST", "Public URL", "Address Jellyfin and other players can reach Mycelium on, used inside every .strm file.",
               "url", placeholder="https://mycelium.example.com", depends_on="CATBOX_MODE"),
            _f("CATBOX_LAZY_ADD", "Lazy add",
               "Skip the TorBox add at request time and do it on first play only. Saves TorBox adds, costs a longer first start.",
               depends_on="CATBOX_MODE"),
            _f("CATBOX_PRELOAD", "Preload on request",
               "Add the torrent to TorBox as soon as a request succeeds so the first play starts fast. Each request spends one of the 60 hourly adds.",
               depends_on="CATBOX_MODE"),
            _f("CATBOX_IDLE_MINUTES", "Idle minutes before release",
               "How long a title may sit unplayed before its torrent is removed from TorBox again. 1440 is one day.",
               unit="minutes", min=5, advanced=True, depends_on="CATBOX_MODE"),
            _f("CATBOX_GC_INTERVAL_MINUTES", "Idle check interval", "How often idle titles are looked for. Restart after changing.",
               unit="minutes", min=1, advanced=True, depends_on="CATBOX_MODE"),
            _f("DISK_SYNC_ENABLED", "Purge titles deleted on disk",
               "Once an hour, a title whose .strm files are gone (a Jellyfin delete) is removed from Mycelium too. Off keeps the files coming back.",
               depends_on="CATBOX_MODE"),
            _f("WEBDAV_ENABLED", "WebDAV share", "Serve the library over WebDAV as well. Restart after changing.", advanced=True),
        ],
    },
    {
        "id": "debrid", "title": "Debrid", "icon": "☁",
        "description": "TorBox is where torrents are cached and streamed from. RealDebrid can stand in when a release is only cached there.",
        "fields": [
            _f("TORBOX_API_KEY", "TorBox API key", "From TorBox, Settings, API. Required for everything.", "secret", test="torbox"),
            _f("TORBOX_BASE_URL", "TorBox API URL", "Leave the default unless TorBox publishes a new API address.",
               "url", placeholder="https://api.torbox.app/v1/api", advanced=True, test="torbox"),
            _f("TORBOX_POLL_INTERVAL_SEC", "Poll interval", "Seconds between checks while waiting for TorBox to finish caching a torrent.",
               unit="seconds", min=1, advanced=True),
            _f("TORBOX_POLL_TIMEOUT_SEC", "Poll timeout", "Give up waiting for TorBox after this many seconds and report the title as failed for now.",
               unit="seconds", min=30, advanced=True),
            _f("MULTI_DEBRID_ENABLED", "RealDebrid fallback", "Try RealDebrid when a release is not cached on TorBox."),
            _f("REALDEBRID_API_KEY", "RealDebrid API key", "From real-debrid.com, My account, API token.",
               "secret", depends_on="MULTI_DEBRID_ENABLED", test="realdebrid"),
        ],
    },
    {
        "id": "scrapers", "title": "Scrapers and metadata", "icon": "\U0001F50D",
        "description": "Where releases are searched for, and where titles, posters and runtimes come from.",
        "fields": [
            _f("TMDB_API_KEY", "TMDB API key", "A free key from themoviedb.org. Powers Discover, posters and the runtime in stub files.",
               "secret", test="tmdb"),
            _f("ZILEAN_ENABLED", "Use Zilean", "Search a Zilean DMM index next to Torrentio for cached releases."),
            _f("ZILEAN_MODE", "Zilean mode", "External talks to a running Zilean service. Native imports its Postgres into a built-in index.",
               options="zilean_mode", depends_on="ZILEAN_ENABLED"),
            _f("ZILEAN_URL", "Zilean URL", "Address of the Zilean service.", "url",
               placeholder="http://zilean:8181", depends_on="ZILEAN_MODE=external", test="zilean"),
            _f("ZILEAN_PG_HOST", "Postgres host", "Host name of Zilean's Postgres database.", placeholder="zilean-postgres",
               depends_on="ZILEAN_MODE=native", test="zilean_pg"),
            _f("ZILEAN_PG_PORT", "Postgres port", "Usually 5432.", min=1, max=65535, depends_on="ZILEAN_MODE=native", test="zilean_pg"),
            _f("ZILEAN_PG_DB", "Postgres database", "Database name, usually zilean.", depends_on="ZILEAN_MODE=native", test="zilean_pg"),
            _f("ZILEAN_PG_USER", "Postgres user", "Database user with read access.", depends_on="ZILEAN_MODE=native", test="zilean_pg"),
            _f("ZILEAN_PG_PASSWORD", "Postgres password", "Password for that user.", "secret",
               depends_on="ZILEAN_MODE=native", test="zilean_pg"),
            _f("DEBRIDIO_ENABLED", "Use Debridio", "Search the Debridio addon as well. Needs its own API key."),
            _f("DEBRIDIO_API_KEY", "Debridio API key", "From your Debridio account.", "secret",
               depends_on="DEBRIDIO_ENABLED", test="debridio"),
            _f("DEBRIDIO_BASE_URL", "Debridio URL", "Leave the default unless you host the addon yourself.", "url",
               placeholder="https://addon.debridio.com", advanced=True, depends_on="DEBRIDIO_ENABLED", test="debridio"),
            _f("DEBRIDIO_MAX_RESULTS", "Debridio result limit", "Most results to take from one Debridio search.",
               min=1, max=500, advanced=True, depends_on="DEBRIDIO_ENABLED"),
            _f("DEBRIDIO_CONFIG_TOKEN", "Debridio config token", "Only if you built a config token in the addon yourself; blank lets Mycelium build one.",
               "secret", advanced=True, depends_on="DEBRIDIO_ENABLED"),
        ],
    },
    {
        "id": "jellyfin", "title": "Jellyfin", "icon": "\U0001F3AC",
        "description": "The media server that plays the library. Mycelium tells it what changed.",
        "fields": [
            _f("JELLYFIN_URL", "Jellyfin URL", "Address Mycelium can reach Jellyfin on, from inside Docker if both run there.",
               "url", placeholder="http://jellyfin:8096", test="jellyfin"),
            _f("JELLYFIN_API_KEY", "Jellyfin API key", "Dashboard, API Keys. Lets Mycelium trigger library refreshes.",
               "secret", test="jellyfin"),
            _f("JELLYFIN_MEDIA_PATH", "Media path as Jellyfin sees it",
               "Only when Jellyfin mounts the media folder at a different path than Mycelium does. Blank means the same path.",
               "path", placeholder="/media"),
            _f("JELLYFIN_REFRESH_DELAY_SEC", "Refresh delay", "Seconds to wait after writing files before asking Jellyfin to look.",
               unit="seconds", min=0, advanced=True),
        ],
    },
    {
        "id": "seerr", "title": "Seerr", "icon": "\U0001F4EC",
        "description": "Requests arrive from Seerr through a webhook; outcomes are reported back.",
        "fields": [
            _f("SEERR_URL", "Seerr URL", "Address of Seerr, Overseerr or Jellyseerr.", "url",
               placeholder="http://seerr:5055", test="seerr"),
            _f("SEERR_API_KEY", "Seerr API key", "Settings, General, API key in Seerr.", "secret", test="seerr"),
            _f("SEERR_REPORT_STATUS", "Report outcomes to Seerr",
               "Mark a request available when its files exist, declined when it finally failed, and remove its media entry when purged."),
            _f("SEERR_DECLINE_WANTED_AFTER_DAYS", "Decline wanted after",
               "Days a released title may stay without a release before Seerr is told it was declined. 0 never declines.",
               unit="days", min=0),
            _custom("WebhookSecret", "Webhook secret"),
        ],
    },
    {
        "id": "arrs", "title": "Radarr / Sonarr", "icon": "\U0001F4E1",
        "description": "Mirror the library into Radarr and Sonarr so Seerr, Maintainerr and calendars see it. The arrs never download anything.",
        "fields": [
            _f("ARR_SYNC_ENABLED", "Mirror the library", "Create every title in the arr as a monitored entry with search off, and remove it on purge."),
            _f("RADARR_URL", "Radarr URL", "Address Mycelium can reach Radarr on.", "url",
               placeholder="http://radarr:7878", depends_on="ARR_SYNC_ENABLED", test="radarr"),
            _f("RADARR_API_KEY", "Radarr API key", "Settings, General, API Key in Radarr.", "secret",
               depends_on="ARR_SYNC_ENABLED", test="radarr"),
            _f("RADARR_ROOT_FOLDER", "Radarr root folder", "Where mirrored movies are filed in Radarr. Blank uses its first root folder.",
               "path", depends_on="ARR_SYNC_ENABLED", picker="radarr_root_folders"),
            _f("RADARR_QUALITY_PROFILE", "Radarr quality profile", "Profile new entries get. Blank uses the first profile.",
               depends_on="ARR_SYNC_ENABLED", picker="radarr_quality_profiles"),
            _f("SONARR_URL", "Sonarr URL", "Address Mycelium can reach Sonarr on.", "url",
               placeholder="http://sonarr:8989", depends_on="ARR_SYNC_ENABLED", test="sonarr"),
            _f("SONARR_API_KEY", "Sonarr API key", "Settings, General, API Key in Sonarr.", "secret",
               depends_on="ARR_SYNC_ENABLED", test="sonarr"),
            _f("SONARR_ROOT_FOLDER", "Sonarr root folder", "Where mirrored series are filed in Sonarr. Blank uses its first root folder.",
               "path", depends_on="ARR_SYNC_ENABLED", picker="sonarr_root_folders"),
            _f("SONARR_QUALITY_PROFILE", "Sonarr quality profile", "Profile new entries get. Blank uses the first profile.",
               depends_on="ARR_SYNC_ENABLED", picker="sonarr_quality_profiles"),
            _f("ARR_STUBS_ENABLED", "Write stub files for the arrs",
               "Put a tiny MKV per title in a folder the arrs mount as their root, so titles show as present instead of missing. Needs Catbox mode.",
               depends_on="ARR_SYNC_ENABLED"),
            _f("ARR_STUB_PATH", "Stub folder", "Folder inside this container where the stubs are written; mount it in Radarr and Sonarr as their root folders.",
               "path", placeholder="/arr-stubs", depends_on="ARR_STUBS_ENABLED"),
            _f("ARR_SYNC_PURGE_ENABLED", "Purge titles deleted in the arr",
               "Once an hour, a mirrored title the arr no longer holds is removed from Mycelium. Off re-adds it to the arr instead.",
               depends_on="ARR_SYNC_ENABLED"),
        ],
    },
    {
        "id": "quality", "title": "Quality", "icon": "⭐",
        "description": "Size and seeder floors and the sort order. Which resolutions, sources and languages win lives in the Filter rules tab.",
        "fields": [
            _f("MIN_SEEDERS", "Minimum seeders", "Releases with fewer seeders are ignored. 3 is a safe floor for cached content.", min=0),
            _f("MAX_SIZE_GB", "Maximum size", "Largest release to accept, in GB. 0 means no limit.", unit="GB", min=0),
            _f("MAX_SIZE_GB_BY_RESOLUTION", "Size cap per resolution",
               "Caps per resolution as resolution:GB pairs, for example 2160p:40,1080p:12. Blank uses the single maximum above.",
               placeholder="2160p:40,1080p:12"),
            _f("PREFER_SMALLER_FILES", "Prefer smaller files", "When two releases tie, take the smaller one."),
            _f("EXCLUDE_UNDERSIZED_RELEASES", "Skip undersized releases",
               "Drop releases far smaller than expected for their resolution; they are usually re-encodes or fakes."),
            _f("EXCLUDE_UNDERSIZED_STRICT", "Undersized rule is strict",
               "Keep dropping undersized releases even when nothing else is left. Off relaxes the rule rather than return nothing.",
               advanced=True),
            _f("WEB_PLAYER_MAX_SIZE_GB", "Web player size limit", "Largest release the built-in web player will pick, in GB.", unit="GB", min=0),
            _f("SORT_ORDER", "Sort order", "Which properties decide between surviving releases, most important first.",
               "ordered", options="sort_criteria"),
            _f("BLACKLIST_FAIL_THRESHOLD", "Blacklist after failures", "A release that fails this many times is never tried again.",
               min=1, advanced=True),
            _custom("FilterRulesLink", "Filter rules"),
        ],
    },
    {
        "id": "subtitles", "title": "Subtitles", "icon": "\U0001F4AC",
        "description": "Subtitle download from OpenSubtitles.",
        "fields": [
            _f("OPENSUBTITLES_API_KEY", "OpenSubtitles API key", "From opensubtitles.com, API consumers.", "secret", test="opensubtitles"),
            _f("OPENSUBTITLES_LANGUAGES", "Subtitle languages", "Languages to fetch subtitles for.", "multiselect", options="languages"),
            _f("OPENSUBTITLES_USER_AGENT", "User agent", "Sent with every OpenSubtitles request; they ask for an app name and version.",
               advanced=True),
        ],
    },
    {
        "id": "automation", "title": "Automation", "icon": "\U0001F916",
        "description": "Background jobs that improve and repair the library on their own.",
        "fields": [
            _f("AUTO_UPGRADE_ENABLED", "Auto-upgrade quality", "Replace a title when a better release matching your rules appears."),
            _f("AUTO_UPGRADE_INTERVAL_HOURS", "Upgrade check interval", "How often to look for upgrades.",
               unit="hours", min=1, advanced=True, depends_on="AUTO_UPGRADE_ENABLED"),
            _f("SEASON_PACK_CONSOLIDATION_ENABLED", "Consolidate season packs",
               "Replace single episodes with a season pack once one is cached, so a season is one torrent."),
            _f("SEASON_PACK_CHECK_INTERVAL_HOURS", "Season pack check interval", "How often to look for packs.",
               unit="hours", min=1, advanced=True, depends_on="SEASON_PACK_CONSOLIDATION_ENABLED"),
            _f("CATCHUP_ENABLED", "Catch up missed requests", "After a restart, re-run requests that were interrupted.", advanced=True),
            _f("CATCHUP_DELAY_SEC", "Catch-up delay", "Seconds after boot before catch-up starts.", unit="seconds", min=0,
               advanced=True, depends_on="CATCHUP_ENABLED"),
            _f("CATCHUP_TAKE", "Catch-up batch", "Most requests to re-run in one catch-up.", min=1, advanced=True, depends_on="CATCHUP_ENABLED"),
            _f("MAX_RETRY_ATTEMPTS", "Retry attempts", "Times a failed request is retried before it is declined for good.", min=0, advanced=True),
            _custom("GenreTabs", "Discover genre tabs"),
        ],
    },
    {
        "id": "auto_add", "title": "Auto-add", "icon": "➕",
        "description": "Request popular titles without anyone asking. Each one spends a TorBox add.",
        "fields": [
            _f("TRENDING_PRECACHE_COUNT", "Trending movies", "How many trending movies to add each run. 0 is off.", min=0),
            _f("TRENDING_TV_COUNT", "Trending series", "How many trending series to add each run. 0 is off.", min=0),
            _f("POPULAR_MOVIE_COUNT", "Popular movies", "How many popular movies to add each run. 0 is off.", min=0),
            _f("POPULAR_TV_COUNT", "Popular series", "How many popular series to add each run. 0 is off.", min=0),
            _f("NETFLIX_NL_TOP_COUNT", "Netflix top list", "How many from the Netflix top list for your region. 0 is off.", min=0),
            _f("PRIME_NL_TOP_COUNT", "Prime Video top list", "How many from the Prime Video top list. 0 is off.", min=0),
            _f("DISNEY_NL_TOP_COUNT", "Disney+ top list", "How many from the Disney+ top list. 0 is off.", min=0),
            _f("AUTO_ADD_MIN_RATING", "Minimum rating", "Skip titles rated below this on TMDB.", min=0, max=10),
            _f("AUTO_ADD_MIN_VOTES", "Minimum votes", "Skip titles with fewer TMDB votes, which filters out obscure entries.", min=0),
            _f("AUTO_ADD_REGION", "Region", "Country the streaming top lists are taken for.", "select", options="regions"),
            _f("TRENDING_CHECK_INTERVAL_HOURS", "Auto-add interval", "How often auto-add runs.", unit="hours", min=1, advanced=True),
            _custom("AutoAddNow", "Run now"),
        ],
    },
    {
        "id": "auto_approve", "title": "Auto-approve and imports", "icon": "✅",
        "description": "Limits for requests Mycelium approves on its own, and the Trakt and MDBList imports.",
        "fields": [
            _f("AUTO_APPROVE_DAILY_LIMIT", "Genre rule daily limit", "Most titles the genre rules may approve per day.", min=0),
            _f("AUTO_APPROVE_ACTOR_DAILY_LIMIT", "Favourite actor daily limit", "Most titles the favourite-actor rule may approve per day.", min=0),
            _f("TRAKT_CLIENT_ID", "Trakt client id", "From trakt.tv, Settings, Your API apps.", test="trakt"),
            _f("TRAKT_CLIENT_SECRET", "Trakt client secret", "The secret of that API app.", "secret"),
            _f("TRAKT_AUTO_REQUEST_CAP", "Trakt import cap", "Most titles a Trakt watchlist sync may request per run.", min=0),
            _f("MDBLIST_AUTO_REQUEST_CAP", "MDBList import cap", "Most titles an MDBList sync may request per run.", min=0),
        ],
    },
    {
        "id": "security", "title": "Security", "icon": "\U0001F512",
        "description": "Who can log in and how.",
        "fields": [
            _f("AUTH_ENABLED", "Require login", "Ask for a login on every page. Off is only safe behind another login."),
            _f("AUTH_USERNAME", "Admin username", "Username for the built-in admin login."),
            _f("TRUSTED_PROXY_AUTH", "Trust a proxy header", "Accept the user name from a header set by a reverse proxy such as Authelia."),
            _f("TRUSTED_PROXY_USER_HEADER", "Proxy user header", "Header carrying the user name.", placeholder="X-Forwarded-User",
               advanced=True, depends_on="TRUSTED_PROXY_AUTH"),
            _f("TRUSTED_PROXY_NETWORKS", "Trusted networks", "Only requests from these networks (CIDR, comma separated) may carry that header.",
               placeholder="127.0.0.1/32,10.0.0.0/8", advanced=True, depends_on="TRUSTED_PROXY_AUTH"),
            _f("OIDC_ENABLED", "Single sign-on (OIDC)", "Log in through an OpenID Connect provider such as Authentik or Keycloak. Restart after changing."),
            _f("OIDC_PROVIDER_NAME", "Provider name", "Shown on the login button.", placeholder="SSO", depends_on="OIDC_ENABLED"),
            _f("OIDC_ISSUER_URL", "Issuer URL", "The provider's issuer; its discovery document lives at /.well-known/openid-configuration below it.",
               "url", placeholder="https://auth.example.com/application/o/mycelium/", depends_on="OIDC_ENABLED", test="oidc"),
            _f("OIDC_CLIENT_ID", "Client id", "Client id registered for Mycelium at the provider.", depends_on="OIDC_ENABLED", test="oidc"),
            _f("OIDC_CLIENT_SECRET", "Client secret", "Client secret from the provider.", "secret", depends_on="OIDC_ENABLED"),
            _f("OIDC_SCOPES", "Scopes", "Scopes to request. The default covers a user name and email.",
               placeholder="openid email profile", advanced=True, depends_on="OIDC_ENABLED"),
            _f("OIDC_USER_CLAIM", "User name claim", "Which claim becomes the Mycelium user name.",
               placeholder="preferred_username", advanced=True, depends_on="OIDC_ENABLED"),
            _custom("LegacyPassword", "Legacy password"),
        ],
    },
    {
        "id": "notifications", "title": "Notifications", "icon": "\U0001F514",
        "description": "Where to hear about finished and failed requests.",
        "fields": [
            _f("NOTIFY_ON_SUCCESS", "Notify on success", "Send a message when a request lands."),
            _f("NOTIFY_ON_FAILURE", "Notify on failure", "Send a message when a request fails for good."),
            _f("DISCORD_WEBHOOK_URL", "Discord webhook URL", "A webhook from a Discord channel's integrations page. Treated as a secret.",
               "secret", test="discord"),
            _f("TELEGRAM_BOT_TOKEN", "Telegram bot token", "Token from BotFather.", "secret", test="telegram"),
            _f("TELEGRAM_CHAT_ID", "Telegram chat id", "The chat or channel the bot posts to.", test="telegram"),
        ],
    },
    {
        "id": "intervals", "title": "Intervals", "icon": "⏱",
        "description": "How often each background job runs. Restart after changing any of these.",
        "fields": [
            _f("STRM_GENERATOR_INTERVAL_HOURS", "Library repair", "Regenerates missing or expired .strm files.", unit="hours", min=1, advanced=True),
            _f("CLEANUP_INTERVAL_HOURS", "Cleanup", "Removes dead and duplicate files.", unit="hours", min=1, advanced=True),
            _f("MONITOR_INTERVAL_HOURS", "Series monitor", "Looks for new episodes of monitored series.", unit="hours", min=1, advanced=True),
            _f("MOVIE_SYNC_INTERVAL_MINUTES", "Wanted movies", "Retries movies that were released but had no release yet.", unit="minutes", min=1, advanced=True),
            _f("MERGE_VERSIONS_INTERVAL_HOURS", "Merge versions", "Folds duplicate versions of a title together.", unit="hours", min=1, advanced=True),
            _f("BACKUP_INTERVAL_HOURS", "Database backup", "Copies the database to the backups folder.", unit="hours", min=1, advanced=True),
            _f("RETRY_QUEUE_INTERVAL_MINUTES", "Retry queue", "Retries requests that hit a temporary error.", unit="minutes", min=1, advanced=True),
            _f("CONTINUE_WATCHING_INTERVAL_MINUTES", "Continue watching", "Refreshes the continue-watching row from Jellyfin.", unit="minutes", min=1, advanced=True),
            _f("AUTO_APPROVE_INTERVAL_HOURS", "Auto-approve", "Runs the genre and favourite-actor rules.", unit="hours", min=1, advanced=True),
            _f("ARR_SYNC_INTERVAL_MINUTES", "Arr reconcile", "Adds what the arrs lack and purges what was deleted there. 0 disables it.", unit="minutes", min=0, advanced=True),
            _f("DISK_SYNC_INTERVAL_MINUTES", "On-disk deletion check", "Purges titles whose files were deleted. 0 disables it.", unit="minutes", min=0, advanced=True),
            _f("HEALTH_CACHE_SECONDS", "Health cache", "How long the Overview health rows are cached.", unit="seconds", min=5, advanced=True),
        ],
    },
]

# Typed keys that have no field on purpose: retired filter booleans (the
# rules editor replaced them, see migrate_filters.RETIRED) and internal
# markers nobody should edit by hand.
_UNLISTED_KEYS = {
    "ALLOW_4K", "EXCLUDE_REMUX", "EXCLUDE_BLURAY", "EXCLUDE_CAM", "STRICT_NO_CAM",
    "PREFER_WEBDL", "PREFER_HEVC", "QUALITY_PREFERENCE",
    "AUDIO_LANGUAGE_PREFERENCE", "EXCLUDE_LANGUAGES",
    "FILTER_RULES_MIGRATED",
}


def fields_by_key() -> dict[str, dict]:
    return {f["key"]: f for s in SECTIONS for f in s["fields"]}


# The pre-schema groups payload. FilterRules.tsx and app.py's wizard save
# read this shape, so it is derived here rather than removed.
SETTING_GROUPS = [
    {"id": s["id"], "title": s["title"], "keys": [f["key"] for f in s["fields"] if f["kind"] != "custom"]}
    for s in SECTIONS
] + [{
    "id": "filter_rules",
    "title": "Filtering rules",
    "keys": [k for k in _RULE_LIST_KEYS] + sorted(_RULE_STRICT_KEYS),
}]


def _coerce(key: str, raw: str | None):
    if raw is None:
        return None
    if key in _BOOL_KEYS:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if key in _LIST_KEYS:
        return [v.strip() for v in raw.split(",") if v.strip()]
    if key in _INT_KEYS:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    if key in _FLOAT_KEYS:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    if key in _ENUM_KEYS:
        return raw if raw in _ENUM_KEYS[key] else None
    return raw


def get(key: str, default=None):
    try:
        raw = db.get_setting(key)
    except Exception as exc:
        log.debug("settings.get: DB read failed for %s (%s); falling back to .env", key, exc)
        raw = None
    if raw is not None:
        coerced = _coerce(key, raw)
        if coerced is not None:
            return coerced
    if hasattr(_config, key):
        return getattr(_config, key)
    return default


def set(key: str, value) -> None:
    if value is None or value == "":
        db.set_setting(key, None)
        return
    if key in _ENUM_KEYS and str(value) not in _ENUM_KEYS[key]:
        raise ValueError(f"{key} must be one of {_ENUM_KEYS[key]}, got {value!r}")
    if key in _LANGUAGE_LIST_KEYS:
        codes = (
            value if isinstance(value, (list, tuple))
            else [v.strip() for v in str(value).split(",") if v.strip()]
        )
        unknown = sorted({c.lower() for c in codes if c.lower() not in _streams.LANGUAGE_CODES})
        if unknown:
            raise ValueError(
                f"{key} has unknown language code(s) {unknown}; valid codes "
                f"are {', '.join(_streams.LANGUAGE_CODES)}"
            )
    if key in _RULE_LIST_KEYS:
        category = _RULE_LIST_KEYS[key]
        vocabulary = _rt.values_for(category)
        values = [v.strip().lower() for v in
                  (value if isinstance(value, list) else str(value).split(","))
                  if str(v).strip()]
        unknown = [v for v in values if v not in vocabulary]
        if unknown:
            raise ValueError(
                f"{key} has value(s) not valid for {category}: {unknown}. "
                f"Valid values are {list(vocabulary)}"
            )
        value = values
    if key == "SORT_ORDER":
        names = [v.strip().lower() for v in
                 (value if isinstance(value, list) else str(value).split(","))
                 if str(v).strip()]
        unknown = [n for n in names if n not in _streams.SORT_CRITERIA]
        if unknown:
            raise ValueError(
                f"{key} has unknown criteria {unknown}. Valid names are "
                f"{list(_streams.SORT_CRITERIA)}"
            )
        value = names
    if isinstance(value, bool):
        stored = "true" if value else "false"
    elif isinstance(value, (list, tuple)):
        stored = ",".join(str(v) for v in value)
    else:
        stored = str(value)
    db.set_setting(key, stored)


def _warn_unknown_env_language_codes() -> None:
    """AUDIO_LANGUAGE_PREFERENCE/EXCLUDE_LANGUAGES set via .env bypass set()'s
    validation entirely - config.py just lowercase-splits on commas and
    accepts anything, since it cannot import streams (streams imports config,
    and a cycle back would break both). So check the .env-derived values once,
    here, at import time - and only warn, never raise: a bad .env value must
    not crash startup, it should just behave like "no preference" until fixed.
    """
    for key in _LANGUAGE_LIST_KEYS:
        codes = getattr(_config, key, None) or []
        unknown = sorted({c for c in codes if c not in _streams.LANGUAGE_CODES})
        if unknown:
            log.warning(
                "%s in .env has unknown language code(s) %s; valid codes are: %s",
                key, unknown, ", ".join(_streams.LANGUAGE_CODES),
            )


_warn_unknown_env_language_codes()


def _warn_unknown_env_rule_values() -> None:
    """RESOLUTION_PREFERRED and the other 27 rule-list keys set via .env
    bypass set()'s vocabulary validation entirely, the same as
    AUDIO_LANGUAGE_PREFERENCE always has - config.py just lowercase-splits on
    commas and accepts anything, since it cannot import release_tags (the
    reverse import already exists, and release_tags.values_for("language")
    imports streams, which imports config). So check the .env-derived values
    once, here, at import time - and only warn, never raise: a bad .env value
    must not crash startup, a migration must never brick boot over one either.
    """
    for key, category in _RULE_LIST_KEYS.items():
        values = getattr(_config, key, None) or []
        vocabulary = _rt.values_for(category)
        unknown = sorted({v for v in values if v not in vocabulary})
        if unknown:
            log.warning(
                "%s in .env has value(s) not valid for %s: %s. Valid values "
                "are %s", key, category, unknown, list(vocabulary),
            )


_warn_unknown_env_rule_values()


def all_for_ui() -> list[dict]:
    """Return groups with each key's current value + type for the UI."""
    overrides = db.get_all_settings()
    out = []
    for group in SETTING_GROUPS:
        items = []
        for key in group["keys"]:
            override_raw = overrides.get(key)
            current = get(key)
            kind = (
                "bool" if key in _BOOL_KEYS
                else "list" if key in _LIST_KEYS
                else "int" if key in _INT_KEYS
                else "float" if key in _FLOAT_KEYS
                else "enum" if key in _ENUM_KEYS
                else "str"
            )
            # options is None for a free-text key; a key with a fixed
            # vocabulary gets it listed here so the UI can render a <select>
            # or multi-select instead of free text that set() would reject.
            options = _ENUM_KEYS.get(key)
            if options is None and key in _RULE_LIST_KEYS:
                options = list(_rt.values_for(_RULE_LIST_KEYS[key]))
            elif options is None and key in _LANGUAGE_LIST_KEYS:
                options = list(_streams.LANGUAGE_CODES)
            elif options is None and key == "SORT_ORDER":
                options = list(_streams.SORT_CRITERIA)
            items.append({
                "key": key,
                "value": current,
                "kind": kind,
                "options": options,
                "overridden": override_raw is not None,
                "hot_reload": key in HOT_RELOAD,
            })
        out.append({"id": group["id"], "title": group["title"], "items": items})
    return out


def _resolve_options(field: dict) -> list[dict] | None:
    opts = field["options"]
    if opts is None:
        return None
    if isinstance(opts, str):
        return _OPTION_RESOLVERS[opts]()
    return [o if isinstance(o, dict) else {"value": o, "label": o} for o in opts]


def schema_for_ui() -> list[dict]:
    """SECTIONS with each field's current value, whether a DB override
    exists, whether it hot-reloads, and options resolved. A secret's value is
    reported as True/False (set or not), never the secret itself."""
    overrides = db.get_all_settings()
    out = []
    for section in SECTIONS:
        fields = []
        for f in section["fields"]:
            item = dict(f)
            item["options"] = _resolve_options(f)
            if f["kind"] == "custom":
                item.update({"value": None, "overridden": False, "hot_reload": True})
            else:
                current = get(f["key"])
                item["value"] = bool(current) if f["kind"] == "secret" else current
                item["overridden"] = overrides.get(f["key"]) is not None
                item["hot_reload"] = f["key"] in HOT_RELOAD
            fields.append(item)
        out.append({"id": section["id"], "title": section["title"], "description": section["description"],
                    "icon": section["icon"], "fields": fields})
    return out
