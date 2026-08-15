"""Shared completeness accounting for bounded collections.

Every bounded collection uses the same ledger shape.  ``total_items`` is the
number of findings/candidates actually known; ``total_items_exact`` says
whether that number covers every accepted input.  This distinction lets a
consumer report an exact number of details it found while remaining honest
about upstream evidence that was not evaluated.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def _reasons(values: Iterable[str]) -> list[str]:
    """Return stable, de-duplicated non-empty reasons."""
    return list(dict.fromkeys(value for value in values if value))


def coverage_ledger(
    total_items: int,
    included_items: int,
    *,
    total_items_exact: bool = True,
    reasons: Iterable[str] = (),
) -> dict:
    """Describe how much of one collection is present in detail.

    ``dropped_items`` counts known items omitted from the detailed list.  When
    upstream work was omitted, callers keep the known lower-bound total and
    set ``total_items_exact`` false with a reason; unknown findings are never
    smuggled into a made-up dropped count.
    """
    if total_items < 0 or included_items < 0 or included_items > total_items:
        raise ValueError("invalid collection coverage counts")
    normalized_reasons = _reasons(reasons)
    dropped_items = total_items - included_items
    return {
        "total_items": total_items,
        "included_items": included_items,
        "dropped_items": dropped_items,
        "total_items_exact": bool(total_items_exact),
        "complete": (
            total_items_exact
            and dropped_items == 0
            and not normalized_reasons
        ),
        "reasons": normalized_reasons,
    }


def capped_collection(
    items: Sequence,
    cap: int,
    *,
    cap_reason: str,
    total_items_exact: bool = True,
    incomplete_reasons: Iterable[str] = (),
) -> tuple[list, dict]:
    """Keep a deterministic prefix and return its shared coverage ledger."""
    if cap < 0:
        raise ValueError("collection cap must be non-negative")
    kept = list(items[:cap])
    reasons = list(incomplete_reasons)
    if len(items) > cap:
        reasons.append(cap_reason)
    return kept, coverage_ledger(
        len(items),
        len(kept),
        total_items_exact=total_items_exact,
        reasons=reasons,
    )


def coverage_reasons(ledger: object, prefix: str = "") -> list[str]:
    """Extract honest incompleteness reasons from a possibly older artifact."""
    if not isinstance(ledger, dict) or ledger.get("complete") is True:
        return []
    reasons = ledger.get("reasons")
    if isinstance(reasons, list):
        clean = [reason for reason in reasons if isinstance(reason, str) and reason]
    else:
        clean = []
    if not clean:
        clean = ["coverage metadata reports an incomplete collection"]
    if prefix:
        return [f"{prefix}: {reason}" for reason in clean]
    return clean
