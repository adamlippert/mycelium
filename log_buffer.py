import logging
from collections import deque

_buffer: deque[str] = deque(maxlen=500)


class _BufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            _buffer.append(self.format(record))
        except Exception:
            pass


_handler = _BufferHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))


def install() -> None:
    logging.getLogger().addHandler(_handler)


def get_lines(n: int = 100) -> list[str]:
    lines = list(_buffer)
    return lines[-n:]


_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_LINE_RE = None


def get_structured(limit: int = 200, min_level: str | None = None) -> list[dict]:
    """Parsed view of the buffer for the admin Logs tab, newest last.

    Malformed lines (traceback continuations) carry level "" and pass every
    filter: hiding a traceback because it has no level would hide exactly
    what the reader came for.
    """
    global _LINE_RE
    import re
    if _LINE_RE is None:
        _LINE_RE = re.compile(
            r"^(\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2})),\d+ (\w+) \[([^\]]*)\] (.*)$"
        )
    threshold = _LEVEL_ORDER.get(min_level or "", 0)
    out = []
    for raw in list(_buffer):
        m = _LINE_RE.match(raw)
        if m:
            level = m.group(3)
            if _LEVEL_ORDER.get(level, 0) < threshold:
                continue
            out.append({"time": m.group(2), "level": level, "name": m.group(4), "msg": m.group(5)})
        else:
            out.append({"time": "", "level": "", "name": "", "msg": raw})
    return out[-max(1, min(int(limit), 1000)):]
