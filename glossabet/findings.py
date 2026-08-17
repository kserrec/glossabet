"""The findings document: the shape drift and validation reports share.

Both checks emit *sections* of *findings*, each section carrying the common
coverage ledger, and both must translate RepositoryEvidence's own omissions
into "why this section may be incomplete" reasons before printing. This
module owns those three things once — the finding record (exactly one of
``certainty`` / ``signal_strength``, which is what the renderer keys on), the
capped section with its ledger, and the evidence-limitation derivation that
reaches into evidence's truncation markers — plus the terminal rendering of
sections. ``drift`` and ``reconcile`` decide *what* is a finding; nothing
here decides that.
"""

from __future__ import annotations

from collections.abc import Iterable

from glossabet.coverage import coverage_ledger, coverage_reasons
from glossabet.display import escape_terminal_text

# Per-section detail cap for every findings document. Totals stay exact;
# only the listed detail is bounded, and the cap is reported.
FINDINGS_CAP = 10

VOCABULARY_MATCHING_OMISSION = (
    "vocabulary.{name} omitted entries needed for exact matching"
)


def finding(
    kind: str,
    summary: str,
    evidence: dict | None = None,
    *,
    certainty: str | None = None,
    signal_strength: str | None = None,
    scope: dict | None = None,
    **fields,
) -> dict:
    """One finding. Exactly one of ``certainty`` (observed facts) or
    ``signal_strength`` (heuristic signals) is required — the renderer
    annotates by whichever is present, and a finding with neither or both
    would misreport its epistemic status."""
    if (certainty is None) == (signal_strength is None):
        raise ValueError(
            f"finding {kind!r} needs exactly one of certainty/signal_strength"
        )
    record: dict = {"kind": kind}
    if certainty is not None:
        record["certainty"] = certainty
    else:
        record["signal_strength"] = signal_strength
    record.update(fields)
    if scope is not None:
        record["scope"] = scope
    if evidence is not None:
        record["evidence"] = evidence
    record["summary"] = summary
    return record


def capped_section(
    items: list,
    name: str,
    *,
    incomplete_reasons: Iterable[str],
    total_items: int | None = None,
    total_items_exact: bool | None = None,
    cap: int | None = None,
) -> dict:
    """``{items, dropped_items, coverage}`` for one section: the first
    ``cap`` findings in detail, the ledger honest about the rest.

    ``total_items`` defaults to the number of findings given; pass a larger
    known total when the producer stopped collecting detail early.
    ``total_items_exact`` defaults to "no incomplete reasons".
    """
    reasons = list(incomplete_reasons)
    if cap is None:
        cap = FINDINGS_CAP  # resolved at call time so tests can lower it
    if total_items is None:
        total_items = len(items)
    if total_items_exact is None:
        total_items_exact = not reasons
    kept = items[:cap]
    if total_items > len(kept):
        reasons.append(f"{name} finding detail cap is {cap} items")
    coverage = coverage_ledger(
        total_items,
        len(kept),
        total_items_exact=total_items_exact,
        reasons=reasons,
    )
    return {
        "items": kept,
        "dropped_items": coverage["dropped_items"],
        "coverage": coverage,
    }


def mark_incomplete(section: dict, reason: str) -> dict:
    """The same section with its total declared inexact for ``reason``."""
    ledger = section["coverage"]
    coverage = coverage_ledger(
        ledger["total_items"],
        ledger["included_items"],
        total_items_exact=False,
        reasons=[*ledger["reasons"], reason],
    )
    return {
        **section,
        "dropped_items": coverage["dropped_items"],
        "coverage": coverage,
    }


def vocabulary_omission_reasons(
    evidence: dict,
    names: Iterable[str],
    template: str = VOCABULARY_MATCHING_OMISSION,
) -> list[str]:
    """One reason per named ``evidence["vocabulary"]`` collection whose
    detail was truncated at scan time — the only place a findings producer
    learns how RepositoryEvidence records that."""
    return [
        template.format(name=name)
        for name in names
        if evidence["vocabulary"][name].get("truncated") is not None
    ]


def matching_reasons(matcher) -> list[str]:
    """The evidence index's own bounded-work reasons, prefixed per index."""
    return [
        reason
        for name, ledger in matcher.coverage.items()
        for reason in coverage_reasons(ledger, f"matching.{name}")
    ]


def collection_limitations(
    collections: dict, *, skip=lambda key: False
) -> list[str]:
    """De-duplicated reasons from every listed section whose total is
    inexact (skipped sections excluded), in first-seen order."""
    return list(dict.fromkeys(
        reason
        for key, ledger in collections.items()
        if (
            isinstance(ledger, dict)
            and not ledger.get("total_items_exact", True)
            and not skip(key)
        )
        for reason in ledger.get("reasons", [])
    ))


def _print_finding_line(finding_record: dict) -> None:
    if "certainty" in finding_record:
        annotation = f"certainty {finding_record['certainty']}"
    else:
        annotation = f"signal {finding_record['signal_strength']}"
    summary = escape_terminal_text(finding_record["summary"])
    safe_annotation = escape_terminal_text(annotation)
    print(f"{summary} [{safe_annotation}]")


def _print_finding_details(finding_record: dict) -> None:
    if finding_record.get("scope", {}).get("kind") == "path-prefixes":
        print(
            "    scope: "
            + ", ".join(
                escape_terminal_text(path)
                for path in finding_record["scope"]["path_prefixes"]
            )
        )
    evidence = finding_record.get("evidence", {})
    if "shared_contexts" in evidence:
        print(
            "    shared contexts: "
            + ", ".join(
                escape_terminal_text(context)
                for context in evidence["shared_contexts"]
            )
        )
    if "locations" in evidence and evidence["locations"]:
        sample = ", ".join(
            escape_terminal_text(location["path"])
            for location in evidence["locations"][:3]
        )
        print(f"    e.g. {sample}")
    if isinstance(evidence.get("modules"), list):
        print(
            "    modules: "
            + ", ".join(
                escape_terminal_text(module["path"])
                for module in evidence["modules"]
            )
        )


def print_sections(document: dict, titles: dict[str, str], *, detail: bool) -> None:
    """Print every non-empty, non-skipped section under its title: one
    annotated line per finding (plus scope/context/location/module detail
    when ``detail`` is set) and the not-shown count."""
    for key, title in titles.items():
        section = document[key]
        if section.get("skipped"):
            continue
        if not section["items"] and not section["dropped_items"]:
            continue
        print(f"\n== {title} ==")
        for finding_record in section["items"]:
            _print_finding_line(finding_record)
            if detail:
                _print_finding_details(finding_record)
        if section["dropped_items"]:
            print(f"... and {section['dropped_items']} more not shown")
