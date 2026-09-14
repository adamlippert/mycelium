"""Promised names on their way out. A name listed here still works for one
minor release and warns once at startup, naming its replacement; the next
minor release removes it. Empty at 1.0."""
import logging
import os

log = logging.getLogger(__name__)

DEPRECATED: dict[str, str] = {}


def warn_deprecated_env() -> list[str]:
    messages = []
    for old, new in DEPRECATED.items():
        if old in os.environ:
            messages.append(f"{old} is deprecated and will be removed in the next minor release; use {new}.")
    for m in messages:
        log.warning("%s", m)
    return messages
