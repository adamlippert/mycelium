"""One tester per credentialed service and one picker per remote list,
shared by the Settings page and the setup wizard.
"""
import importlib
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.pop("settings", None)

import pytest
import requests

import db
import debridio
import service_tests
import settings

_ROOT = os.path.join(os.path.dirname(__file__), "..")


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


class FakeResp:
    def __init__(self, status, body=None, ctype="application/json"):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = {"content-type": ctype}
        self.text = str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def http(monkeypatch):
    """Fakes service_tests' HTTP seam: routes a URL substring to a response
    and records every call. Nothing reaches the network."""
    calls = []
    routes = {}

    def fake(method, url, **kw):
        calls.append((method, url, kw))
        for needle, resp in routes.items():
            if needle in url:
                return resp() if callable(resp) else resp
        return FakeResp(404)

    monkeypatch.setattr(service_tests, "_http", fake)
    # The root folder / quality profile pickers now call radarr.py's and
    # sonarr.py's own functions (which call requests.get directly) rather
    # than service_tests._http, so those need faking too.
    for mod in ("radarr", "sonarr"):
        monkeypatch.setattr(
            importlib.import_module(mod).requests, "get",
            lambda url, headers=None, timeout=None: fake("GET", url, headers=headers, timeout=timeout),
        )
    return routes, calls


def test_every_schema_test_and_picker_name_is_registered():
    for f in settings.fields_by_key().values():
        if f["test"]:
            assert f["test"] in service_tests.TESTS, f["key"]
        if f["picker"]:
            assert f["picker"] in service_tests.PICKERS, f["key"]


def test_torbox_reports_ok_and_never_echoes_the_key(http):
    routes, calls = http
    routes["/torrents/mylist"] = FakeResp(200, {"data": []})
    out = service_tests.run("torbox", {"TORBOX_API_KEY": "secret-key"})
    assert out["ok"] is True and "secret-key" not in out["message"]
    assert calls[0][2]["headers"]["Authorization"] == "Bearer secret-key"


def test_a_blank_value_falls_back_to_the_saved_setting(http):
    routes, calls = http
    settings.set("TORBOX_API_KEY", "saved-key")
    routes["/torrents/mylist"] = FakeResp(200, {"data": []})
    service_tests.run("torbox", {"TORBOX_API_KEY": ""})
    assert calls[0][2]["headers"]["Authorization"] == "Bearer saved-key"


def test_a_missing_credential_is_reported_without_a_request(http, monkeypatch):
    routes, calls = http
    import config
    monkeypatch.setattr(config, "TORBOX_API_KEY", "")
    settings.set("TORBOX_API_KEY", None)
    out = service_tests.run("torbox", {})
    assert out["ok"] is False and "key" in out["message"].lower() and calls == []


def test_a_missing_credential_names_the_schema_label_not_the_raw_key(monkeypatch):
    """_need() must report the field's schema label ("TorBox API key"), not
    the old key.replace("_", " ").lower() transform ("torbox api key")."""
    import config
    monkeypatch.setattr(config, "TORBOX_API_KEY", "")
    settings.set("TORBOX_API_KEY", None)
    out = service_tests.run("torbox", {})
    label = settings.fields_by_key()["TORBOX_API_KEY"]["label"]
    assert label == "TorBox API key"
    assert label in out["message"]


def test_an_unknown_key_falls_back_to_the_old_transform():
    assert service_tests._need({}, "NOT_A_REAL_SETTING_KEY") == "not a real setting key"


def test_a_timeout_reads_as_timed_out(http):
    routes, _ = http
    routes["/System/Info/Public"] = lambda: (_ for _ in ()).throw(requests.Timeout())
    out = service_tests.run("jellyfin", {"JELLYFIN_URL": "http://jf.test"})
    assert out == {"ok": False, "message": "timed out after 8 s"}


def test_realdebrid_reports_the_user(http):
    routes, calls = http
    routes["/user"] = FakeResp(200, {"username": "adam", "type": "premium", "expiration": "2027-01-01T00:00:00.000Z"})
    out = service_tests.run("realdebrid", {"REALDEBRID_API_KEY": "rd"})
    assert out["ok"] and "adam" in out["message"] and "2027-01-01" in out["message"]
    assert calls[0][2]["headers"]["Authorization"] == "Bearer rd"


