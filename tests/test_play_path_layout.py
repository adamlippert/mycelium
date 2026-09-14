"""The play path stays readable: the two functions a play goes through are
short enough to hold in your head, and the pieces they delegate to live in
the same module (the monkeypatch seams the play-path tests use depend on
that). Source-text only: routes/ is never imported by a test."""
import ast
import os

_ROOT = os.path.join(os.path.dirname(__file__), "..")

_MAX_LINES = 120


def _functions(relpath):
    """{name: node} for the module's top-level functions, parsed not imported."""
    src = open(os.path.join(_ROOT, relpath), encoding="utf-8").read()
    return {n.name: n for n in ast.parse(src).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _length(relpath, name):
    fn = _functions(relpath)[name]
    return fn.end_lineno - fn.lineno + 1


def test_materialize_locked_reads_as_its_four_steps():
    assert _length("catbox.py", "_materialize_locked") < _MAX_LINES


def test_prepare_stream_reads_as_its_three_outcomes():
    assert _length("routes/stream.py", "_prepare_stream") < _MAX_LINES


def test_the_materialize_helpers_live_next_to_the_function_that_calls_them():
    """Not in catbox_jobs or catbox_packs: those import catbox, and a helper
    moved there would put the play path behind an import cycle."""
    names = _functions("catbox.py")
    for name in ("_materialize_realdebrid", "_acquire_torbox", "_resolve_file_id"):
        assert name in names, f"{name} must be a top-level function in catbox.py"


def test_the_stream_helpers_live_next_to_the_function_that_calls_them():
    names = _functions("routes/stream.py")
    for name in ("_prepare_cold", "_prepare_fast", "_prepare_warm"):
        assert name in names, f"{name} must be a top-level function in routes/stream.py"
