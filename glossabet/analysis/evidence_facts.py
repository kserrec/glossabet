"""Compatibility-tolerant and derived facts about repository evidence.

Ordinary, statically known evidence fields are read directly. These helpers
exist only where a read derives meaning, accepts older or hand-built evidence,
or narrows a dynamic key.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from glossabet.analysis.evidence_types import EvidenceDocument, TruncationMarker

VocabularyName = Literal["tokens", "identifiers", "doc_terms"]


def skipped_path_entries(evidence: EvidenceDocument, kind: str) -> list[object]:
    """Return one compatibility-tolerant skipped-path ledger.

    Older or hand-built evidence can omit a ledger or contain legacy entry
    objects. Consumers that understand a particular legacy shape narrow each
    returned item themselves.
    """
    document: Mapping[str, object] = evidence
    skipped = document.get("skipped")
    entries = skipped.get(kind) if isinstance(skipped, Mapping) else None
    return list(entries) if isinstance(entries, list) else []


def oversized_identifier_count(evidence: EvidenceDocument) -> int:
    """Return the current counter or zero for supported minimal evidence.

    Direct pure-builder callers historically assembled only the ledgers their
    consumer needed. Absence therefore means that no identifier-tail omission
    was recorded; current schema-17 evidence always supplies the counter.
    """
    document: Mapping[str, object] = evidence
    skipped = document.get("skipped")
    value = (
        skipped.get("oversized_identifiers")
        if isinstance(skipped, Mapping)
        else None
    )
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def vocabulary_truncation(
    evidence: EvidenceDocument, name: VocabularyName
) -> TruncationMarker | None:
    """Return the omission marker for a dynamically selected vocabulary."""
    if name == "tokens":
        return evidence["vocabulary"]["tokens"].get("truncated")
    if name == "identifiers":
        return evidence["vocabulary"]["identifiers"].get("truncated")
    return evidence["vocabulary"]["doc_terms"].get("truncated")


def repository_corpus_complete(evidence: EvidenceDocument) -> bool:
    """Whether scanner evidence proves the full repository inventory."""
    return _corpus_budget_flag(evidence, "complete")


def production_corpus_complete(evidence: EvidenceDocument) -> bool:
    """Whether scanner evidence proves the full production corpus.

    An older budget that proves the entire repository complete also proves
    the production subset complete. Missing budget information remains
    conservative and therefore reads as incomplete.
    """
    return _corpus_budget_flag(evidence, "production_complete")


def _corpus_budget_flag(evidence: EvidenceDocument, flag: str) -> bool:
    document: Mapping[str, object] = evidence
    skipped = document.get("skipped")
    budget = skipped.get("corpus_budget") if isinstance(skipped, Mapping) else None
    if not isinstance(budget, Mapping):
        return False
    if flag == "production_complete":
        return budget.get("production_complete", budget.get("complete")) is True
    return budget.get("complete") is True
