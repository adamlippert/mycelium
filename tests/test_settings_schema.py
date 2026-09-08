"""The settings schema: one declaration per key that drives the admin
Settings page. Guards keep a new key from shipping without a label, and
keep the old groups payload byte-compatible for the Filter rules tab.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.pop("settings", None)

import pytest

import db
import settings

_ROOT = os.path.join(os.path.dirname(__file__), "..")
FIELD_KEYS = {"key", "label", "help", "kind", "options", "placeholder", "unit", "min", "max",
              "advanced", "depends_on", "test", "picker", "component", "readonly", "required"}
KINDS = {"bool", "int", "float", "str", "list", "url", "path", "secret", "select",
         "multiselect", "ordered", "custom"}


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


def _drop_cached_conn():
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db._tls.conn = None


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


def _fields():
    return list(settings.fields_by_key().values())


def test_every_field_has_exactly_the_declared_keys():
    for f in _fields():
        assert set(f) == FIELD_KEYS, f["key"]
        assert f["kind"] in KINDS, f["key"]


def test_every_field_has_a_label_and_help_without_dashes():
    for f in _fields():
        if f["kind"] == "custom":
            continue
        assert f["label"].strip() and f["help"].strip(), f["key"]
        for text in (f["label"], f["help"]):
            assert chr(0x2014) not in text and " -" + "- " not in text, f["key"]
    for s in settings.SECTIONS:
        assert s["title"].strip() and s["description"].strip() and s["icon"], s["id"]


def test_every_typed_key_is_listed_once_or_deliberately_unlisted():
    typed = (settings._BOOL_KEYS | settings._LIST_KEYS | settings._INT_KEYS
             | settings._FLOAT_KEYS | {*settings._ENUM_KEYS})
    listed = [f["key"] for f in _fields() if f["kind"] != "custom"]
    assert len(listed) == len(set(listed)), "a key appears in two sections"
    rule_keys = {*settings._RULE_LIST_KEYS} | settings._RULE_STRICT_KEYS
    missing = typed - set(listed) - settings._UNLISTED_KEYS - rule_keys
    assert not missing, f"typed keys without a field: {sorted(missing)}"
    assert not (set(listed) & settings._UNLISTED_KEYS)


def test_kind_agrees_with_the_type_buckets():
    for f in _fields():
        k, kind = f["key"], f["kind"]
        if kind == "custom":
            continue
        if k in settings._BOOL_KEYS:
            assert kind == "bool", k
        elif k in settings._INT_KEYS:
            assert kind == "int", k
        elif k in settings._FLOAT_KEYS:
            assert kind == "float", k
        elif k in settings._LIST_KEYS:
            assert kind in ("list", "multiselect", "ordered"), k
        elif k in settings._ENUM_KEYS:
            assert kind == "select", k
        else:
            assert kind in ("str", "url", "path", "secret", "select"), k


def test_depends_on_names_a_real_toggle_or_select_value():
    by_key = settings.fields_by_key()
    for f in _fields():
        dep = f["depends_on"]
        if not dep:
            continue
        key, _, value = dep.partition("=")
        assert key in by_key, f["key"]
        if value:
            assert by_key[key]["kind"] == "select", f["key"]
            assert value in [o["value"] for o in settings._resolve_options(by_key[key])], f["key"]
        else:
            assert by_key[key]["kind"] == "bool", f["key"]


def test_custom_fields_name_a_component_and_nothing_else_does():
    for f in _fields():
        assert bool(f["component"]) == (f["kind"] == "custom"), f["key"]


def test_the_secret_keys_are_declared_secret():
    for f in _fields():
        if re.search(r"KEY|TOKEN|SECRET|PASSWORD", f["key"]) and f["kind"] != "custom":
            assert f["kind"] == "secret", f["key"]


def test_the_old_groups_are_derived_and_keep_the_filter_rules_group():
    ids = [g["id"] for g in settings.SETTING_GROUPS]
    assert "filter_rules" in ids
    keys = {k for g in settings.SETTING_GROUPS for k in g["keys"]}
    assert keys >= {f["key"] for f in _fields() if f["kind"] != "custom"}
    payload = settings.all_for_ui()
    assert payload and {"id", "title", "items"} <= set(payload[0])


def test_schema_for_ui_carries_value_override_and_resolved_options():
    settings.set("MIN_SEEDERS", 7)
    settings.set("RADARR_URL", "http://radarr.test")
    out = settings.schema_for_ui()
    by_key = {f["key"]: f for s in out for f in s["fields"]}
    assert by_key["MIN_SEEDERS"]["value"] == 7 and by_key["MIN_SEEDERS"]["overridden"] is True
    assert by_key["MAX_SIZE_GB"]["overridden"] is False
    assert by_key["RADARR_URL"]["hot_reload"] is True
    langs = by_key["OPENSUBTITLES_LANGUAGES"]["options"]
    assert {"value": "en", "label": "en"} in langs
    sort = by_key["SORT_ORDER"]["options"]
    assert [o["value"] for o in sort] == list(settings._streams.SORT_CRITERIA)
    assert by_key["ZILEAN_MODE"]["options"] == [{"value": "external", "label": "External service"},
                                                 {"value": "native", "label": "Native index"}]
    assert by_key["AUTO_ADD_REGION"]["options"][0] == {"value": "NL", "label": "Netherlands"}
    assert by_key["RADARR_ROOT_FOLDER"]["picker"] == "radarr_root_folders"
    assert by_key["TORBOX_API_KEY"]["test"] == "torbox"
    # A secret's value is never sent to the browser, only whether it is set.
    settings.set("TORBOX_API_KEY", "abc")
    out = settings.schema_for_ui()
    tb = next(f for s in out for f in s["fields"] if f["key"] == "TORBOX_API_KEY")
    assert tb["value"] is True


def test_the_new_keys_are_typed_and_have_defaults():
    import config
    assert "ARR_SYNC_INTERVAL_MINUTES" in settings._INT_KEYS
    assert "DISK_SYNC_INTERVAL_MINUTES" in settings._INT_KEYS
    assert "RADARR_QUALITY_PROFILE" in settings.HOT_RELOAD and "SONARR_QUALITY_PROFILE" in settings.HOT_RELOAD
    assert config.RADARR_QUALITY_PROFILE == "" and config.SONARR_QUALITY_PROFILE == ""


def test_the_schema_route_exists_and_is_admin_only():
    src = _src("app.py")
    m = re.search(r'@app\.get\("/ui/api/settings/schema"\)\s*\ndef (\w+)\(\):(.*?)\n\n', src, re.S)
    assert m and "is_admin()" in m.group(2) and "schema_for_ui()" in m.group(2)


def test_help_lines_are_short_sentences():
    for f in _fields():
        if f["kind"] == "custom":
            continue
        assert len(f["help"]) <= 220, f["key"]
        assert f["help"].rstrip().endswith("."), f["key"]
        assert len(f["label"]) <= 40, f["key"]


def test_oidc_settings_go_through_the_settings_overlay():
    """oidc.py must read every OIDC key via the settings overlay (through its
    _s() helper) so a Settings > Security edit takes effect without a rebuilt
    .env; the only cfg.OIDC_ reference allowed is the getattr fallback inside
    _s(), which does not spell out a key name and so never matches this."""
    src = _src("oidc.py")
    assert re.findall(r"cfg\.OIDC_\w+", src) == []


def test_clearing_a_secret_with_an_empty_value_removes_the_override():
    """settings.set(key, "") must clear a secret's DB override the same way
    it clears any other key, so posting setting_<KEY>="" from the admin
    Settings page's Clear button actually removes a stored secret instead of
    silently keeping it."""
    assert settings.fields_by_key()["TRAKT_CLIENT_SECRET"]["kind"] == "secret"
    settings.set("TRAKT_CLIENT_SECRET", "abc123")
    assert settings.get("TRAKT_CLIENT_SECRET") == "abc123"
    settings.set("TRAKT_CLIENT_SECRET", "")
    # No TRAKT_CLIENT_SECRET in the environment, so config.TRAKT_CLIENT_SECRET
    # is "" (config._env's own default) and that is exactly what falls
    # through once the DB override is gone.
    assert settings.get("TRAKT_CLIENT_SECRET") == ""
    assert db.get_setting("TRAKT_CLIENT_SECRET") is None


def test_clearing_a_secret_backed_by_the_environment_leaves_the_env_value_in_force(monkeypatch):
    """settings.set(key, None) only ever deletes the DB override row
    (db.set_setting(key, None) -> DELETE). A secret supplied through the
    environment (config.<KEY>, e.g. a Dokploy env var) has no override to
    delete, so clearing it must be a no-op: settings.get(key) keeps
    returning the config value, and _field_for_ui must keep reporting the
    field as set. Only clearing an actual DB override removes the value."""
    import config
    assert settings.fields_by_key()["TORBOX_API_KEY"]["kind"] == "secret"
    monkeypatch.setattr(config, "TORBOX_API_KEY", "env-supplied-key")

    # No override yet: clearing is a no-op, the env value is still in force.
    settings.set("TORBOX_API_KEY", None)
    assert settings.get("TORBOX_API_KEY") == "env-supplied-key"
    field = settings._field_for_ui(settings.fields_by_key()["TORBOX_API_KEY"], db.get_all_settings())
    assert field["value"] is True
    assert field["overridden"] is False

    # An override present: clearing removes it and the env value takes over.
    settings.set("TORBOX_API_KEY", "db-override-key")
    assert settings.get("TORBOX_API_KEY") == "db-override-key"
    settings.set("TORBOX_API_KEY", None)
    assert db.get_setting("TORBOX_API_KEY") is None
    assert settings.get("TORBOX_API_KEY") == "env-supplied-key"
    field = settings._field_for_ui(settings.fields_by_key()["TORBOX_API_KEY"], db.get_all_settings())
    assert field["value"] is True
    assert field["overridden"] is False


def test_settings_and_setup_save_routes_clear_any_empty_posted_value():
    """Both save routes must treat an empty posted value as "clear this
    key's override" without carving secrets out of that path, since the
    Settings page's Clear button relies on it posting setting_<KEY>=""."""
    for name, route in (("app.py", '@app.post("/ui/settings")'), ("app.py", '@app.post("/setup/save")')):
        src = _src(name)
        idx = src.index(route)
        body = src[idx:idx + 1800]
        assert 'value == ""' in body
        assert "settings.set(key, None)" in body or "_settings.set(key, None)" in body


