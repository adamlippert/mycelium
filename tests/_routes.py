"""Where a route lives now. Tests assert routes on source text; after the
blueprint split that text is in routes/<module>.py, and a later move costs
nothing here."""
import glob
import os
import re

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _candidates():
    return [os.path.join(_ROOT, "app.py")] + sorted(glob.glob(os.path.join(_ROOT, "routes", "*.py")))


def src_for_route(path: str) -> str:
    """The full source of the module whose decorator registers `path`.

    Matches the decorator line, not the path anywhere in the file: several
    routes carry their own path in a redirect or a log line, and one of
    those must never decide where the test looks."""
    decor = re.compile(r'^@(?:bp|app)\.(?:get|post|put|delete|route)\(\s*"'
                       + re.escape(path) + r'"', re.M)
    for p in _candidates():
        with open(p, encoding="utf-8") as f:
            text = f.read()
        if decor.search(text):
            return text
    raise KeyError(f"no module defines a route for {path}")


def all_route_sources() -> str:
    """app.py, appcore.py and every route module, concatenated. For the
    guards that make a claim about the whole surface ("no render_template
    anywhere") rather than about one route."""
    paths = _candidates() + [os.path.join(_ROOT, "appcore.py")]
    out = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            out.append(f.read())
    return "\n".join(out)
