"""Jellyfin 12 disabled the legacy X-Emby-Token header and the api_key query
parameter: every request must carry `Authorization: MediaBrowser Token="..."`,
which 10.x accepts as well. The tester and the health ping must prove the
key is accepted rather than call an endpoint that never needed one."""
import glob
import os
import re

import requests

import health
import jellyfin
import service_tests

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_auth_headers_use_the_standard_form(monkeypatch):
    assert jellyfin.auth_headers("abc") == {"Authorization": 'MediaBrowser Token="abc"'}
    assert jellyfin.auth_headers("") == {}
    monkeypatch.setattr(jellyfin.settings, "get", lambda k, d=None: "cfg" if k == "JELLYFIN_API_KEY" else d)
    assert jellyfin.auth_headers() == {"Authorization": 'MediaBrowser Token="cfg"'}
    assert jellyfin._jf_headers() == {"Content-Type": "application/json", "Authorization": 'MediaBrowser Token="cfg"'}


def test_no_source_file_sends_a_legacy_jellyfin_credential():
    offenders = []
    for path in glob.glob(os.path.join(_ROOT, "*.py")):
        src = open(path).read()
        # The header used as a dict key; a docstring may still name it.
        if re.search(r"""["'](X-Emby-Token|X-Emby-Authorization|X-MediaBrowser-Token)["']\s*:""", src):
            offenders.append(os.path.basename(path))
    assert offenders == [], f"legacy Jellyfin auth header in {offenders}"


class _Resp:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body or {}
        self.headers = {"content-type": "application/json"}
        self.text = "{}"

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def test_settings_tester_proves_the_key_on_the_authenticated_endpoint(monkeypatch):
    calls = []

    def fake(method, url, **kw):
        calls.append((url, kw.get("headers") or {}))
        if url.endswith("/System/Info"):
            return _Resp(401)
        return _Resp(200, {"ServerName": "Vault", "Version": "12.0.0"})
    monkeypatch.setattr(service_tests, "_http", fake)

    out = service_tests.run("jellyfin", {"JELLYFIN_URL": "http://jf.test", "JELLYFIN_API_KEY": "k"})
    assert out["ok"] is False and "rejected the API key" in out["message"] and "401" in out["message"]
    assert calls[-1] == ("http://jf.test/System/Info", {"Authorization": 'MediaBrowser Token="k"'})

    out = service_tests.run("jellyfin", {"JELLYFIN_URL": "http://jf.test", "JELLYFIN_API_KEY": ""})
    assert out["ok"] is True and out["message"] == "Vault 12.0.0"
    assert calls[-1] == ("http://jf.test/System/Info/Public", {})


def test_health_ping_marks_a_rejected_key_as_down(monkeypatch):
    values = {"JELLYFIN_URL": "http://jf.test", "JELLYFIN_API_KEY": "k"}
    monkeypatch.setattr(health.settings, "get", lambda k, d=None: values.get(k, d))
    seen = []

    def fake_get(url, headers=None, timeout=None):
        seen.append((url, headers))
        return _Resp(401 if url.endswith("/System/Info") else 200, [])
    monkeypatch.setattr(health.requests, "get", fake_get)

    row = next(r for r in health.check_all() if r["name"] == "Jellyfin")
    assert row["status"] == "down" and row["code"] == 401
    assert ("http://jf.test/System/Info", {"Authorization": 'MediaBrowser Token="k"'}) in seen

    values["JELLYFIN_API_KEY"] = ""
    seen.clear()
    row = next(r for r in health.check_all() if r["name"] == "Jellyfin")
    assert row["status"] == "ok"
    assert ("http://jf.test/System/Info/Public", {}) in seen