def test_the_torznab_scraper_keys_are_typed_placed_and_hot():
    import config
    fields = settings.fields_by_key()
    for key in ("COMET_ENABLED", "MEDIAFUSION_ENABLED"):
        assert key in settings._BOOL_KEYS and fields[key]["kind"] == "bool"
    assert fields["COMET_URL"]["kind"] == "url" and fields["COMET_URL"]["depends_on"] == "COMET_ENABLED"
    assert fields["COMET_URL"]["test"] == "comet"
    assert fields["MEDIAFUSION_URL"]["kind"] == "url" and fields["MEDIAFUSION_URL"]["test"] == "mediafusion"
    assert fields["MEDIAFUSION_API_KEY"]["kind"] == "secret" and fields["MEDIAFUSION_API_KEY"]["depends_on"] == "MEDIAFUSION_ENABLED"
    section = next(s for s in settings.SECTIONS if s["id"] == "scrapers")
    keys = [f["key"] for f in section["fields"]]
    assert keys.index("DEBRIDIO_CONFIG_TOKEN") < keys.index("COMET_ENABLED") < keys.index("MEDIAFUSION_ENABLED")
    for key in ("COMET_ENABLED", "COMET_URL", "MEDIAFUSION_ENABLED", "MEDIAFUSION_URL", "MEDIAFUSION_API_KEY"):
        assert key in settings.HOT_RELOAD
    assert config.COMET_ENABLED is False and config.COMET_URL == ""
    assert config.MEDIAFUSION_ENABLED is False and config.MEDIAFUSION_URL == "https://mediafusion.elfhosted.com"
    assert config.MEDIAFUSION_API_KEY == ""
