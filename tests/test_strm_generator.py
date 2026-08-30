"""
Smoke tests voor strm_generator.py.

Doel: verantwoorden dat Jellyfin .strm logica intact blijft na Spore-wijzigingen
en vice versa. Geen live DB of netwerk nodig -- zware imports worden gemockt.

Secties:
  - Shared utilities  (_parse_info, _strm_path, _norm_title, naam-cleaning)
  - Plex Spore        (make_stub_mkv, _write_spore_stubs)
  - Jellyfin .strm    (_write_strm inclusief duplicate-skip)
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Verplichte env vars voor config.py (wordt NIET gemockt)
os.environ.setdefault("TORBOX_API_KEY", "test")
os.environ.setdefault("MEDIA_PATH", "/tmp/mycelium-test-media")
os.environ.setdefault("SPORE_MEDIA_PATH", "/tmp/mycelium-test-spore")
os.environ.setdefault("TORBOX_BASE_URL", "https://api.torbox.app/v1/api")
os.environ.setdefault("SPORE_ENABLED", "true")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import strm_generator as sg  # noqa: E402  (imports na sys.path setup)


# strm_generator doet bij import geen I/O (alleen regex-compilatie en een lock)
# en bindt zijn zware dependencies als module-attributen: `import db`,
# `import settings`, `import torbox as torbox_mod`. Daarom mocken we die
# attributen per test, in plaats van sys.modules te overschrijven vlak voor de
# import hieronder.
#
# Die oude aanpak was volgorde-afhankelijk en faalde stil: zodra een ander
# testbestand strm_generator al echt geimporteerd had (test_catchup.py ->
# catchup -> processor -> strm_generator), gaf `import strm_generator` hier de
# gecachete module terug, met de ECHTE settings/db er al aan gebonden. De swap
# in sys.modules deed dan niets en tests die op een gemockte settings leunen
# draaiden ongemerkt tegen de echte module.
_MOCKED_ATTRS = ("db", "jellyfin", "settings", "torbox_mod")

# Deze twee worden lui geimporteerd binnen functies en zijn dus alleen via
# sys.modules te onderscheppen. monkeypatch draait dat zelf weer terug, zodat
# er niets naar andere testbestanden lekt.
_MOCKED_LAZY = ("nfo_generator", "mp4_faststart")


@pytest.fixture(autouse=True)
def _mock_heavy_deps(monkeypatch):
    """Verse mocks per test - geen state die tussen tests door lekt."""
    for _attr in _MOCKED_ATTRS:
        monkeypatch.setattr(sg, _attr, MagicMock())
    for _mod in _MOCKED_LAZY:
        monkeypatch.setitem(sys.modules, _mod, MagicMock())


# =============================================================================
# Shared utilities
# =============================================================================

class TestParseInfo:
    def test_movie(self):
        info = sg._parse_info("Civil.War.2024.1080p.WEB-DL.EAC3.x264", "Civil.War.2024.mkv")
        assert info is not None
        assert info["type"] == "movie"
        assert "Civil War" in info["title"]
        assert info.get("year") == 2024

    def test_episode(self):
        info = sg._parse_info("Severance.S02E01.1080p", "Severance.S02E01.mkv")
        assert info is not None
        assert info["type"] == "episode"
        assert info["season"] == 2
        assert info["episode"] == 1

    def test_garbage_returns_none(self):
        assert sg._parse_info("", "") is None

    def test_site_prefix_stripped(self):
        info = sg._parse_info("[DEVIL-TORRENTS PL] Elevation 2024 1080p", "Elevation.2024.mkv")
        assert info is not None
        assert "Elevation" in info["title"]
        assert "DEVIL" not in info["title"]

    def test_year_extracted(self):
        info = sg._parse_info("Oppenheimer.2023.2160p.UHD", "Oppenheimer.2023.mkv")
        assert info is not None
        assert info.get("year") == 2023


class TestStrmPath:
    def test_movie_path(self):
        p = sg._strm_path({"type": "movie", "title": "Civil War", "year": 2024})
        assert p.suffix == ".strm"
        assert "Civil War (2024)" in str(p)
        assert "movies" in str(p)

    def test_movie_path_no_year(self):
        p = sg._strm_path({"type": "movie", "title": "Untitled", "year": None})
        assert "Untitled" in str(p)
        assert p.suffix == ".strm"

    def test_episode_path(self):
        p = sg._strm_path({"type": "episode", "title": "Severance", "season": 2, "episode": 1})
        assert p.suffix == ".strm"
        assert "Season 02" in str(p)
        assert "S02E01" in str(p)
        assert "series" in str(p)

    def test_episode_path_double_digit(self):
        p = sg._strm_path({"type": "episode", "title": "The Bear", "season": 1, "episode": 10})
        assert "S01E10" in str(p)


class TestScanTorboxLibrary:
    """scan_torbox_library() backfills .strm files for torrents TorBox already
    has cached that we have no virtual_item record of (e.g. after a DB reset)."""

    def test_imports_unknown_ready_torrent_with_tmdb_title(self, tmp_path, monkeypatch):
        import tmdb as real_tmdb
        monkeypatch.setattr(sg, "MEDIA_PATH", str(tmp_path))
        monkeypatch.setattr(sg.settings, "get", lambda key, default=None: False)  # CATBOX_MODE off
        monkeypatch.setattr(sg, "_resolve_url", lambda *a, **kw: "http://cdn.example/x")
        monkeypatch.setattr(sg.db, "get_virtual_item_by_hash", lambda info_hash: None)
        monkeypatch.setattr(real_tmdb, "search_movie", lambda title, year=None: "tt0110912")
        monkeypatch.setattr(real_tmdb, "display_title", lambda imdb_id, media_type: "Pulp Fiction (1994)")

        item = {
            "id": 1, "name": "Pulp.Fiction.1994.1080p.WEB-DL", "hash": "a" * 40,
            "files": [{"id": 1, "name": "Pulp.Fiction.1994.1080p.WEB-DL.mkv"}],
        }
        sg.torbox_mod.list_torrents = lambda force_refresh=True: [item]
        sg.torbox_mod._is_ready = lambda item: True
        sg.torbox_mod.find_by_id = lambda torrent_id: item

        result = sg.scan_torbox_library()
        assert result == {"scanned": 1, "imported": 1, "skipped": 0, "failed": 0}
        path = Path(tmp_path) / "movies" / "Pulp Fiction (1994)" / "Pulp Fiction (1994).strm"
        assert path.exists()

    def test_skips_torrent_already_known(self, monkeypatch):
        monkeypatch.setattr(sg.db, "get_virtual_item_by_hash", lambda info_hash: {"token": "existing"})
        item = {"id": 2, "name": "Known.Movie.2020", "hash": "b" * 40, "files": []}
        sg.torbox_mod.list_torrents = lambda force_refresh=True: [item]
        sg.torbox_mod._is_ready = lambda item: True

        result = sg.scan_torbox_library()
        assert result == {"scanned": 1, "imported": 0, "skipped": 1, "failed": 0}

    def test_skips_not_ready_torrents(self, monkeypatch):
        item = {"id": 3, "name": "Still.Downloading.2020", "hash": "c" * 40, "files": []}
        sg.torbox_mod.list_torrents = lambda force_refresh=True: [item]
        sg.torbox_mod._is_ready = lambda item: False

        result = sg.scan_torbox_library()
        assert result == {"scanned": 0, "imported": 0, "skipped": 0, "failed": 0}


class TestProcessTorrentCanonicalTitle:
    """A canonical_title/imdb_id lets a fresh torrent add land in the same
    series folder every time instead of re-deriving a (possibly different)
    folder name from each torrent's own raw release name  -  the cause of a
    show ending up split across several duplicate library entries."""

    def test_uses_canonical_title_and_writes_tvshow_nfo(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sg, "MEDIA_PATH", str(tmp_path))
        monkeypatch.setattr(sg.torbox_mod, "_is_ready", lambda item: True)
        monkeypatch.setattr(sg.settings, "get", lambda key, default=None: False)  # CATBOX_MODE off
        monkeypatch.setattr(sg, "_resolve_url", lambda *a, **kw: "http://cdn.example/x")
        item = {
            "id": 1,
            "name": "Full.House.S02.1080p.WEB-DL",
            "hash": "a" * 40,
            "files": [{"id": 1, "name": "Full.House.S02E01.mkv"}],
        }
        written = sg.process_torrent(item, canonical_title="Full House", imdb_id="tt0092359")
        assert written == 1
        folder = Path(tmp_path) / "series" / "Full House"
        assert (folder / "Season 02" / "Full House S02E01.strm").exists()
        nfo = folder / "tvshow.nfo"
        assert nfo.exists()
        assert "tt0092359" in nfo.read_text()

    def test_two_differently_named_torrents_land_in_same_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sg, "MEDIA_PATH", str(tmp_path))
        monkeypatch.setattr(sg.torbox_mod, "_is_ready", lambda item: True)
        monkeypatch.setattr(sg.settings, "get", lambda key, default=None: False)
        monkeypatch.setattr(sg, "_resolve_url", lambda *a, **kw: "http://cdn.example/x")
        item1 = {
            "id": 1, "name": "Full.House.S01.1080p.WEB-DL", "hash": "a" * 40,
            "files": [{"id": 1, "name": "Full.House.S01E01.mkv"}],
        }
        item2 = {
            "id": 2, "name": "[SITE] FULL HOUSE S02 COMPLETE", "hash": "b" * 40,
            "files": [{"id": 2, "name": "Full House S02E01.mkv"}],
        }
        sg.process_torrent(item1, canonical_title="Full House", imdb_id="tt0092359")
        sg.process_torrent(item2, canonical_title="Full House", imdb_id="tt0092359")
        series_dir = Path(tmp_path) / "series"
        show_folders = [p for p in series_dir.iterdir() if p.is_dir()]
        assert [p.name for p in show_folders] == ["Full House"]


class TestNormTitle:
    def test_strips_year(self):
        assert sg._norm_title("The Dark Knight (2008)") == sg._norm_title("dark knight (2008)")

    def test_strips_leading_the(self):
        assert sg._norm_title("The Matrix") == "matrix"

    def test_strips_leading_a(self):
        assert sg._norm_title("A Beautiful Mind (2001)") == "beautifulmind"

    def test_alphanumeric_only(self):
        result = sg._norm_title("Spider-Man: No Way Home (2021)")
        assert result == "spidermannowayhome"

    def test_case_insensitive(self):
        assert sg._norm_title("DUNE") == sg._norm_title("dune")


class TestCleanTorrentName:
    def test_strips_bracket_prefix(self):
        result = sg._clean_torrent_name("[RARBG] Elevation 2024 1080p")
        assert "RARBG" not in result
        assert "Elevation" in result

    def test_keeps_title_intact(self):
        result = sg._clean_torrent_name("Civil.War.2024.1080p.WEB-DL")
        assert "Civil" in result

    def test_strips_rutor_prefix(self):
        result = sg._clean_torrent_name("rutor.info Civil War 2024")
        assert "rutor" not in result.lower()


class TestStripJunk:
    def test_removes_quality_tags(self):
        result = sg._strip_junk("Civil War 2024 1080p WEB-DL EAC3 x264")
        assert "1080p" not in result
        assert "WEB-DL" not in result

    def test_preserves_title_and_year(self):
        result = sg._strip_junk("Elevation 2024 1080p WEB-DL")
        assert "Elevation" in result
        assert "2024" in result

    def test_removes_4k_tags(self):
        result = sg._strip_junk("Oppenheimer 2023 2160p UHD HEVC")
        assert "2160p" not in result
        assert "HEVC" not in result


# =============================================================================
# Plex Spore
# =============================================================================

class TestMakeStubMkv:
    def test_returns_bytes(self):
        data = sg.make_stub_mkv("Test Movie", quality="1080p")
        assert isinstance(data, bytes)
        assert len(data) > 100

    def test_ebml_magic_header(self):
        data = sg.make_stub_mkv("Test Movie", quality="1080p")
        # EBML magic: 0x1A 0x45 0xDF 0xA3
        assert data[:4] == b'\x1a\x45\xdf\xa3'

    def test_video_codec_matches_quality(self):
        # Stub video codec moet overeenkomen met de CDN-codec zodat Direct Stream
        # clients (Linux HTPC etc.) geen codec mismatch krijgen van Plex.
        data_4k = sg.make_stub_mkv("Test", quality="2160p")
        assert b"V_MPEGH/ISO/HEVC" in data_4k, "HEVC verwacht voor 2160p"
        assert b"V_VP8" not in data_4k

        data_1080 = sg.make_stub_mkv("Test", quality="1080p")
        assert b"V_MPEG4/ISO/AVC" in data_1080, "H264 verwacht voor 1080p"
        assert b"V_VP8" not in data_1080

        data_720 = sg.make_stub_mkv("Test", quality="720p")
        assert b"V_MPEG4/ISO/AVC" in data_720, "H264 verwacht voor 720p"

    def test_eac3_audio_placeholder(self):
        data = sg.make_stub_mkv("Test", quality="1080p")
        assert b"A_EAC3" in data
        assert b"A_PCM/INT/LIT" not in data


class TestWriteSporeStubs:
    def test_creates_mkv_and_minfo(self, tmp_path, monkeypatch):
        media_root = tmp_path / "media"
        spore_root = tmp_path / "plex-media"
        monkeypatch.setattr(sg, "MEDIA_PATH", str(media_root))
        monkeypatch.setattr(sg, "SPORE_MEDIA_PATH", str(spore_root))
        sg.settings.get.return_value = True

        strm_path = media_root / "movies" / "Elevation (2024)" / "Elevation (2024).strm"
        sg._write_spore_stubs(strm_path, token="abc123", title="Elevation",
                              quality="1080p", size_gb=5.2)

        stub_dir = spore_root / "movies" / "Elevation (2024)"
        assert (stub_dir / "Elevation (2024).mkv").exists(), ".mkv niet aangemaakt"
        minfo = (stub_dir / "Elevation (2024).minfo").read_text()
        assert "token=abc123" in minfo
        assert "size=" in minfo

    def test_minfo_size_in_bytes(self, tmp_path, monkeypatch):
        media_root = tmp_path / "media"
        spore_root = tmp_path / "plex-media"
        monkeypatch.setattr(sg, "MEDIA_PATH", str(media_root))
        monkeypatch.setattr(sg, "SPORE_MEDIA_PATH", str(spore_root))
        sg.settings.get.return_value = True

        strm_path = media_root / "movies" / "Film (2024)" / "Film (2024).strm"
        sg._write_spore_stubs(strm_path, token="tok1", title="Film", quality="2160p", size_gb=10.0)

        minfo = (spore_root / "movies" / "Film (2024)" / "Film (2024).minfo").read_text()
        assert "size=10000000000" in minfo

    def test_skips_if_both_exist(self, tmp_path, monkeypatch):
        media_root = tmp_path / "media"
        spore_root = tmp_path / "plex-media"
        monkeypatch.setattr(sg, "MEDIA_PATH", str(media_root))
        monkeypatch.setattr(sg, "SPORE_MEDIA_PATH", str(spore_root))
        sg.settings.get.return_value = True

        strm_path = media_root / "movies" / "Elevation (2024)" / "Elevation (2024).strm"
        stub_dir = spore_root / "movies" / "Elevation (2024)"
        stub_dir.mkdir(parents=True)
        (stub_dir / "Elevation (2024).mkv").write_bytes(b"existing")
        (stub_dir / "Elevation (2024).minfo").write_text("token=old\n")

        sg._write_spore_stubs(strm_path, token="new", title="Elevation",
                              quality="1080p", size_gb=1.0)

        # Moet NIET overschreven zijn
        assert (stub_dir / "Elevation (2024).minfo").read_text() == "token=old\n"

    def test_skips_when_spore_disabled(self, tmp_path, monkeypatch):
        media_root = tmp_path / "media"
        spore_root = tmp_path / "plex-media"
        monkeypatch.setattr(sg, "MEDIA_PATH", str(media_root))
        monkeypatch.setattr(sg, "SPORE_MEDIA_PATH", str(spore_root))
        sg.settings.get.return_value = False  # spore disabled

        strm_path = media_root / "movies" / "Film (2024)" / "Film (2024).strm"
        sg._write_spore_stubs(strm_path, token="x", title="Film", quality="1080p", size_gb=1.0)

        assert not (spore_root / "movies").exists(), "Spore dir aangemaakt terwijl disabled"


# =============================================================================
# Jellyfin .strm
# =============================================================================

class TestWriteStrm:
    def test_creates_file_with_url(self, tmp_path):
        path = tmp_path / "movies" / "Elevation (2024)" / "Elevation (2024).strm"
        result = sg._write_strm(path, "http://localhost/stream/abc")
        assert result is True
        assert path.read_text() == "http://localhost/stream/abc"

    def test_skips_if_already_exists(self, tmp_path):
        path = tmp_path / "movies" / "Elevation (2024)" / "Elevation (2024).strm"
        path.parent.mkdir(parents=True)
        path.write_text("http://old")
        result = sg._write_strm(path, "http://new")
        assert result is False
        assert path.read_text() == "http://old"

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "movies" / "Deep Nested" / "film.strm"
        sg._write_strm(path, "http://x")
        assert path.exists()

    def test_skips_normalized_duplicate(self, tmp_path):
        """Schrijft niet als een sibling-map dezelfde genormaliseerde titel heeft."""
        movies = tmp_path / "movies"
        existing = movies / "The Dark Knight (2008)"
        existing.mkdir(parents=True)
        (existing / "The Dark Knight (2008).strm").write_text("http://existing")

        # "dark knight (2008)" normaliseert naar "darkknight" -- zelfde als "The Dark Knight (2008)"
        dup = movies / "dark knight (2008)" / "dark knight (2008).strm"
        result = sg._write_strm(dup, "http://dup")
        assert result is False
        assert not dup.exists()

    def test_no_false_positive_different_titles(self, tmp_path):
        """Twee films met andere titel mogen beiden aangemaakt worden."""
        movies = tmp_path / "movies"
        first = movies / "Dune (2021)" / "Dune (2021).strm"
        second = movies / "Dune Part Two (2024)" / "Dune Part Two (2024).strm"
        assert sg._write_strm(first, "http://dune1") is True
        assert sg._write_strm(second, "http://dune2") is True
        assert first.exists()
        assert second.exists()


# ── tvshow.nfo title (Jellyfin showed "Season 01" for every series) ───────────

def _read_title(nfo_path):
    import xml.etree.ElementTree as ET
    return ET.parse(nfo_path).getroot().findtext("title")


def test_tvshow_nfo_gets_the_series_name_not_the_season_folder(tmp_path):
    """_write_nfo derived the title from strm_path.parent.name. For an episode
    that parent is the SEASON folder, so every tvshow.nfo written from an
    episode said "Season 01" and Jellyfin displayed that as the show's name.
    """
    import strm_generator as sg
    series = tmp_path / "series" / "Reacher (2022)"
    season = series / "Season 01"
    season.mkdir(parents=True)
    strm = season / "Reacher (2022) S01E01.strm"
    strm.write_text("http://x")

    sg._write_nfo(strm, "tt9288030", nfo_path=series / "tvshow.nfo", media_type="series")

    assert _read_title(series / "tvshow.nfo") == "Reacher"


def test_tvshow_nfo_keeps_a_show_whose_name_starts_with_season(tmp_path):
    """Guard against 'fixing' this by string-matching the title."""
    import strm_generator as sg
    series = tmp_path / "series" / "Seasons of Love (2019)"
    season = series / "Season 02"
    season.mkdir(parents=True)
    strm = season / "Seasons of Love (2019) S02E03.strm"
    strm.write_text("http://x")

    sg._write_nfo(strm, "tt1234567", nfo_path=series / "tvshow.nfo", media_type="series")

    assert _read_title(series / "tvshow.nfo") == "Seasons of Love"


def test_movie_nfo_title_is_unchanged(tmp_path):
    """The movie path always sat next to its own folder, so it was correct.
    The fix must not disturb it."""
    import strm_generator as sg
    folder = tmp_path / "movies" / "Dune (2021)"
    folder.mkdir(parents=True)
    strm = folder / "Dune (2021).strm"
    strm.write_text("http://x")

    sg._write_nfo(strm, "tt1160419", media_type="movie")

    nfo = folder / "Dune (2021).nfo"
    assert _read_title(nfo) == "Dune"
    import xml.etree.ElementTree as ET
    assert ET.parse(nfo).getroot().findtext("year") == "2021"
