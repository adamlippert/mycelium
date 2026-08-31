import os, sys
os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import settings as _s


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setattr(_s.db, "get_all_settings", lambda: {})
    return _s.all_for_ui()


def _group(ui):
    return next(g for g in ui if g["id"] == "filter_rules")


def test_the_filter_rules_group_exists_with_all_thirty_five_keys(ui):
    assert len(_group(ui)["items"]) == 35


def test_every_list_key_carries_its_vocabulary(ui):
    """The editor renders a dropdown from options. A key without them would
    render an empty picker with no way to add a value."""
    missing = [i["key"] for i in _group(ui)["items"]
               if i["kind"] == "list" and not i["options"]]
    assert missing == []


def test_every_rule_key_is_hot_reloadable(ui):
    """The editor saves without a restart. A key marked otherwise would make
    the UI tell the user to restart for a change that takes effect at once."""
    assert all(i["hot_reload"] for i in _group(ui)["items"])


def test_key_names_match_what_the_editor_writes(ui):
    """The editor writes hidden inputs named setting_<KEY>. If these names
    drift, saving silently stops working while every test still passes."""
    keys = {i["key"] for i in _group(ui)["items"]}
    for prefix in ("RESOLUTION", "SOURCE", "ENCODE", "VISUAL_TAG",
                   "AUDIO_TAG", "AUDIO_CHANNELS", "LANGUAGE"):
        for state in ("PREFERRED", "EXCLUDED", "REQUIRED", "INCLUDED"):
            assert f"{prefix}_{state}" in keys
        assert f"{prefix}_STRICT" in keys


def test_strict_keys_are_bools_and_state_keys_are_lists(ui):
    for item in _group(ui)["items"]:
        expected = "bool" if item["key"].endswith("_STRICT") else "list"
        assert item["kind"] == expected, item["key"]


def test_the_save_endpoint_still_reads_the_setting_prefix():
    """The editor's hidden inputs are named setting_<KEY> because that is what
    /ui/settings parses. This pins the prefix so a rename cannot pass silently.

    app.py is read as TEXT rather than imported: importing it pulls in
    apscheduler, which is not installed in the test environment, and no other
    test imports app either.
    """
    import pathlib
    import re

    source = pathlib.Path(__file__).resolve().parent.parent.joinpath("app.py").read_text()
    match = re.search(r"def ui_save_settings.*?(?=\ndef |\n@app)", source, re.S)
    assert match, "ui_save_settings not found in app.py"
    assert 'startswith("setting_")' in match.group(0), (
        "the save endpoint no longer filters on the setting_ prefix; the "
        "rules editor writes hidden inputs with that prefix and would "
        "silently stop saving")


def test_a_fresh_install_still_filters_without_any_env_or_database():
    """The retired booleans all defaulted to ON: EXCLUDE_CAM, EXCLUDE_REMUX,
    EXCLUDE_DV_P5, PREFER_WEBDL, PREFER_HEVC and QUALITY_PREFERENCE. If the
    rule keys that replaced them shipped empty, a brand new install with no
    .env and no database would silently accept cam rips, telesyncs and Dolby
    Vision releases with no HDR10 base layer.

    This pins the code defaults, not .env.example. A user who deletes their
    .env should still get Mycelium's historical behaviour.
    """
    import config

    assert "cam" in config.SOURCE_EXCLUDED
    assert "remux" in config.SOURCE_EXCLUDED
    assert "workprint" in config.SOURCE_EXCLUDED
    assert "webdl" in config.SOURCE_PREFERRED
    assert "hevc" in config.ENCODE_PREFERRED
    assert "dv_only" in config.VISUAL_TAG_EXCLUDED
    assert config.RESOLUTION_PREFERRED == ["1080p", "2160p", "720p"]