def test_tmdb_accepts_and_rejects(http):
    routes, _ = http
    routes["/configuration"] = FakeResp(200, {"images": {}})
    assert service_tests.run("tmdb", {"TMDB_API_KEY": "k"})["ok"] is True
    routes["/configuration"] = FakeResp(401, {"status_message": "Invalid API key"})
    out = service_tests.run("tmdb", {"TMDB_API_KEY": "k"})
    assert out["ok"] is False and "401" in out["message"]


def test_oidc_reads_the_discovery_document(http):
    routes, calls = http
    routes["/.well-known/openid-configuration"] = FakeResp(200, {
        "issuer": "https://auth.test/app/o/mycelium/",
        "authorization_endpoint": "https://auth.test/authorize",
        "token_endpoint": "https://auth.test/token",
    })
    out = service_tests.run("oidc", {"OIDC_ISSUER_URL": "https://auth.test/app/o/mycelium/"})
    assert out["ok"] and "auth.test" in out["message"] and "token" in out["message"]
    assert calls[0][1] == "https://auth.test/app/o/mycelium/.well-known/openid-configuration"
    routes["/.well-known/openid-configuration"] = FakeResp(200, {"issuer": "x"})
    out = service_tests.run("oidc", {"OIDC_ISSUER_URL": "https://auth.test/app/o/mycelium/"})
    assert out["ok"] is False and "authorization" in out["message"]


def test_zilean_pg_connects_and_reports_the_version(monkeypatch):
    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, q): self.q = q
        def fetchone(self): return ("PostgreSQL 16.2 on x86_64",)

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return Cur()

    seen = {}

    def connect(**kw):
        seen.update(kw)
        return Conn()

    monkeypatch.setattr(service_tests, "_pg_connect", connect)
    out = service_tests.run("zilean_pg", {"ZILEAN_PG_HOST": "pg", "ZILEAN_PG_PORT": "5433", "ZILEAN_PG_DB": "z",
                                          "ZILEAN_PG_USER": "u", "ZILEAN_PG_PASSWORD": "p"})
    assert out["ok"] and "16.2" in out["message"]
    assert seen["host"] == "pg" and seen["port"] == 5433 and seen["connect_timeout"] == 8
    monkeypatch.setattr(service_tests, "_pg_connect", lambda **kw: (_ for _ in ()).throw(RuntimeError("refused")))
    out = service_tests.run("zilean_pg", {"ZILEAN_PG_HOST": "pg"})
    assert out["ok"] is False
    assert out["message"] == "could not connect to Postgres; check host, port, database, user and password"


def test_debridio_fetches_the_manifest_with_the_typed_key(http, monkeypatch):
    routes, calls = http
    routes["/manifest.json"] = FakeResp(200, {"name": "Debridio", "version": "1.2.3"})
    out = service_tests.run("debridio", {"DEBRIDIO_API_KEY": "dk"})
    assert out["ok"] and "Debridio" in out["message"] and "1.2.3" in out["message"]
    assert "dk" not in out["message"]
    expected_token = debridio.build_config_token(api_key="dk")
    assert calls[-1][1] == f"https://addon.debridio.com/{expected_token}/manifest.json"


def test_debridio_uses_a_typed_config_token_override_verbatim(http, monkeypatch):
    routes, calls = http
    routes["/manifest.json"] = FakeResp(200, {"name": "Debridio", "version": "1.2.3"})
    monkeypatch.setattr(debridio, "send_torbox_key", lambda: False)
    out = service_tests.run("debridio", {"DEBRIDIO_API_KEY": "dk", "DEBRIDIO_CONFIG_TOKEN": "not-base64-json!!"})
    assert out["ok"]
    expected_token = debridio.build_config_token(api_key="dk", config_token="not-base64-json!!")
    assert expected_token == "not-base64-json!!"
    assert calls[-1][1] == f"https://addon.debridio.com/{expected_token}/manifest.json"


def test_radarr_reports_version_and_count(http):
    routes, _ = http
    routes["/api/v3/system/status"] = FakeResp(200, {"version": "5.2.0"})
    routes["/api/v3/movie"] = FakeResp(200, [{"id": 1}, {"id": 2}])
    out = service_tests.run("radarr", {"RADARR_URL": "http://r.test", "RADARR_API_KEY": "k"})
    assert out == {"ok": True, "message": "Radarr 5.2.0, 2 movies"}


