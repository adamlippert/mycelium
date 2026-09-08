import os
import sys
import time

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import scrapers
import streams as streams_mod


def _s(h, source, quality="1080p"):
    return streams_mod.Stream(name=source, title=f"T.{quality}", info_hash=h,
                              quality=quality, seeders=10, size_gb=5.0,
                              is_season_pack=False, source=source)


@pytest.fixture(autouse=True)
def _all_enabled_and_healthy(monkeypatch):
    monkeypatch.setattr(scrapers._settings, "get", lambda k, d=None: True)
    monkeypatch.setattr(scrapers.health_cache, "is_up", lambda name: True)
    monkeypatch.setattr(scrapers, "rank_streams",
                        lambda s, prefer_season_pack=False, override=None: list(s))


def _wire(monkeypatch, deb=(), zil=(), tor=(), com=(), mf=()):
    monkeypatch.setattr(scrapers.debridio, "fetch", lambda *a, **k: list(deb))
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: list(zil))
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: list(tor))

    def fake_torznab(name, base_url, path, media_type, imdb_id, season=None, episode=None, **kw):
        return list(com) if name == "comet" else list(mf)

    monkeypatch.setattr(scrapers.torznab_scraper, "fetch", fake_torznab)


def test_debridio_wins_a_duplicate_hash(monkeypatch):
    h = "a" * 40
    _wire(monkeypatch, deb=[_s(h, "debridio")], tor=[_s(h, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert len(out) == 1
    assert out[0].source == "debridio"


def test_also_seen_in_records_the_other_sources_in_priority_order(monkeypatch):
    h = "a" * 40
    _wire(monkeypatch, deb=[_s(h, "debridio")], zil=[_s(h, "zilean")],
          tor=[_s(h, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert out[0].also_seen_in == ("zilean", "torrentio")


def test_unique_result_has_empty_also_seen_in(monkeypatch):
    _wire(monkeypatch, deb=[_s("a" * 40, "debridio")], tor=[_s("b" * 40, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert all(s.also_seen_in == () for s in out)


def test_all_sources_are_merged(monkeypatch):
    _wire(monkeypatch, deb=[_s("a" * 40, "debridio")], zil=[_s("b" * 40, "zilean")],
          tor=[_s("c" * 40, "torrentio")])
    assert len(scrapers.fetch_candidates("movie", "tt1")) == 3


def _src(name):
    with open(os.path.join(os.path.dirname(__file__), "..", name), encoding="utf-8") as f:
        return f.read()


def test_the_five_torznab_keys_are_documented_in_env_example():
    # M4: config.py reads all five from the environment; every other
    # scraper's env surface is documented here, and this branch's was not.
    env = _src(".env.example")
    for key in ("COMET_ENABLED", "COMET_URL", "MEDIAFUSION_ENABLED",
               "MEDIAFUSION_URL", "MEDIAFUSION_API_KEY"):
        assert f"\n{key}=" in env, f"{key} missing from .env.example"


def test_registry_order_puts_the_torznab_scrapers_before_torrentio():
    assert [n for n, _, _ in scrapers._SCRAPERS] == ["debridio", "zilean", "comet", "mediafusion", "torrentio"]
    keys = {n: k for n, k, _ in scrapers._SCRAPERS}
    assert keys["comet"] == "COMET_ENABLED" and keys["mediafusion"] == "MEDIAFUSION_ENABLED"


def test_torznab_results_merge_and_record_also_seen_in(monkeypatch):
    h = "a" * 40
    _wire(monkeypatch, zil=[_s(h, "zilean")], com=[_s(h, "comet")], mf=[_s(h, "mediafusion")],
          tor=[_s(h, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert len(out) == 1 and out[0].source == "zilean"
    assert out[0].also_seen_in == ("comet", "mediafusion", "torrentio")


def test_comet_adapter_passes_url_and_settings(monkeypatch):
    seen = {}

    def fake_torznab(name, base_url, path, media_type, imdb_id, season=None, episode=None, **kw):
        seen.update(name=name, base_url=base_url, path=path, kw=kw, season=season, episode=episode)
        return []

    monkeypatch.setattr(scrapers.torznab_scraper, "fetch", fake_torznab)
    values = {"COMET_URL": "http://comet:8000", "MEDIAFUSION_URL": "https://mf.test", "MEDIAFUSION_API_KEY": "pw"}
    monkeypatch.setattr(scrapers._settings, "get", lambda k, d=None: values.get(k, d))
    scrapers._fetch_comet("series", "tt1", 1, 2, timeout=9)
    assert seen["name"] == "comet" and seen["base_url"] == "http://comet:8000" and seen["path"] == "/torznab/api"
    assert seen["season"] == 1 and seen["episode"] == 2
    assert seen["kw"] == {"api_key": "", "timeout": 9, "raise_on_error": True}
    scrapers._fetch_mediafusion("movie", "tt1", None, None)
    assert seen["name"] == "mediafusion" and seen["path"] == "/torznab" and seen["base_url"] == "https://mf.test"
    assert seen["kw"] == {"api_key": "pw", "raise_on_error": True}


def test_a_failing_scraper_does_not_fail_the_call(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("debridio exploded")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams",
                        lambda *a, **k: [_s("c" * 40, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert [s.source for s in out] == ["torrentio"]


def test_disabled_scraper_is_not_called(monkeypatch):
    monkeypatch.setattr(scrapers._settings, "get",
                        lambda k, d=None: k != "DEBRIDIO_ENABLED")

    def _boom(*a, **k):
        raise AssertionError("disabled scraper must not be called")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    assert scrapers.fetch_candidates("movie", "tt1") == []


def test_unhealthy_scraper_is_skipped(monkeypatch):
    monkeypatch.setattr(scrapers.health_cache, "is_up", lambda name: name != "debridio")

    def _boom(*a, **k):
        raise AssertionError("unhealthy scraper must not be called")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    assert scrapers.fetch_candidates("movie", "tt1") == []


def test_merge_order_is_priority_not_completion_order(monkeypatch):
    h = "a" * 40

    def _slow_debridio(*a, **k):
        time.sleep(0.15)
        return [_s(h, "debridio")]

    monkeypatch.setattr(scrapers.debridio, "fetch", _slow_debridio)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [_s(h, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert out[0].source == "debridio"
    assert out[0].also_seen_in == ("torrentio",)


def test_zilean_receives_no_media_type_argument(monkeypatch):
    seen = {}

    def _zilean(imdb_id, season=None, episode=None, **kwargs):
        seen["args"] = (imdb_id, season, episode)
        return []

    monkeypatch.setattr(scrapers.debridio, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", _zilean)
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    scrapers.fetch_candidates("series", "tt9", season=2, episode=3)
    assert seen["args"] == ("tt9", 2, 3)


def test_empty_everywhere_returns_empty(monkeypatch):
    _wire(monkeypatch)
    assert scrapers.fetch_candidates("movie", "tt1") == []


def test_all_failed_raises_only_when_asked(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", _boom)
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", _boom)
    # Default stays permissive so the seven non-destructive call sites are
    # unaffected.
    assert scrapers.fetch_candidates("movie", "tt1") == []
    with pytest.raises(scrapers.ScrapersUnavailable):
        scrapers.fetch_candidates("movie", "tt1", raise_if_inconclusive=True)


def test_no_active_scraper_raises_when_asked(monkeypatch):
    monkeypatch.setattr(scrapers.health_cache, "is_up", lambda name: False)
    assert scrapers.fetch_candidates("movie", "tt1") == []
    with pytest.raises(scrapers.ScrapersUnavailable):
        scrapers.fetch_candidates("movie", "tt1", raise_if_inconclusive=True)


def test_searched_successfully_and_found_nothing_does_not_raise(monkeypatch):
    # The whole point of the flag: a real "nothing out there" must stay an
    # empty list, or cleanup would stop deleting genuinely dead titles.
    _wire(monkeypatch)
    assert scrapers.fetch_candidates("movie", "tt1", raise_if_inconclusive=True) == []


def test_a_survivor_that_found_nothing_is_still_inconclusive(monkeypatch):
    # The guard is evaluated AFTER the merge: two scrapers erroring and the
    # third finding nothing gives no way to conclude the title is really
    # gone, so this must raise rather than return [] - unlike the case below,
    # where the survivor actually found something.
    def _boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", _boom)
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    with pytest.raises(scrapers.ScrapersUnavailable):
        scrapers.fetch_candidates("movie", "tt1", raise_if_inconclusive=True)


def test_a_survivor_that_found_something_is_not_an_outage(monkeypatch):
    # But if the survivor DID find candidates, a partial failure must not
    # block a legitimate repair.
    h = "a" * 40

    def _boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", _boom)
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams",
                        lambda *a, **k: [_s(h, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1", raise_if_inconclusive=True)
    assert [s.source for s in out] == ["torrentio"]


def test_fetch_debridio_wires_raise_on_error(monkeypatch):
    # Pins A3 itself: every outage test elsewhere replaces scrapers.debridio
    # wholesale with a lambda that ignores kwargs, so none of them would
    # notice if raise_on_error=True were quietly dropped from this call site
    # - which would silently reopen the exact gap A1-A3 exist to close.
    seen = {}

    def _record(*a, **k):
        seen.update(k)
        return []

    monkeypatch.setattr(scrapers.debridio, "fetch", _record)
    scrapers._fetch_debridio("movie", "tt1", None, None)
    assert seen.get("raise_on_error") is True
    seen.clear()
    scrapers._fetch_debridio("movie", "tt1", None, None, timeout=5)
    assert seen.get("raise_on_error") is True


def test_fetch_zilean_wires_raise_on_error(monkeypatch):
    seen = {}

    def _record(*a, **k):
        seen.update(k)
        return []

    monkeypatch.setattr(scrapers.zilean, "fetch_streams", _record)
    scrapers._fetch_zilean("movie", "tt1", None, None)
    assert seen.get("raise_on_error") is True
    seen.clear()
    scrapers._fetch_zilean("movie", "tt1", None, None, timeout=5)
    assert seen.get("raise_on_error") is True


def test_merge_candidates_does_not_rank(monkeypatch):
    calls = []
    monkeypatch.setattr(scrapers, "rank_streams",
                        lambda *a, **k: calls.append(1) or [])
    _wire(monkeypatch, deb=[_s("a" * 40, "debridio")])
    out = scrapers.merge_candidates("movie", "tt1")
    assert [s.source for s in out] == ["debridio"]
    assert calls == []


def test_merge_candidates_still_dedups_and_records_also_seen_in(monkeypatch):
    h = "a" * 40
    _wire(monkeypatch, deb=[_s(h, "debridio")], tor=[_s(h, "torrentio")])
    out = scrapers.merge_candidates("movie", "tt1")
    assert len(out) == 1
    assert out[0].also_seen_in == ("torrentio",)


def test_timeout_is_forwarded_to_every_scraper(monkeypatch):
    # M7: the name promises all five; the assertion used to cover three, and
    # the autouse fixture made the two Torznab adapters run for real against
    # the literal base URL "True" (harmless only because requests happens to
    # reject it before any socket opens).
    seen = {}

    def _rec(name):
        def _fn(*a, **k):
            seen[name] = k.get("timeout")
            return []
        return _fn

    monkeypatch.setattr(scrapers.debridio, "fetch", _rec("debridio"))
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", _rec("zilean"))
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", _rec("torrentio"))

    def fake_torznab(name, base_url, path, media_type, imdb_id, season=None, episode=None, **kw):
        seen[name] = kw.get("timeout")
        return []

    monkeypatch.setattr(scrapers.torznab_scraper, "fetch", fake_torznab)
    scrapers.merge_candidates("movie", "tt1", timeout=12)
    assert seen == {"debridio": 12, "zilean": 12, "comet": 12, "mediafusion": 12, "torrentio": 12}


def test_scraper_failure_is_logged_through_redact(monkeypatch, caplog):
    # build_config_token() is called outside the try, and the message shape
    # requests produces embeds the whole URL. Nothing here may reach the log.
    def _boom(*a, **k):
        raise RuntimeError("failed for url: https://addon.debridio.com/"
                           "eyJhcGlfa2V5IjoiZGtka2RrZGtka2RrZGsi/stream/movie/tt1.json")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    with caplog.at_level("DEBUG"):
        scrapers.fetch_candidates("movie", "tt1")
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert "eyJhcGlfa2V5" not in blob


def test_merge_candidates_redacts_the_mediafusion_api_key_from_the_log(monkeypatch, caplog):
    # C1: torznab_scraper.fetch redacted and re-raised the ORIGINAL
    # exception, and merge_candidates logged it a second time through
    # debridio.redact alone, which has no rule for MEDIAFUSION_API_KEY or
    # apikey=. This must be exercised at the merge_candidates log site, not
    # only at torznab_scraper.fetch's own log line.
    values = {"MEDIAFUSION_API_KEY": "secretpw"}
    monkeypatch.setattr(scrapers._settings, "get", lambda k, d=None: values.get(k, True))

    def fake_torznab(name, base_url, path, media_type, imdb_id, season=None, episode=None, **kw):
        if name == "mediafusion":
            raise scrapers.torznab_scraper.requests.exceptions.HTTPError(
                "403 Client Error for url: https://mf.example/torznab?t=movie&"
                "imdbid=tt1&limit=100&apikey=secretpw"
            )
        return []

    monkeypatch.setattr(scrapers.torznab_scraper, "fetch", fake_torznab)
    monkeypatch.setattr(scrapers.debridio, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    with caplog.at_level("WARNING"):
        scrapers.merge_candidates("movie", "tt1")
    assert "secretpw" not in caplog.text
    assert "mediafusion" in caplog.text


def test_merge_candidates_redacts_a_comet_access_token_from_the_log(monkeypatch, caplog):
    # I2: a protected Comet instance carries its token in the URL path, not
    # a query string, and the token never lands in settings under a key name
    # this module knows - it must be scrubbed by pattern alone.
    def fake_torznab(name, base_url, path, media_type, imdb_id, season=None, episode=None, **kw):
        if name == "comet":
            raise scrapers.torznab_scraper.requests.exceptions.HTTPError(
                "403 Client Error for url: https://comet.test/s/tok123abc/torznab/api?t=movie&imdbid=tt1"
            )
        return []

    monkeypatch.setattr(scrapers.torznab_scraper, "fetch", fake_torznab)
    monkeypatch.setattr(scrapers.debridio, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    with caplog.at_level("WARNING"):
        scrapers.merge_candidates("movie", "tt1")
    assert "tok123abc" not in caplog.text
    assert "comet" in caplog.text


def test_every_call_site_uses_the_orchestrator():
    """No module may call a scraper's fetch directly any more; that is what
    produced three inconsistent orchestration patterns in the first place."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    # Only the scraper modules themselves, plus the orchestrator that fans out
    # to them. find_web_candidates used to be exempted here; it now goes
    # through scrapers.merge_candidates, which gives it the same merge and
    # dedup without the ranking it deliberately does not want.
    allowed = {"scrapers.py", "zilean.py", "torrentio.py", "debridio.py"}
    skip_dirs = {".venv", ".git", "node_modules", "tests"}
    # \b would miss catbox's "_zilean.fetch_streams" alias, so match an
    # optional leading underscore-prefix instead.
    pattern = re.compile(r"\w*(?:zilean|torrentio|debridio)\.fetch(?:_streams)?\s*\(")
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if any(part in skip_dirs or part.startswith(".venv") for part in rel.parts[:-1]):
            continue
        if str(rel) in allowed or rel.name in allowed:
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{rel}:{i}")
    assert offenders == [], f"direct scraper calls remain: {offenders}"


def test_unique_win_recorded_only_when_no_other_source_had_it(monkeypatch):
    import processor
    recorded = []
    monkeypatch.setattr(processor.db, "record_metric",
                        lambda metric, label=None, **kw: recorded.append((metric, label)))

    unique = _s("a" * 40, "debridio")
    processor._record_source_metrics(unique)
    assert ("source_win", "debridio") in recorded
    assert ("source_unique_win", "debridio") in recorded

    recorded.clear()
    shared = _s("b" * 40, "debridio")
    shared.also_seen_in = ("torrentio",)
    processor._record_source_metrics(shared)
    assert ("source_win", "debridio") in recorded
    assert ("source_unique_win", "debridio") not in recorded
