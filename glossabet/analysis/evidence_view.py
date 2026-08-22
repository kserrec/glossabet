"""EvidenceView: the read side of RepositoryEvidence.

`evidence.py` writes the document; every other module reads it through
this view, so the key spellings live in exactly two places (the writer and
here) and every read carries the precise type of the section it returns
(``evidence_types``). A consumer that spells a key itself is caught by
``tests/test_document_keys.py``; a consumer that misuses a section's shape
is caught by mypy. Views return the live sub-documents (no copies); callers
that mutate copy first.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, overload

from glossabet.analysis.evidence_types import (
    CodeFileEntry,
    ContextDispersionSection,
    DocFileEntry,
    DocTermTable,
    EvidenceDocument,
    FilesSection,
    GeneratorRecord,
    IdentifierTable,
    ImportsSection,
    LayersSection,
    ModuleRecord,
    NamingCandidates,
    OverloadCandidatesSection,
    RegisterSection,
    RepositoryRecord,
    SkippedSection,
    StructuralGroups,
    SynonymCandidatesSection,
    TerminologyCoverage,
    TerminologyScope,
    TerminologySection,
    TokenizationContract,
    TokenTable,
    TotalsRecord,
    TruncationMarker,
    VocabularySection,
    VocabularyTable,
)
from glossabet.corpus.config import ConfigurationEvidence
from glossabet.corpus.scanner import CorpusBudgetEvidence, MonorepoEvidence
from glossabet.runtime.git_state import GitStamp

TerminologyCandidates = (
    SynonymCandidatesSection | OverloadCandidatesSection | ContextDispersionSection
)
TerminologySubsection = (
    TerminologyCandidates | RegisterSection | LayersSection
    | TerminologyCoverage | TerminologyScope
)


class EvidenceView:
    """Named, typed lookups over one RepositoryEvidence document."""

    def __init__(self, evidence: EvidenceDocument) -> None:
        self._e = evidence

    # -- identity and provenance --------------------------------------
    def schema_version(self) -> int:
        return self._e["schema_version"]

    def generator(self) -> GeneratorRecord:
        return self._e["generator"]

    def repository(self) -> RepositoryRecord:
        return self._e["repository"]

    def git(self) -> GitStamp:
        """The filtered Git stamp ``{head, dirty}`` the evidence was built from."""
        return self._e["repository"]["git"]

    def configuration(self) -> ConfigurationEvidence:
        return self._e["configuration"]

    # -- inventory ------------------------------------------------------
    def totals(self) -> TotalsRecord:
        return self._e["totals"]

    def languages(self) -> dict[str, int]:
        return self._e["languages"]

    def modules(self) -> list[ModuleRecord]:
        return self._e["modules"]

    def files(self) -> FilesSection:
        """``{"code": [...], "docs": [...]}`` inventory entries."""
        return self._e["files"]

    @overload
    def file_entries(self, kind: Literal["code"]) -> list[CodeFileEntry]: ...
    @overload
    def file_entries(self, kind: Literal["docs"]) -> list[DocFileEntry]: ...
    @overload
    def file_entries(self, kind: str) -> list[CodeFileEntry] | list[DocFileEntry]: ...

    def file_entries(self, kind: str) -> list[CodeFileEntry] | list[DocFileEntry]:
        """Inventory entries of one kind, ``"code"`` or ``"docs"``."""
        if kind == "code":
            return self._e["files"]["code"]
        if kind == "docs":
            return self._e["files"]["docs"]
        raise KeyError(kind)

    def imports(self) -> ImportsSection:
        return self._e["imports"]

    def monorepo(self) -> MonorepoEvidence:
        return self._e["monorepo"]

    # -- vocabulary -----------------------------------------------------
    def vocabulary(self) -> VocabularySection:
        """The whole vocabulary section: normalization contract plus the
        capped ``tokens`` / ``identifiers`` / ``doc_terms`` tables."""
        return self._e["vocabulary"]

    def normalization(self) -> TokenizationContract:
        return self._e["vocabulary"]["normalization"]

    @overload
    def vocabulary_table(self, name: Literal["tokens"]) -> TokenTable: ...
    @overload
    def vocabulary_table(self, name: Literal["identifiers"]) -> IdentifierTable: ...
    @overload
    def vocabulary_table(self, name: Literal["doc_terms"]) -> DocTermTable: ...
    @overload
    def vocabulary_table(self, name: str) -> VocabularyTable: ...

    def vocabulary_table(self, name: str) -> VocabularyTable:
        """One capped table (``tokens`` / ``identifiers`` / ``doc_terms``):
        ``{items, truncated, coverage}``."""
        if name == "tokens":
            return self._e["vocabulary"]["tokens"]
        if name == "identifiers":
            return self._e["vocabulary"]["identifiers"]
        if name == "doc_terms":
            return self._e["vocabulary"]["doc_terms"]
        raise KeyError(name)

    def truncated(self, name: str) -> TruncationMarker | None:
        """The truncation marker of one vocabulary table, ``None`` when the
        table is complete."""
        return self.vocabulary_table(name).get("truncated")

    # -- analyses -------------------------------------------------------
    def terminology(self) -> TerminologySection:
        return self._e["terminology"]

    @overload
    def terminology_section(
        self, name: Literal["synonym_candidates"],
    ) -> SynonymCandidatesSection: ...
    @overload
    def terminology_section(
        self, name: Literal["overload_candidates"],
    ) -> OverloadCandidatesSection: ...
    @overload
    def terminology_section(
        self, name: Literal["context_dispersion"],
    ) -> ContextDispersionSection: ...
    @overload
    def terminology_section(self, name: Literal["register"]) -> RegisterSection: ...
    @overload
    def terminology_section(self, name: Literal["layers"]) -> LayersSection: ...
    @overload
    def terminology_section(self, name: str) -> TerminologySubsection: ...

    def terminology_section(self, name: str) -> TerminologySubsection:
        """One terminology collection such as ``synonym_candidates`` or
        ``overload_candidates``: ``{items, dropped_items, ...}``."""
        terminology = self._e["terminology"]
        if name == "synonym_candidates":
            return terminology["synonym_candidates"]
        if name == "overload_candidates":
            return terminology["overload_candidates"]
        if name == "context_dispersion":
            return terminology["context_dispersion"]
        if name == "register":
            return terminology["register"]
        if name == "layers":
            return terminology["layers"]
        if name == "coverage":
            return terminology["coverage"]
        if name == "scope":
            return terminology["scope"]
        raise KeyError(name)

    def terminology_scope(self) -> TerminologyScope:
        """``{roles, code_files, doc_files}`` — what the terminology
        analysis was computed over."""
        return self._e["terminology"]["scope"]

    def naming_candidates(self) -> NamingCandidates:
        return self._e["naming_candidates"]

    def structural_groups(self) -> StructuralGroups:
        return self._e["structural_groups"]

    # -- omissions ------------------------------------------------------
    def skipped(self) -> SkippedSection:
        """The whole omissions ledger."""
        return self._e["skipped"]

    def skipped_paths(self, kind: str) -> list[str]:
        """Paths recorded under one exclusion kind (``[]`` when absent)."""
        ledger: Mapping[str, object] = self._e["skipped"]
        paths = ledger.get(kind)
        return list(paths) if isinstance(paths, list) else []

    def corpus_budget(self) -> CorpusBudgetEvidence:
        return self._e["skipped"]["corpus_budget"]

    def repository_corpus_complete(self) -> bool:
        """Whether the repository inventory has no scanner-created omissions."""
        return self._corpus_budget_flag("complete")

    def production_corpus_complete(self) -> bool:
        """Whether production vocabulary has no scanner-created omissions."""
        return self._corpus_budget_flag("production_complete")

    def _corpus_budget_flag(self, flag: str) -> bool:
        # Read tolerantly: a hand-built or older evidence document without a
        # budget is incomplete evidence, not a crash.
        document: Mapping[str, object] = self._e
        skipped = document.get("skipped")
        budget = skipped.get("corpus_budget") if isinstance(skipped, Mapping) else None
        if not isinstance(budget, Mapping):
            return False
        if flag == "production_complete":
            return budget.get("production_complete", budget.get("complete")) is True
        return budget.get("complete") is True
