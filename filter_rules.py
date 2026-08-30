"""The four-state filter model.

Every category is evaluated against the full candidate pool, independently, and
the resulting drops are applied together. That is what makes the outcome
independent of category order, unlike the sequential chain it replaces, where
each filter rebound the candidate list before the next one ran.
"""
import logging
from dataclasses import dataclass

import release_tags as rt
import settings as _settings

log = logging.getLogger(__name__)

_STATES = ("preferred", "excluded", "required", "included")

_PREFIX_BY_CATEGORY = {
    "resolution": "RESOLUTION",
    "source": "SOURCE",
    "encode": "ENCODE",
    "visual_tag": "VISUAL_TAG",
    "audio_tag": "AUDIO_TAG",
    "audio_channels": "AUDIO_CHANNELS",
    "language": "LANGUAGE",
}


@dataclass(frozen=True)
class Verdict:
    kept: bool
    rule: str | None = None      # "SOURCE_EXCLUDED", "AUDIO_TAG_INCLUDED", ...
    value: str | None = None     # the value that matched
    relaxed: bool = False        # this rule self-disabled to avoid an empty pool


def load_rules() -> dict[str, dict]:
    """Read the 35 settings into the nested shape evaluate() expects."""
    rules = {}
    for category, prefix in _PREFIX_BY_CATEGORY.items():
        rules[category] = {
            state: [v.strip().lower()
                    for v in (_settings.get(f"{prefix}_{state.upper()}", []) or [])]
            for state in _STATES
        }
        rules[category]["strict"] = bool(_settings.get(f"{prefix}_STRICT", False))
    return rules


def _included_match(tags: dict, rules: dict) -> tuple[str, str] | None:
    """Included is checked first, across every category, and short-circuits.

    It is deliberately powerful: marking atmos as included will keep a cam rip
    that happens to carry Atmos. The UI must say so at the point of choosing.
    """
    for category in rt.CATEGORIES:
        included = rules.get(category, {}).get("included") or []
        for value in tags.get(category, ()):
            if value in included:
                return f"{_PREFIX_BY_CATEGORY[category]}_INCLUDED", value
    return None


def _category_drop(tags: dict, category: str, rules: dict) -> tuple[str, str] | None:
    """Return the rule and value that would drop this candidate, or None.

    A required rule never drops an UNKNOWN. "The release did not say" is not
    "the release does not match", and treating it as a mismatch would delete
    every result from a source that cannot supply this category at all.
    """
    prefix = _PREFIX_BY_CATEGORY[category]
    values = tags.get(category, ())
    spec = rules.get(category, {})

    required = spec.get("required") or []
    if required and not any(v in required for v in values):
        if rt.UNKNOWN not in values:
            return f"{prefix}_REQUIRED", ",".join(values) or rt.UNKNOWN

    excluded = spec.get("excluded") or []
    for value in values:
        if value in excluded:
            return f"{prefix}_EXCLUDED", value
    return None


def evaluate(tagged: list[dict], rules: dict) -> list[Verdict]:
    """One Verdict per candidate, in input order. Nothing is discarded silently.

    Each category votes against the full pool, independently, and the votes are
    unioned afterwards. No category ever sees a pool another category already
    shrank, which is what makes the outcome independent of category order.
    """
    if not tagged:
        return []

    # Included is checked first, across every category, and short-circuits.
    rescued: dict[int, tuple[str, str]] = {}
    for i, tags in enumerate(tagged):
        hit = _included_match(tags, rules)
        if hit:
            rescued[i] = hit

    # Every category votes against the FULL pool.
    votes: dict[str, dict[int, tuple[str, str]]] = {}
    for category in rt.CATEGORIES:
        category_votes = {}
        for i, tags in enumerate(tagged):
            if i in rescued:
                continue
            hit = _category_drop(tags, category, rules)
            if hit:
                category_votes[i] = hit
        votes[category] = category_votes

    def _union(categories) -> dict[int, tuple[str, str]]:
        merged: dict[int, tuple[str, str]] = {}
        for category in categories:
            for i, hit in votes[category].items():
                merged.setdefault(i, hit)
        return merged

    drops = _union(rt.CATEGORIES)
    relaxed_categories: set[str] = set()

    # Soft by default, assessed GLOBALLY. A per-category check misses the case
    # where two categories drop disjoint subsets that together empty the pool.
    if drops and len(drops) + len(rescued) >= len(tagged):
        strict = [c for c in rt.CATEGORIES if rules.get(c, {}).get("strict")]
        relaxed_categories = {c for c in rt.CATEGORIES
                              if c not in strict and votes[c]}
        for category in sorted(relaxed_categories):
            log.info("Filter %s would leave no candidates; relaxing it",
                     _PREFIX_BY_CATEGORY[category])
        drops = _union(strict)

    verdicts = []
    for i in range(len(tagged)):
        if i in rescued:
            rule, value = rescued[i]
            verdicts.append(Verdict(kept=True, rule=rule, value=value))
        elif i in drops:
            rule, value = drops[i]
            verdicts.append(Verdict(kept=False, rule=rule, value=value))
        else:
            # relaxed is precise: true only for a candidate that a relaxed
            # category actually voted against, not for every survivor.
            was_relaxed = any(i in votes[c] for c in relaxed_categories)
            verdicts.append(Verdict(kept=True, relaxed=was_relaxed))
    return verdicts
