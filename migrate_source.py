"""One-shot backfill: virtual_items.source and requests.source used to hold
the winning scraper's name (torrentio, zilean, ...). Since the source column
was redefined to mean a release-source label (WEB-DL, BluRay, REMUX, ...,
see release_tags.source_label), new writes already carry the new meaning;
this migration re-derives a label for rows written before that change.

Runs once, guarded by MIGRATION_MARKER, for the same reason migrate_filters
is guarded: without it, every startup would re-derive labels and could
clobber a source a later swap or upgrade has already written correctly.

settings and db are imported lazily, matching migrate_filters.py: some
tests pop these modules out of sys.modules to force a reload, and a
module-level import here would keep pointing at the stale pre-pop object.
"""
import logging

log = logging.getLogger(__name__)

MIGRATION_MARKER = "SOURCE_LABELS_MIGRATED"


def migrate(dry_run: bool = False, force: bool = False) -> dict:
    """Re-derive virtual_items.source and requests.source as a release-source
    label instead of a scraper name.

    virtual_items has no column holding the original scene release name,
    only the sanitised display `title` (a movie folder like "Movie Name
    (2024)", or an episode's "Show S01E02"); release_tags.detect_sources()
    usually finds no source tag on text that clean, so most existing rows
    are left untouched. That is expected, not a bug in this migration: the
    tag simply was never stored anywhere for older rows.

    requests has no release-name column at all (its title is the request's
    title, not a release name); its source is instead derived from its own
    movie virtual_item's title, when one exists, on the same basis. Series
    requests have no single virtual_item to fall back to (one row per
    episode), so a series row is left alone unless its own title happens to
    carry a source tag.

    A row that yields no label keeps whatever source value it already had,
    UNLESS that value is itself one of the scraper names this column used to
    hold (torrentio, zilean, ...; from scrapers._SCRAPERS): a scraper name
    left in a column that now means a release-source label is a wrong value,
    not a harmless old one, so that row's source is blanked to NULL instead.
    Anything else already there (a label, empty, NULL, some other string) is
    left untouched.
    """
    import db
    import release_tags
    import scrapers
    import settings as _settings

    if not force and _settings.get(MIGRATION_MARKER, False):
        log.debug("Source labels already migrated; skipping")
        return {}

    scraper_names = {name.lower() for name, _key, _fn in scrapers._SCRAPERS}

    vi_updated = vi_unchanged = vi_blanked = 0
    req_updated = req_unchanged = req_blanked = 0

    with db._connect() as conn:
        vi_rows = conn.execute(
            "SELECT token, imdb_id, media_type, title, source FROM virtual_items"
        ).fetchall()

        # A movie virtual_item's derived label, by imdb_id, used below as the
        # fallback for a request row that has nothing of its own to derive
        # from. Keeps the first label found per imdb_id; there is normally
        # only one movie virtual_item per imdb_id anyway.
        movie_label_by_imdb: dict[str, str] = {}

        for row in vi_rows:
            label = release_tags.source_label(row["title"] or "")
            if label:
                if not dry_run:
                    conn.execute("UPDATE virtual_items SET source=? WHERE token=?", (label, row["token"]))
                vi_updated += 1
                if row["media_type"] == "movie" and row["imdb_id"] and row["imdb_id"] not in movie_label_by_imdb:
                    movie_label_by_imdb[row["imdb_id"]] = label
            elif (row["source"] or "").lower() in scraper_names:
                if not dry_run:
                    conn.execute("UPDATE virtual_items SET source=NULL WHERE token=?", (row["token"],))
                vi_blanked += 1
            else:
                vi_unchanged += 1

        req_rows = conn.execute("SELECT id, imdb_id, title, source FROM requests").fetchall()
        for row in req_rows:
            label = release_tags.source_label(row["title"] or "") or movie_label_by_imdb.get(row["imdb_id"])
            if label:
                if not dry_run:
                    conn.execute("UPDATE requests SET source=? WHERE id=?", (label, row["id"]))
                req_updated += 1
            elif (row["source"] or "").lower() in scraper_names:
                if not dry_run:
                    conn.execute("UPDATE requests SET source=NULL WHERE id=?", (row["id"],))
                req_blanked += 1
            else:
                req_unchanged += 1

        if not dry_run:
            conn.commit()

    if not dry_run:
        _settings.set(MIGRATION_MARKER, True)

    log.info(
        "Source label migration: virtual_items %d labelled / %d blanked / %d unchanged, "
        "requests %d labelled / %d blanked / %d unchanged",
        vi_updated, vi_blanked, vi_unchanged, req_updated, req_blanked, req_unchanged,
    )
    return {
        "virtual_items_updated": vi_updated, "virtual_items_blanked": vi_blanked,
        "virtual_items_unchanged": vi_unchanged,
        "requests_updated": req_updated, "requests_blanked": req_blanked,
        "requests_unchanged": req_unchanged,
    }
