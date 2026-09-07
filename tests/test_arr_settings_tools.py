"""Settings > Radarr / Sonarr: a Test button per arr and a root-folder
dropdown filled from the arr, instead of a free-text path typed blind.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


class FakeResp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body
        self.text = ""

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


@pytest.fixture(params=["radarr", "sonarr"])
def arr(request):
    return __import__(request.param)


def test_root_folders_lists_path_and_free_space(arr, monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"], seen["headers"] = url, headers
        return FakeResp(200, [{"id": 1, "path": "/movies", "freeSpace": 1024},
                              {"id": 2, "path": "/mnt/more", "freeSpace": None}])

    monkeypatch.setattr(arr.requests, "get", fake_get)
    out = arr.root_folders("http://arr.test/", "k")
    assert out == [{"path": "/movies", "free_space": 1024}, {"path": "/mnt/more", "free_space": None}]
    assert seen["url"] == "http://arr.test/api/v3/rootfolder"
    assert seen["headers"]["X-Api-Key"] == "k"


def test_root_folders_raises_on_a_bad_key(arr, monkeypatch):
    monkeypatch.setattr(arr.requests, "get", lambda url, headers=None, timeout=None: FakeResp(401, {}))
    with pytest.raises(Exception):
        arr.root_folders("http://arr.test", "wrong")


def test_system_status_returns_the_version(arr, monkeypatch):
    monkeypatch.setattr(arr.requests, "get",
                        lambda url, headers=None, timeout=None: FakeResp(200, {"version": "5.1.0.1234", "appName": "X"}))
    assert arr.system_status("http://arr.test", "k") == {"version": "5.1.0.1234"}


def test_system_status_is_none_when_unreachable(arr, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(arr.requests, "get", boom)
    assert arr.system_status("http://arr.test", "k") is None


# -- routes ------------------------------------------------------------------

def _route(path_re):
    src = _src("app.py")
    m = re.search(r'@app\.post\("' + path_re + r'"\)\s*\ndef (\w+)\(.*?\):\n(.*?)\n@app\.', src, re.S)
    assert m, f"route {path_re} not found"
    return m.group(2)


def test_root_folder_route_is_admin_only_and_validates_the_kind():
    body = _route(r"/ui/api/arr-import/root-folders-<kind>")
    assert "auth.is_admin()" in body.splitlines()[0:4].__str__()
    assert '("radarr", "sonarr")' in body
    # The route is now a thin alias over the service_tests registry rather
    # than calling radarr.root_folders/sonarr.root_folders directly.
    assert "service_tests" in body


def test_root_folder_route_uses_the_form_values_before_the_saved_ones():
    """The Settings page sends what is typed in the URL and key boxes, so a
    person can pick a folder before saving; blank falls back to saved. The
    fallback now lives in service_tests._v(), not in this route."""
    body = _route(r"/ui/api/arr-import/root-folders-<kind>")
    assert "_arr_values(kind)" in body
    assert "service_tests" in body
    helper = _src("service_tests.py").split("def _v(", 1)[1].split("\ndef ", 1)[0]
    assert "_settings.get(key" in helper


def test_test_routes_report_the_arr_version():
    """The routes are now thin aliases over service_tests.run(), which
    already reports the arr's version and item count."""
    for kind in ("radarr", "sonarr"):
        body = _route(rf"/ui/api/arr-import/test-{kind}")
        assert f'service_tests.run("{kind}"' in body
        assert "version=" in body
    assert "def _arr_test" not in _src("app.py")
