import os, sys
os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import migrate_filters


@pytest.fixture
def store(monkeypatch):
    written = {}
    import settings as _s
    monkeypatch.setattr(_s, "set", lambda k, v: written.__setitem__(k, v))
    return written


def _old(monkeypatch, **values):
    import settings as _s
    monkeypatch.setattr(_s, "get", lambda k, d=None: values.get(k, d))


def test_quality_preference_becomes_resolution_preferred(monkeypatch, store):
    _old(monkeypatch, QUALITY_PREFERENCE=["1080p", "2160p", "720p"])
    migrate_filters.migrate()
    assert store["RESOLUTION_PREFERRED"] == ["1080p", "2160p", "720p"]


def test_quality_preference_does_not_become_a_source_rule(monkeypatch, store):
    """QUALITY_PREFERENCE holds a resolution despite its name. Reading it as a
    source preference would silently change every user's picks."""
    _old(monkeypatch, QUALITY_PREFERENCE=["1080p"])
    migrate_filters.migrate()
    assert "SOURCE_PREFERRED" not in store or store["SOURCE_PREFERRED"] == []


def test_allow_4k_false_excludes_2160p(monkeypatch, store):
    _old(monkeypatch, ALLOW_4K=False)
    migrate_filters.migrate()
    assert "2160p" in store["RESOLUTION_EXCLUDED"]


def test_exclude_bluray_no_longer_sweeps_up_remux(monkeypatch, store):
    _old(monkeypatch, EXCLUDE_BLURAY=True, EXCLUDE_REMUX=False)
    migrate_filters.migrate()
    excluded = store["SOURCE_EXCLUDED"]
    assert {"bluray", "bdrip", "brrip"} <= set(excluded)
    assert "remux" not in excluded


def test_exclude_cam_maps_to_every_cam_family_value(monkeypatch, store):
    _old(monkeypatch, EXCLUDE_CAM=True)
    migrate_filters.migrate()
    assert {"cam", "ts", "tc", "scr", "r5"} <= set(store["SOURCE_EXCLUDED"])


def test_strict_no_cam_maps_only_to_source_strict(monkeypatch, store):
    """It must not also make the undersized check hard; that coupling was a bug."""
    _old(monkeypatch, STRICT_NO_CAM=True)
    migrate_filters.migrate()
    assert store["SOURCE_STRICT"] is True
    assert store.get("EXCLUDE_UNDERSIZED_STRICT", False) is False


def test_prefer_webdl_and_hevc(monkeypatch, store):
    _old(monkeypatch, PREFER_WEBDL=True, PREFER_HEVC=True)
    migrate_filters.migrate()
    assert "webdl" in store["SOURCE_PREFERRED"]
    assert "webrip" in store["SOURCE_PREFERRED"]
    assert "web" in store["SOURCE_PREFERRED"]
    assert "hevc" in store["ENCODE_PREFERRED"]


def test_exclude_dv_p5_becomes_dv_only(monkeypatch, store):
    _old(monkeypatch, EXCLUDE_DV_P5=True)
    migrate_filters.migrate()
    assert "dv_only" in store["VISUAL_TAG_EXCLUDED"]


def test_language_settings_migrate_in_order(monkeypatch, store):
    _old(monkeypatch, AUDIO_LANGUAGE_PREFERENCE=["en", "multi"],
         EXCLUDE_LANGUAGES=["ru"])
    migrate_filters.migrate()
    assert store["LANGUAGE_PREFERRED"] == ["en", "multi"]
    assert store["LANGUAGE_EXCLUDED"] == ["ru"]


def test_dry_run_writes_nothing(monkeypatch, store):
    _old(monkeypatch, EXCLUDE_CAM=True)
    result = migrate_filters.migrate(dry_run=True)
    assert store == {}
    assert "SOURCE_EXCLUDED" in result


def test_stale_env_keys_are_reported(monkeypatch):
    monkeypatch.setenv("QUALITY_PREFERENCE", "1080p")
    messages = migrate_filters.warn_stale_env()
    assert any("QUALITY_PREFERENCE" in m for m in messages)
    assert any("RESOLUTION_PREFERRED" in m for m in messages)


def test_migration_runs_only_once(monkeypatch, store):
    """The retired env vars persist after upgrading, so a second run would read
    them again and clobber whatever the user has since set in the admin UI."""
    _old(monkeypatch, EXCLUDE_CAM=True)
    first = migrate_filters.migrate()
    assert "SOURCE_EXCLUDED" in first
    assert store.get(migrate_filters.MIGRATION_MARKER) is True

    # Simulate the marker now being set, as a real second startup would see it.
    import settings as _s
    monkeypatch.setattr(_s, "get",
                        lambda k, d=None: True if k == migrate_filters.MIGRATION_MARKER else d)
    store.clear()
    assert migrate_filters.migrate() == {}
    assert store == {}, "a second run must write nothing"


def test_force_reruns_a_completed_migration(monkeypatch, store):
    import settings as _s
    monkeypatch.setattr(_s, "get",
                        lambda k, d=None: True if k == migrate_filters.MIGRATION_MARKER
                        else ({"EXCLUDE_CAM": True}.get(k, d)))
    assert migrate_filters.migrate(force=True) != {}


def test_an_unmappable_value_is_dropped_not_raised(monkeypatch, store):
    """A migration runs before the admin UI is reachable, so raising would
    leave the user unable to fix the value that is blocking boot."""
    _old(monkeypatch, QUALITY_PREFERENCE=["totally_bogus", "1080p"])
    result = migrate_filters.migrate()
    assert result["RESOLUTION_PREFERRED"] == ["1080p"]


def test_retired_resolution_spellings_are_aliased(monkeypatch, store):
    """_QUALITY_PATTERNS matched 2160p, 4k and uhd alike, so a .env saying 4k
    meant 2160p and must migrate to it rather than being discarded."""
    _old(monkeypatch, QUALITY_PREFERENCE=["4k", "1080p"])
    assert migrate_filters.migrate()["RESOLUTION_PREFERRED"] == ["2160p", "1080p"]


def test_uhd_and_4k_do_not_produce_a_duplicate(monkeypatch, store):
    _old(monkeypatch, QUALITY_PREFERENCE=["4k", "uhd", "1080p"])
    assert migrate_filters.migrate()["RESOLUTION_PREFERRED"] == ["2160p", "1080p"]


def test_warn_stale_env_is_silent_for_a_clean_environment(monkeypatch):
    for key in migrate_filters.RETIRED:
        monkeypatch.delenv(key, raising=False)
    assert migrate_filters.warn_stale_env() == []


def test_warn_stale_env_names_a_key_the_user_actually_set(monkeypatch):
    monkeypatch.setenv("QUALITY_PREFERENCE", "1080p")
    messages = migrate_filters.warn_stale_env()
    assert len(messages) == 1
    assert "QUALITY_PREFERENCE" in messages[0]
    assert "RESOLUTION_PREFERRED" in messages[0]


def test_warn_stale_env_warns_about_an_explicitly_false_setting(monkeypatch):
    """A user who set EXCLUDE_BLURAY=false still has an inert key in .env."""
    monkeypatch.setenv("EXCLUDE_BLURAY", "false")
    assert any("EXCLUDE_BLURAY" in m for m in migrate_filters.warn_stale_env())