def test_bluray_is_not_excluded_by_default():
    """EXCLUDE_BLURAY defaulted to false, and the retiring regexes overlapped
    so that excluding BluRay silently dropped remuxes too. Neither behaviour
    should be reintroduced through a default."""
    import config

    assert "bluray" not in config.SOURCE_EXCLUDED
    assert "bdrip" not in config.SOURCE_EXCLUDED


def test_no_retired_setting_is_still_offered_in_the_settings_ui():
    """A retired key rendered as a live control is worse than no control at all.

    The twelve booleans were replaced in 0.7.0 and nothing reads them any more,
    but SETTING_GROUPS kept listing them, so the admin page still showed
    EXCLUDE_CAM, PREFER_HEVC, QUALITY_PREFERENCE and the rest as editable
    fields. Toggling one saved a value that no code path ever consults, which
    reads as "the setting is broken" rather than "the setting is gone".

    Ties the UI to migrate_filters.RETIRED, so retiring another key in future
    fails here until it is also pulled out of the settings page.
    """
    import migrate_filters
    import settings

    shown = {k for group in settings.SETTING_GROUPS for k in group["keys"]}
    still_offered = sorted(shown & set(migrate_filters.RETIRED))

    assert not still_offered, (
        "retired settings still editable in the UI: "
        + ", ".join(f"{k} (use {migrate_filters.RETIRED[k]})" for k in still_offered)
    )


def test_the_settings_that_replaced_them_are_offered_instead():
    """Removing the old controls must not leave the user with no way to filter."""
    import settings

    shown = {k for group in settings.SETTING_GROUPS for k in group["keys"]}
    for key in ("RESOLUTION_PREFERRED", "SOURCE_EXCLUDED", "ENCODE_PREFERRED",
                "LANGUAGE_EXCLUDED", "SORT_ORDER"):
        assert key in shown, f"{key} is not reachable from the settings page"


def test_live_size_and_seeder_settings_survive():
    """These sit in the same group as the retired ones and are still read."""
    import settings

    shown = {k for group in settings.SETTING_GROUPS for k in group["keys"]}
    for key in ("MIN_SEEDERS", "MAX_SIZE_GB", "EXCLUDE_UNDERSIZED_RELEASES",
                "EXCLUDE_UNDERSIZED_STRICT", "OPENSUBTITLES_LANGUAGES"):
        assert key in shown, f"{key} is live but no longer editable"


def test_the_series_title_repair_is_reachable_from_the_ui():
    """repair_tvshow_titles() and its endpoint existed for months with no
    button anywhere, so the only way to run it was to call the URL by hand.
    A repair nobody can find does not repair anything.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    app_src = (root / "app.py").read_text()
    api = (root / "frontend" / "src" / "api.ts").read_text()

    assert "/ui/api/repair-tvshow-titles" in app_src, "endpoint disappeared"
    assert "/ui/api/repair-tvshow-titles" in api, "the SPA does not call the endpoint"


def test_every_spa_url_calls_an_endpoint_that_exists():
    """A renamed route leaves a button that fails only when someone clicks it.
    Scans every string literal starting with /ui/ across the SPA source
    (skipping template strings that interpolate ids) and requires app.py to
    define each path."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    # Routes are defined in app.py and in plugin route modules (trakt,
    # webplayer register their own /ui/api/ paths).
    app_src = (root / "app.py").read_text()
    for f in (root / "plugins").rglob("*.py"):
        app_src += f.read_text()

    called = set()
    for f in (root / "frontend" / "src").rglob("*.ts*"):
        text = f.read_text()
        for u in re.findall(r"['\"`](/ui/[^'\"`?]+)['\"`]", text):
            if "${" in u or u.endswith("/"):
                continue
            called.add(u)
    assert called, "no /ui/ URLs found in the SPA source at all"
    missing = sorted(u for u in called
                     if f'"{u}"' not in app_src and f"'{u}'" not in app_src)
    assert not missing, f"the SPA calls routes app.py does not define: {missing}"
