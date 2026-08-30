"""repair_tvshow_titles() never repaired anything.

    title_el = root.find("title")
    if not title_el or not title_el.text:
        continue

An ElementTree Element's truth value is its CHILD COUNT, not whether it was
found. <title>Season 01</title> has no child elements, so `not title_el` was
True for every file and the loop skipped all of them. The function returned
{"fixed": 0} no matter what the library contained, which is why the button
appeared to do nothing.
"""
import os
import sys
import xml.etree.ElementTree as ET

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import nfo_generator as ng


def _nfo(path, title, imdb="tt5551234", root_tag="tvshow"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<{root_tag}>\n  <title>{title}</title>\n'
        f'  <uniqueid type="imdb" default="true">{imdb}</uniqueid>\n</{root_tag}>\n',
        encoding="utf-8")


def _title(path):
    return ET.parse(path).getroot().findtext("title")


@pytest.fixture
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(ng, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(ng.db, "get_all_monitored_series", lambda: [])
    return tmp_path


def test_a_season_title_is_actually_rewritten(media):
    nfo = media / "series" / "Reacher (2022)" / "tvshow.nfo"
    _nfo(nfo, "Season 01")

    result = ng.repair_tvshow_titles()

    assert result["fixed"] == 1, f"nothing was repaired: {result}"
    assert _title(nfo) == "Reacher (2022)"


def test_the_canonical_db_title_wins_over_the_folder_name(media, monkeypatch):
    monkeypatch.setattr(ng.db, "get_all_monitored_series",
                        lambda: [{"imdb_id": "tt5551234", "title": "Reacher"}])
    nfo = media / "series" / "Reacher (2022)" / "tvshow.nfo"
    _nfo(nfo, "Season 07")

    ng.repair_tvshow_titles()

    assert _title(nfo) == "Reacher"


def test_a_correct_title_is_left_alone(media):
    nfo = media / "series" / "Lioness (2023)" / "tvshow.nfo"
    _nfo(nfo, "Lioness")

    result = ng.repair_tvshow_titles()

    assert result["fixed"] == 0
    assert _title(nfo) == "Lioness"


def test_a_show_genuinely_named_season_something_is_left_alone(media):
    """The pattern is anchored, so only a bare "Season NN" counts."""
    nfo = media / "series" / "Season of the Witch (2011)" / "tvshow.nfo"
    _nfo(nfo, "Season of the Witch")

    ng.repair_tvshow_titles()

    assert _title(nfo) == "Season of the Witch"


def test_a_bad_title_without_an_imdb_id_is_reported_not_guessed(media):
    nfo = media / "series" / "Mystery (2020)" / "tvshow.nfo"
    nfo.parent.mkdir(parents=True, exist_ok=True)
    nfo.write_text('<?xml version="1.0"?>\n<tvshow>\n  <title>Season 01</title>\n</tvshow>\n',
                   encoding="utf-8")

    result = ng.repair_tvshow_titles()

    assert result["skipped"] == 1
    assert result["fixed"] == 0


# ── movies (the bug could not reach them, but the repair should still look) ───

def test_a_movie_nfo_with_a_season_title_is_repaired(media):
    """No known path produces this - a movie's NFO sits in the movie's own
    folder, so its title was always correct. Checked anyway, because a repair
    that inspects half the library cannot report the other half is clean.
    """
    nfo = media / "movies" / "Dune (2021)" / "Dune (2021).nfo"
    _nfo(nfo, "Season 01", imdb="tt1160419", root_tag="movie")

    result = ng.repair_tvshow_titles()

    assert result["fixed"] == 1
    assert _title(nfo) == "Dune (2021)"


def test_a_repaired_movie_keeps_the_movie_shape_and_its_year(media):
    """Writing a <tvshow> document over a movie would break Jellyfin matching."""
    nfo = media / "movies" / "Dune (2021)" / "Dune (2021).nfo"
    _nfo(nfo, "Season 03", imdb="tt1160419", root_tag="movie")

    ng.repair_tvshow_titles()

    root = ET.parse(nfo).getroot()
    assert root.tag == "movie", "a movie must not be rewritten as a tvshow"
    assert root.findtext("year") == "2021"


def test_a_normal_movie_title_is_untouched(media):
    nfo = media / "movies" / "Dune (2021)" / "Dune (2021).nfo"
    _nfo(nfo, "Dune", imdb="tt1160419", root_tag="movie")

    result = ng.repair_tvshow_titles()

    assert result["fixed"] == 0
    assert _title(nfo) == "Dune"


def test_series_and_movies_are_both_counted(media):
    _nfo(media / "series" / "Reacher (2022)" / "tvshow.nfo", "Season 01", imdb="tt1")
    _nfo(media / "movies" / "Dune (2021)" / "Dune (2021).nfo", "Season 01",
         imdb="tt2", root_tag="movie")

    result = ng.repair_tvshow_titles()

    assert result["fixed"] == 2