def test_unknown_service_is_a_key_error():
    with pytest.raises(KeyError):
        service_tests.run("nope", {})


def test_the_wizard_kinds_all_exist():
    for kind in ("torbox", "jellyfin", "seerr", "discord", "telegram", "trakt", "opensubtitles", "zilean", "radarr", "sonarr"):
        assert kind in service_tests.TESTS


def test_root_folder_picker_lists_paths_with_free_space(http):
    routes, _ = http
    routes["/api/v3/rootfolder"] = FakeResp(200, [{"path": "/movies", "freeSpace": 5 * 1024 ** 3}, {"path": "/more", "freeSpace": None}])
    out = service_tests.pick("radarr_root_folders", {"RADARR_URL": "http://r.test", "RADARR_API_KEY": "k"})
    assert out == {"ok": True, "options": [{"value": "/movies", "label": "/movies (5 GB free)"}, {"value": "/more", "label": "/more"}]}


def test_quality_profile_picker_lists_names(http):
    routes, _ = http
    routes["/api/v3/qualityprofile"] = FakeResp(200, [{"id": 1, "name": "HD-1080p"}, {"id": 6, "name": "Ultra-HD"}])
    out = service_tests.pick("sonarr_quality_profiles", {"SONARR_URL": "http://s.test", "SONARR_API_KEY": "k"})
    assert out == {"ok": True, "options": [{"value": "HD-1080p", "label": "HD-1080p"}, {"value": "Ultra-HD", "label": "Ultra-HD"}]}


def test_a_picker_failure_is_an_error_not_an_empty_list(http):
    routes, _ = http
    routes["/api/v3/rootfolder"] = FakeResp(401)
    out = service_tests.pick("radarr_root_folders", {"RADARR_URL": "http://r.test", "RADARR_API_KEY": "bad"})
    assert out["ok"] is False and out["error"]
    assert service_tests.pick("radarr_root_folders", {})["ok"] is False


def test_the_routes_exist_and_the_wizard_and_arr_import_use_the_registry():
    src = _src("app.py")
    assert re.search(r'@app\.post\("/ui/api/settings/test/<service>"\)', src)
    assert re.search(r'@app\.post\("/ui/api/settings/picker/<name>"\)', src)
    wizard = src.split('@app.post("/setup/test/<kind>")', 1)[1].split("\n\n\n", 1)[0]
    assert "service_tests.run(kind" in wizard and '__import__("requests")' not in wizard
    arr = src.split('/ui/api/arr-import/test-radarr', 1)[1][:2000]
    assert "service_tests" in arr
    assert "def _arr_test" not in src
    assert '_settings_mod.get("ARR_SYNC_INTERVAL_MINUTES"' in src
    assert '_settings_mod.get("DISK_SYNC_INTERVAL_MINUTES"' in src


_CAPS = ('<?xml version="1.0" encoding="UTF-8"?><caps><server version="6.1.5" '
         'title="MediaFusion | ElfHosted" url="https://mf.test"/></caps>')


def test_mediafusion_reports_the_caps_server(http, monkeypatch):
    routes, calls = http
    routes["/torznab?t=caps"] = FakeResp(200, _CAPS, ctype="text/xml")
    out = service_tests.run("mediafusion", {"MEDIAFUSION_URL": "https://mf.test", "MEDIAFUSION_API_KEY": "pw"})
    assert out["ok"] and out["message"] == "MediaFusion | ElfHosted 6.1.5"
    assert calls[-1][1] == "https://mf.test/torznab?t=caps&apikey=pw"
    assert "pw" not in out["message"]


def test_comet_explains_a_refused_torznab_path(http, monkeypatch):
    routes, calls = http
    routes["/torznab/api?t=caps"] = FakeResp(403, "Forbidden", ctype="text/html")
    out = service_tests.run("comet", {"COMET_URL": "https://comet.elfhosted.com"})
    assert out["ok"] is False
    assert out["message"] == "this instance does not expose Torznab; use your own Comet URL"


def test_comet_blank_url_uses_the_schema_label(http, monkeypatch):
    monkeypatch.setattr(service_tests._settings, "get", lambda k, d=None: d)
    out = service_tests.run("comet", {})
    assert out == {"ok": False, "message": "Comet URL is empty"}
