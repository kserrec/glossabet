"""Shared completeness accounting for bounded collections.

Every bounded collection uses the same ledger shape.  ``total_items`` is the
number of findings/candidates actually known; ``total_items_exact`` says
whether that number covers every accepted input.  This distinction lets a
consumer report an exact number of details it found while remaining honest
about upstream evidence that was not evaluated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TypedDict, TypeVar

T = TypeVar("T")


class CoverageLedger(TypedDict):
    """The persisted completeness ledger every bounded collection carries."""

    total_items: int
    included_items: int
    dropped_items: int
    total_items_exact: bool
    complete: bool
    reasons: list[str]


class CappedSection(TypedDict):
    """``{items, dropped_items, coverage}`` — a capped list in an artifact."""

    items: list[object]
    dropped_items: int
    coverage: CoverageLedger


class LocationSample(TypedDict):
    """One ``{path, count}`` record of a location sample."""

    path: str
    count: int


def _reasons(values: Iterable[str]) -> list[str]:
    """Return stable, de-duplicated non-empty reasons."""
    return list(dict.fromkeys(value for value in values if value))


def coverage_ledger(
    total_items: int,
    included_items: int,
    *,
    total_items_exact: bool = True,
    reasons: Iterable[str] = (),
) -> CoverageLedger:
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
    items: Sequence[T],
    cap: int,
    *,
    cap_reason: str,
    total_items: int | None = None,
    total_items_exact: bool = True,
    incomplete_reasons: Iterable[str] = (),
) -> tuple[list[T], CoverageLedger]:
    """Keep a deterministic prefix and return its shared coverage ledger.

    This is the one way to "cap this list and say so": the ledger's reasons
    are the caller's upstream ``incomplete_reasons`` followed by
    ``cap_reason`` whenever anything was left out. ``total_items`` defaults
    to ``len(items)``; pass a larger known total when the producer stopped
    collecting detail early.
    """
    if cap < 0:
        raise ValueError("collection cap must be non-negative")
    kept = list(items[:cap])
    if total_items is None:
        total_items = len(items)
    reasons = list(incomplete_reasons)
    if total_items > len(kept):
        reasons.append(cap_reason)
    return kept, coverage_ledger(
        total_items,
        len(kept),
        total_items_exact=total_items_exact,
        reasons=reasons,
    )


def location_sample(
    per_file: Mapping[str, int], cap: int
) -> tuple[list[LocationSample], bool]:
    """The top-``cap`` (path, count) locations by (-count, path) as
    ``{"path", "count"}`` records, and whether any were left out."""
    ranked = sorted(per_file.items(), key=lambda item: (-item[1], item[0]))
    kept = ranked[:cap]
    return (
        [{"path": path, "count": count} for path, count in kept],
        len(ranked) > len(kept),
    )


def capped_section(
    items: Sequence[object],
    cap: int,
    *,
    cap_reason: str,
    total_items: int | None = None,
    total_items_exact: bool = True,
    incomplete_reasons: Iterable[str] = (),
) -> CappedSection:
    """``{items, dropped_items, coverage}`` — the section shape every
    capped list in an artifact takes — from ``capped_collection``."""
    kept, coverage = capped_collection(
        items,
        cap,
        cap_reason=cap_reason,
        total_items=total_items,
        total_items_exact=total_items_exact,
        incomplete_reasons=incomplete_reasons,
    )
    return {
        "items": kept,
        "dropped_items": coverage["dropped_items"],
        "coverage": coverage,
    }


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
