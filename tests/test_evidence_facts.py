"""Semantic evidence reads stay conservative across compatible old shapes."""

from typing import cast

from glossabet.analysis.evidence_facts import (
    production_corpus_complete,
    repository_corpus_complete,
    skipped_path_entries,
)
from glossabet.analysis.evidence_types import EvidenceDocument


def _evidence(skipped: object) -> EvidenceDocument:
    return cast(EvidenceDocument, {"skipped": skipped})


def test_missing_corpus_budget_is_incomplete():
    evidence = _evidence({})

    assert repository_corpus_complete(evidence) is False
    assert production_corpus_complete(evidence) is False


def test_complete_legacy_budget_proves_its_production_subset():
    evidence = _evidence({"corpus_budget": {"complete": True}})

    assert repository_corpus_complete(evidence) is True
    assert production_corpus_complete(evidence) is True


def test_skipped_path_entries_tolerate_missing_and_legacy_ledgers():
    evidence = _evidence({"configured": ["src/old", {"path": "src/new"}]})

    assert skipped_path_entries(evidence, "configured") == [
        "src/old",
        {"path": "src/new"},
    ]
    assert skipped_path_entries(evidence, "absent") == []
