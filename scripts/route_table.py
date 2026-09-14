"""The registered routes as (method, path) pairs, parsed from source so the
tests can compare without importing app.py. `--write` refreshes the
fixture, `--check` fails when the code and the fixture differ."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "route_table.json"
# re.S so a decorator that wraps its arguments over several lines (the
# methods=[...] list on its own line) is still one match.
DECOR = re.compile(
    r'^@(?:app|bp)\.(get|post|put|delete|route)\(\s*"([^"]+)"'
    r'(?:\s*,\s*methods=\[([^\]]*)\])?',
    re.M | re.S,
)


def parse(paths):
    pairs = set()
    for p in paths:
        src = Path(p).read_text(encoding="utf-8")
        for verb, path, methods in DECOR.findall(src):
            if verb == "route":
                for m in re.findall(r'"([A-Z]+)"', methods or '"GET"'):
                    pairs.add((m, path))
            else:
                pairs.add((verb.upper(), path))
    return sorted([list(x) for x in pairs])


def sources():
    out = [ROOT / "app.py"]
    out += sorted((ROOT / "routes").glob("*.py")) if (ROOT / "routes").is_dir() else []
    return [str(p) for p in out]


if __name__ == "__main__":
    table = parse(sources())
    if "--write" in sys.argv:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(table, indent=1) + "\n")
        print(f"wrote {len(table)} routes")
    else:
        stored = json.loads(FIXTURE.read_text())
        if stored != table:
            missing = [r for r in stored if r not in table]
            extra = [r for r in table if r not in stored]
            print("route table changed:", "missing", missing, "extra", extra)
            sys.exit(1)
        print(f"{len(table)} routes match")
