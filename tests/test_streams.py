import os
import sys

import pytest

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streams
import torrentio


def _stream(**kw):
    base = dict(name="n", title="t", info_hash="a" * 40, quality="1080p",
                seeders=10, size_gb=5.0, is_season_pack=False)
    base.update(kw)
    return streams.Stream(**base)


def test_magnet_derives_from_info_hash():
    assert _stream().magnet == "magnet:?xt=urn:btih:" + "a" * 40


def test_new_fields_default_to_empty():
    s = _stream()
    assert s.cached is False
    assert s.also_seen_in == ()


def test_new_fields_are_settable():
    s = _stream(cached=True, also_seen_in=("zilean", "torrentio"))
    assert s.cached is True
    assert s.also_seen_in == ("zilean", "torrentio")


def test_source_defaults_to_torrentio_for_backwards_compatibility():
    assert _stream().source == "torrentio"


def test_torrentio_still_exports_the_old_name():
    assert torrentio.TorrentioStream is streams.Stream


def test_size_is_blank_when_unknown():
    assert _stream(size_gb=0.0).size == ""
    assert _stream(size_gb=5.25).size == "5.25 GB"


def test_parse_quality_recognises_each_bucket():
    assert streams.parse_quality("Movie.2160p.WEB") == "2160p"
    assert streams.parse_quality("Movie.1080p.WEB") == "1080p"
    assert streams.parse_quality("Movie.720p.WEB") == "720p"
    assert streams.parse_quality("Movie.480p.WEB") == "480p"


def test_parse_quality_treats_4k_and_uhd_as_2160p():
    assert streams.parse_quality("Movie 4K HDR") == "2160p"
    assert streams.parse_quality("Movie UHD BluRay") == "2160p"


def test_parse_quality_says_unknown_when_unrecognised():
    # Must match torrentio._classify_quality exactly: both feed the
    # quality_added metric label, and "" vs "unknown" splits one bucket
    # into two on the dashboard's Quality card.
    assert streams.parse_quality("Movie.DVDRip") == "unknown"
    assert streams.parse_quality("Movie.DVDRip") == torrentio._classify_quality(
        {"name": "Movie.DVDRip", "title": ""})


def test_parse_size_gb_handles_gb_and_mb():
    assert streams.parse_size_gb("⚡ 📺 4k 💾 85.37 GB") == 85.37
    assert streams.parse_size_gb("💾 700 MB") == pytest.approx(700 / 1024)


def test_parse_size_gb_returns_zero_when_absent():
    assert streams.parse_size_gb("no size here") == 0.0


def test_parse_seeders():
    assert streams.parse_seeders("👤 42 💾 5 GB") == 42
    assert streams.parse_seeders("no seeders") == 0


def test_rank_streams_is_reexported_from_torrentio():
    assert torrentio.rank_streams is streams.rank_streams


def test_rank_streams_soft_filter_allows_remux_when_it_is_all_there_is(monkeypatch):
    # Mycelium's excludes self-disable rather than return nothing. This is the
    # property that stops us pushing filters down to Debridio; lock it in.
    import settings as _settings
    monkeypatch.setattr(_settings, "get",
                        lambda k, d=None: True if k == "EXCLUDE_REMUX" else d)
    only_remux = [_stream(name="Movie 2160p BluRay REMUX", title="Movie REMUX")]
    assert len(streams.rank_streams(only_remux)) == 1
