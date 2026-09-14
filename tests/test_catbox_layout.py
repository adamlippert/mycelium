"""catbox.py holds the play path; jobs and pack handling live in their own
modules. The re-exports exist for one release so the scheduler and the
overview keep their names; the docstring lists them."""
import os

import catbox
import catbox_jobs
import catbox_packs

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_modules_own_their_functions():
    assert {"release_idle", "reconcile_torbox_ids", "last_reconcile", "_account_lists"} <= set(dir(catbox_jobs))
    assert {"reconcile_pack_files", "detach_episode", "series_title", "_search_detached", "_start_detached_search"} <= set(dir(catbox_packs))
    for name in ("_resolve_pack_files", "_reconcile_pack", "_detach_episode", "_account_lists",
                 "reconcile_pack_files", "detach_episode", "series_title"):
        assert name not in catbox.__dict__, f"{name} moved out of catbox.py"


def test_re_exports_actually_delegate(monkeypatch):
    """A text-window check on the source can pass even when the wrapper
    body was replaced with `return 0` (the docstring alone mentions the
    jobs module). Prove delegation by swapping the real implementation and
    checking the sentinel comes back through the wrapper."""
    monkeypatch.setattr(catbox_jobs, "release_idle", lambda: 4242)
    assert catbox.release_idle() == 4242
    monkeypatch.setattr(catbox_jobs, "reconcile_torbox_ids", lambda: {"sentinel": 4242})
    assert catbox.reconcile_torbox_ids() == {"sentinel": 4242}
    monkeypatch.setattr(catbox_jobs, "last_reconcile", lambda: {"sentinel": 4242})
    assert catbox.last_reconcile() == {"sentinel": 4242}


def test_re_exports_are_listed_in_the_docstring():
    doc = catbox.__doc__ or ""
    for name in ("release_idle", "reconcile_torbox_ids", "last_reconcile"):
        assert name in doc, "re-export listed in the module docstring"


def test_no_import_cycle_at_module_level():
    src = open(os.path.join(_ROOT, "catbox.py")).read()
    top = src.split("\ndef ")[0]
    assert "import catbox_jobs" not in top and "import catbox_packs" not in top


def test_public_surface_other_modules_reach_is_still_on_catbox():
    """The exact surface app.py, release_swap.py, webdav.py,
    strm_generator.py, overview.py and spore_server.py use: the public
    re-exports (materialize, register, proxy_url, cache_url,
    invalidate_url_cache, catbox_host, release_idle, reconcile_torbox_ids,
    last_reconcile) plus the private members reached from outside
    (_fail_cache_lock, _fail_cache, _content_key, _token_lock, _pack_lock,
    _cache_get). Freezing it here catches an accidental rename or a member
    that moved out from under a caller."""
    public = ("materialize", "register", "proxy_url", "cache_url", "invalidate_url_cache",
              "catbox_host", "release_idle", "reconcile_torbox_ids", "last_reconcile")
    private = ("_fail_cache_lock", "_fail_cache", "_content_key", "_token_lock", "_pack_lock", "_cache_get")
    for name in public + private:
        assert hasattr(catbox, name), f"{name} must stay reachable as catbox.{name}"
    doc = catbox.__doc__ or ""
    for name in ("release_idle", "reconcile_torbox_ids", "last_reconcile"):
        assert name in doc, "the three job re-exports are listed in the catbox.py docstring"
