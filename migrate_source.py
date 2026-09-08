"""One-shot backfill: virtual_items.source and requests.source used to hold
the winning scraper's name (torrentio, zilean, ...). Since the source column
was redefined to mean a release-source label (WEB-DL, BluRay, REMUX, ...,
see release_tags.source_label), new writes already carry the new meaning;
this migration only blanks rows written before that change, it does not try
to derive a label for them.

An earlier version of this migration also tried to derive a label from
virtual_items.title / requests.title. Both columns hold sanitised display
names ("Heat (1995)", "Loki S01E02"), never a release name, so a real match
was essentially never present; the rows it did label were near-certainly
coincidental word matches (e.g. "Web Therapy" -> WEB, "R5" as part of a
title). That derive step is gone: blanking a wrong value is safe, writing a
plausible-looking wrong one is not.

Runs once, guarded by MIGRATION_MARKER, for the same reason migrate_filters
is guarded: without it, every startup would re-scan every row for no
reason once the column is clean.

settings and db are imported lazily, matching migrate_filters.py: some
tests pop these modules out of sys.modules to force a reload, and a
module-level import here would keep pointing at the stale pre-pop object.
"""
import logging

log = logging.getLogger(__name__)

MIGRATION_MARKER = "SOURCE_LABELS_MIGRATED"


def migrate(dry_run: bool = False, force: bool = False) -> dict:
    """Blank virtual_items.source and requests.source where the stored value
    is a scraper name (torrentio, zilean, ...; from scrapers._SCRAPERS)
    rather than a release-source label.

    A scraper name left in a column that now means a release-source label is
    a wrong value, not a harmless old one, so it is set to NULL. Anything
    else already there (a label, empty, NULL, some other string) is left
    untouched.
    """
    import db
    import scrapers
    import settings as _settings

    if not force and _settings.get(MIGRATION_MARKER, False):
        log.debug("Source labels already migrated; skipping")
        return {}

    scraper_names = {name.lower() for name, _key, _fn in scrapers._SCRAPERS}

    vi_blanked = vi_unchanged = 0
    req_blanked = req_unchanged = 0

    with db._connect() as conn:
        vi_rows = conn.execute("SELECT token, source FROM virtual_items").fetchall()
        for row in vi_rows:
            if (row["source"] or "").lower() in scraper_names:
                if not dry_run:
                    conn.execute("UPDATE virtual_items SET source=NULL WHERE token=?", (row["token"],))
                vi_blanked += 1
            else:
                vi_unchanged += 1

        req_rows = conn.execute("SELECT id, source FROM requests").fetchall()
        for row in req_rows:
            if (row["source"] or "").lower() in scraper_names:
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
        "Source label migration: virtual_items %d blanked / %d unchanged, "
        "requests %d blanked / %d unchanged",
        vi_blanked, vi_unchanged, req_blanked, req_unchanged,
    )
    return {
        "virtual_items_blanked": vi_blanked, "virtual_items_unchanged": vi_unchanged,
        "requests_blanked": req_blanked, "requests_unchanged": req_unchanged,
    }
