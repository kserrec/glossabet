"""EvidenceView: the read side of RepositoryEvidence.

`evidence.py` writes the document; every other module reads it through
this view, so the key spellings live in exactly two places (the writer and
here) and a consumer's typo is an ``AttributeError`` at import time, not a
``KeyError`` in a branch a test may never reach. Views return the live
sub-documents (no copies); callers that mutate copy first.
"""

from __future__ import annotations


class EvidenceView:
    """Named lookups over one RepositoryEvidence dict."""

    def __init__(self, evidence: dict) -> None:
        self._e = evidence

    # -- identity and provenance --------------------------------------
    def schema_version(self) -> int:
        return self._e["schema_version"]

    def generator(self) -> dict:
        return self._e["generator"]

    def repository(self) -> dict:
        return self._e["repository"]

    def git(self) -> dict:
        """The filtered Git stamp ``{head, dirty}`` the evidence was built from."""
        return self._e["repository"]["git"]

    def configuration(self) -> dict:
        return self._e["configuration"]

    # -- inventory ------------------------------------------------------
    def totals(self) -> dict:
        return self._e["totals"]

    def languages(self) -> dict:
        return self._e["languages"]

    def modules(self) -> list[dict]:
        return self._e["modules"]

    def files(self) -> dict:
        """``{"code": [...], "docs": [...]}`` inventory entries."""
        return self._e["files"]

    def file_entries(self, kind: str) -> list[dict]:
        """Inventory entries of one kind, ``"code"`` or ``"docs"``."""
        return self._e["files"][kind]

    def imports(self) -> dict:
        return self._e["imports"]

    def monorepo(self) -> dict:
        return self._e["monorepo"]

    # -- vocabulary -----------------------------------------------------
    def vocabulary(self) -> dict:
        """The whole vocabulary section: normalization contract plus the
        capped ``tokens`` / ``identifiers`` / ``doc_terms`` tables."""
        return self._e["vocabulary"]

    def normalization(self) -> dict:
        return self._e["vocabulary"]["normalization"]

    def vocabulary_table(self, name: str) -> dict:
        """One capped table (``tokens`` / ``identifiers`` / ``doc_terms``):
        ``{items, truncated, coverage}``."""
        return self._e["vocabulary"][name]

    def truncated(self, name: str) -> dict | None:
        """The truncation marker of one vocabulary table, ``None`` when the
        table is complete."""
        return self._e["vocabulary"][name].get("truncated")

    # -- analyses -------------------------------------------------------
    def terminology(self) -> dict:
        return self._e["terminology"]

    def terminology_section(self, name: str) -> dict:
        """One terminology collection such as ``synonym_candidates`` or
        ``overload_candidates``: ``{items, dropped_items, ...}``."""
        return self._e["terminology"][name]

    def terminology_scope(self) -> dict:
        """``{roles, code_files, doc_files}`` — what the terminology
        analysis was computed over."""
        return self._e["terminology"]["scope"]

    def naming_candidates(self) -> dict:
        return self._e["naming_candidates"]

    def structural_groups(self) -> dict:
        return self._e["structural_groups"]

    # -- omissions ------------------------------------------------------
    def skipped(self) -> dict:
        """The whole omissions ledger."""
        return self._e["skipped"]

    def skipped_paths(self, kind: str) -> list[str]:
        """Paths recorded under one exclusion kind (``[]`` when absent)."""
        return list(self._e["skipped"].get(kind, []))

    def corpus_budget(self) -> dict:
        return self._e["skipped"]["corpus_budget"]

    def repository_corpus_complete(self) -> bool:
        """Whether the repository inventory has no scanner-created omissions."""
        budget = self._e.get("skipped", {}).get("corpus_budget", {})
        return isinstance(budget, dict) and budget.get("complete") is True

    def production_corpus_complete(self) -> bool:
        """Whether production vocabulary has no scanner-created omissions."""
        budget = self._e.get("skipped", {}).get("corpus_budget", {})
        if not isinstance(budget, dict):
            return False
        return budget.get("production_complete", budget.get("complete")) is True
