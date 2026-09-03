"""Jellyfin never probes .strm files during a library scan: resolution, codec
and audio stay empty until an item's first playback. The data is already
known locally, so the NFO can carry it and the library reads correctly from
the moment it is scanned, with no probe and no provider contact.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import nfo_generator


def test_resolution_becomes_width_and_height():
    xml = nfo_generator._streamdetails_xml("1080p", "Some.Movie.1080p.WEB-DL.x264")

    assert "<width>1920</width>" in xml
    assert "<height>1080</height>" in xml


def test_2160p_maps_to_uhd_dimensions():
    xml = nfo_generator._streamdetails_xml("2160p", "Some.Movie.2160p.WEB-DL")

    assert "<width>3840</width>" in xml
    assert "<height>2160</height>" in xml


def test_codec_comes_from_the_release_name():
    xml = nfo_generator._streamdetails_xml("1080p", "Some.Movie.1080p.WEB-DL.HEVC")

    assert "<codec>hevc</codec>" in xml


def test_audio_channels_are_carried():
    xml = nfo_generator._streamdetails_xml("1080p", "Some.Movie.1080p.DDP.5.1")

    assert "<channels>6</channels>" in xml


def test_nothing_known_yields_no_block():
    """An empty streamdetails element is worse than none: Jellyfin would
    treat it as authoritative and never probe."""
    assert nfo_generator._streamdetails_xml(None, "") == ""


def test_movie_nfo_embeds_the_block_when_given_details():
    xml = nfo_generator._movie_nfo(
        "Some Movie", 2024, "tt1234567",
        quality="1080p", release_name="Some.Movie.1080p.WEB-DL.x264")

    assert "<fileinfo>" in xml and "<streamdetails>" in xml
    assert "<height>1080</height>" in xml
    assert xml.rstrip().endswith("</movie>")


def test_movie_nfo_without_details_is_unchanged():
    """Existing call sites pass three arguments and must keep working."""
    xml = nfo_generator._movie_nfo("Some Movie", 2024, "tt1234567")

    assert "<fileinfo>" not in xml
    assert "<title>Some Movie</title>" in xml
