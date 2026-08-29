import os
import sys

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
