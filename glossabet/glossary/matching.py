"""Exact lexical-unit matching for glossary terms against code evidence.

A one-token term uses the token index. A compound term is observed only when
its ordered tokens occur contiguously inside one identifier spelling, such as
``PaymentRequest`` or ``create_payment_request``. Independent token hits in a
file, module, or repository never establish a compound occurrence.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Iterable
from typing import TypedDict

from glossabet.analysis.evidence_facts import (
    production_corpus_complete as evidence_production_corpus_complete,
)
from glossabet.analysis.evidence_facts import (
    repository_corpus_complete as evidence_repository_corpus_complete,
)
from glossabet.analysis.evidence_types import (
    EvidenceDocument,
    IdentifierEntry,
    TokenEntry,
    VocabularyEntry,
)
from glossabet.corpus.imports import module_of
from glossabet.corpus.tokenize import doc_words, tokenize_identifier, tokenize_term
from glossabet.glossary.model import ScopeEvidence
from glossabet.glossary.store import path_in_scope, scope_evidence
from glossabet.runtime.coverage import (
    CoverageLedger,
    LocationSample,
    coverage_ledger,
    location_sample,
)

LOCATION_SAMPLE = 5
COMPOUND_MATCH_START_BUDGET = 250_000
MAX_COMPOUND_TERM_TOKENS = 32


class _TrieNode:
    """One node of the compound-term trie: children by token, and the
    compounds that end exactly here."""

    __slots__ = ("children", "terminals")

    def __init__(self) -> None:
        self.children: dict[str, _TrieNode] = {}
        self.terminals: list[tuple[str, ...]] = []


def _match_compounds(
    units: list[tuple[IdentifierEntry, list[str]]],
    supported: set[tuple[str, ...]],
    start_budget: int,
) -> tuple[dict[tuple[str, ...], list[IdentifierEntry]], int, int]:
    """One bounded trie pass mapping each supported compound to its entries.

    Returns (matches, processed starts, total starts). A start is one
    identifier position where a compound could begin; the budget caps how
    many are examined across the whole index.
    """
    matches: dict[tuple[str, ...], list[IdentifierEntry]] = {
        wanted: [] for wanted in supported
    }
    total_starts = sum(len(unit) for _, unit in units) if supported else 0
    processed_starts = 0

    trie = _TrieNode()
    for wanted in supported:
        node = trie
        for token in wanted:
            node = node.children.setdefault(token, _TrieNode())
        node.terminals.append(wanted)

    exhausted = False
    for entry, unit in (units if supported else []):
        matched: set[tuple[str, ...]] = set()
        for start in range(len(unit)):
            if processed_starts >= start_budget:
                exhausted = True
                break
            processed_starts += 1
            node = trie
            for token in unit[start:start + MAX_COMPOUND_TERM_TOKENS]:
                child = node.children.get(token)
                if child is None:
                    break
                node = child
                matched.update(node.terminals)
        for wanted in matched:
            matches[wanted].append(entry)
        if exhausted:
            break
    return matches, processed_starts, total_starts


class DocOccurrence(TypedDict):
    """How often a term occurs in documentation, and whether that count
    is exact for the corpus the scan read."""

    count: int
    count_exact: bool
    scope: ScopeEvidence


class _CodeOccurrenceFacts(TypedDict):
    count: int
    count_exact: bool
    files: int
    files_exact: bool
    modules: int
    modules_exact: bool
    locations: list[LocationSample]
    locations_truncated: bool


class IdentifierOccurrence(DocOccurrence):
    """One identifier's numeric occurrence facts and bounded location display."""

    files: int
    files_exact: bool
    modules: int
    modules_exact: bool
    locations: list[LocationSample]
    locations_truncated: bool


class TermOccurrence(IdentifierOccurrence):
    """A glossary term's occurrence in code: a single token is matched
    against the token table, a compound term as a lexical unit."""

    term_tokens: list[str]
    match_kind: str


def is_unproven_zero(occurrence: DocOccurrence) -> bool:
    """Whether zero is only a lower bound, not evidence of absence.

    ``count_exact`` already combines corpus, table, scope-location, matching
    work, and term-representability limits. Consumers should not reconstruct
    those causes from display or coverage fields.
    """
    return occurrence["count"] == 0 and not occurrence["count_exact"]


def _matching_locations(
    entry: VocabularyEntry, scope: tuple[str, ...],
) -> list[LocationSample]:
    return [
        location for location in entry["locations"]
        if path_in_scope(location["path"], scope)
    ]


def _scoped_entry_occurrence(
    entry: VocabularyEntry,
    scope: tuple[str, ...],
    corpus_complete: bool,
) -> _CodeOccurrenceFacts:
    locations = _matching_locations(entry, scope)
    modules = {module_of(location["path"]) for location in locations}
    upstream_locations_exact = not entry.get("locations_truncated", False)
    display_truncated = len(locations) > LOCATION_SAMPLE
    return {
        "count": sum(location["count"] for location in locations),
        "count_exact": upstream_locations_exact and corpus_complete,
        "files": len(locations),
        "files_exact": upstream_locations_exact and corpus_complete,
        "modules": len(modules),
        "modules_exact": upstream_locations_exact and corpus_complete,
        "locations": locations[:LOCATION_SAMPLE],
        "locations_truncated": not upstream_locations_exact or display_truncated,
    }


def _unscoped_entry_occurrence(
    entry: TokenEntry | IdentifierEntry,
    corpus_complete: bool,
) -> _CodeOccurrenceFacts:
    locations = list(entry["locations"])
    display_truncated = len(locations) > LOCATION_SAMPLE
    return {
        "count": entry["count"],
        "count_exact": corpus_complete,
        "files": entry["files"],
        "files_exact": corpus_complete,
        "modules": entry["modules"],
        "modules_exact": corpus_complete,
        "locations": locations[:LOCATION_SAMPLE],
        "locations_truncated": entry["locations_truncated"] or display_truncated,
    }


class EvidenceIndex:
    """One bounded lexical index shared by all glossary consumers.

    Single-token, documentation, symbol, file, and module lookups become
    constant-time dictionaries.  Requested compound terms are matched in one
    bounded trie pass over the identifier index, instead of rescanning every
    identifier once per glossary concept.
    """

    def __init__(
        self,
        evidence: EvidenceDocument,
        terms: Iterable[str] = (),
        *,
        compound_start_budget: int = COMPOUND_MATCH_START_BUDGET,
    ) -> None:
        if compound_start_budget < 0:
            raise ValueError("compound match budget must be non-negative")
        self.evidence = evidence
        self.token_section = evidence["vocabulary"]["tokens"]
        self.identifier_section = evidence["vocabulary"]["identifiers"]
        self.doc_section = evidence["vocabulary"]["doc_terms"]
        self.token_entries = {
            entry["term"]: entry for entry in self.token_section["items"]
        }
        self.identifier_entries = {
            entry["name"]: entry for entry in self.identifier_section["items"]
        }
        self.doc_entries = {
            entry["term"]: entry for entry in self.doc_section["items"]
        }
        # NFC-keyed for the same reason path_in_scope compares in NFC.
        self.file_paths = {
            unicodedata.normalize("NFC", item["path"])
            for item in [*evidence["files"]["code"], *evidence["files"]["docs"]]
        }
        self.module_paths = {
            unicodedata.normalize("NFC", module["path"])
            for module in evidence["modules"]
        }

        requested: set[tuple[str, ...]] = set()
        for term in terms:
            wanted = tuple(tokenize_term(term))
            if len(wanted) > 1:
                requested.add(wanted)
        supported = {
            wanted for wanted in requested
            if len(wanted) <= MAX_COMPOUND_TERM_TOKENS
        }
        self._unsupported_compounds = requested - supported

        units: list[tuple[IdentifierEntry, list[str]]] = []
        for entry in self.identifier_section["items"]:
            unit = entry.get("tokens")
            if not isinstance(unit, list):
                unit = tokenize_identifier(entry["name"])
            units.append((entry, unit))
        self._compound_matches, processed_starts, total_starts = (
            _match_compounds(units, supported, compound_start_budget)
        )

        work_reasons = []
        if processed_starts < total_starts:
            work_reasons.append(
                "compound lexical matching reached its "
                f"{compound_start_budget}-identifier-position budget"
            )
        term_reasons = []
        if self._unsupported_compounds:
            term_reasons.append(
                f"{len(self._unsupported_compounds)} compound term(s) exceed "
                f"the {MAX_COMPOUND_TERM_TOKENS}-token matching limit"
            )
        self.coverage: dict[str, CoverageLedger] = {
            "compound_match_positions": coverage_ledger(
                total_starts,
                processed_starts,
                reasons=work_reasons,
            ),
            "compound_terms": coverage_ledger(
                len(requested),
                len(supported),
                reasons=term_reasons,
            ),
        }
        # The position budget is index-wide (an exhausted pass leaves every
        # compound term's count a lower bound); the term-length cap is not —
        # an over-cap term is simply absent from the matches, and must not
        # mark every other compound term's count inexact.
        self.compound_complete = self.coverage["compound_match_positions"]["complete"]

    @property
    def repository_corpus_complete(self) -> bool:
        """Whether the evidence proves the complete repository inventory."""
        return evidence_repository_corpus_complete(self.evidence)

    @property
    def production_corpus_complete(self) -> bool:
        """Whether the evidence proves the complete production corpus."""
        return evidence_production_corpus_complete(self.evidence)

    def code_term_occurrence(
        self, term: str, scope: tuple[str, ...] | None = None
    ) -> TermOccurrence:
        wanted = tokenize_term(term)
        corpus_complete = self.production_corpus_complete
        empty: TermOccurrence = {
            "term_tokens": wanted,
            "match_kind": "token" if len(wanted) <= 1 else "lexical-unit",
            "count": 0,
            "count_exact": corpus_complete,
            "files": 0,
            "files_exact": corpus_complete,
            "modules": 0,
            "modules_exact": corpus_complete,
            "locations": [],
            "locations_truncated": False,
            "scope": scope_evidence(scope),
        }
        if not wanted:
            return {
                **empty,
                "count_exact": False,
                "files_exact": False,
                "modules_exact": False,
            }
        if len(wanted) == 1:
            return self._single_token_occurrence(
                wanted, scope, corpus_complete, empty
            )
        return self._compound_occurrence(wanted, scope, corpus_complete)

    def _single_token_occurrence(
        self, wanted: list[str], scope: tuple[str, ...] | None,
        corpus_complete: bool, empty: TermOccurrence,
    ) -> TermOccurrence:
        entry = self.token_entries.get(wanted[0])
        if entry is None:
            complete = (
                self.token_section.get("truncated") is None
                and corpus_complete
            )
            return {
                **empty,
                "count_exact": complete,
                "files_exact": complete,
                "modules_exact": complete,
            }
        if scope is not None:
            return {
                "term_tokens": wanted,
                "match_kind": "token",
                **_scoped_entry_occurrence(entry, scope, corpus_complete),
                "scope": scope_evidence(scope),
            }
        return {
            "term_tokens": wanted,
            "match_kind": "token",
            **_unscoped_entry_occurrence(entry, corpus_complete),
            "scope": scope_evidence(scope),
        }

    def _compound_occurrence(
        self, wanted: list[str], scope: tuple[str, ...] | None,
        corpus_complete: bool,
    ) -> TermOccurrence:
        wanted_tuple = tuple(wanted)
        entries = self._compound_matches.get(wanted_tuple, [])
        count = 0
        locations: Counter[str] = Counter()
        upstream_locations_truncated = False
        index_complete = (
            wanted_tuple in self._compound_matches and self.compound_complete
        )
        indexed_corpus_exact = (
            self.identifier_section.get("truncated") is None
            and corpus_complete
            and index_complete
        )
        upstream_locations_exact = True
        for entry in entries:
            entry_locations = entry.get("locations", [])
            if scope is None:
                count += entry["count"]
            else:
                entry_locations = _matching_locations(entry, scope)
                count += sum(location["count"] for location in entry_locations)
            for location in entry_locations:
                locations[location["path"]] += location["count"]
            if entry.get("locations_truncated"):
                upstream_locations_truncated = True
                upstream_locations_exact = False

        # The display sample may be clipped without making the file total a
        # lower bound: ``files`` counts every aggregated location. Only an
        # upstream entry-level clip (handled above) makes ``files`` inexact.
        kept, sample_truncated = location_sample(locations, LOCATION_SAMPLE)
        return {
            "term_tokens": wanted,
            "match_kind": "lexical-unit",
            "count": count,
            "count_exact": (
                indexed_corpus_exact
                and (scope is None or upstream_locations_exact)
            ),
            "files": len(locations),
            "files_exact": indexed_corpus_exact and upstream_locations_exact,
            "modules": len({module_of(path) for path in locations}),
            "modules_exact": indexed_corpus_exact and upstream_locations_exact,
            "locations": kept,
            "locations_truncated": (
                upstream_locations_truncated or sample_truncated
            ),
            "scope": scope_evidence(scope),
        }

    def code_identifier_occurrence(
        self, name: str, scope: tuple[str, ...] | None = None
    ) -> IdentifierOccurrence:
        corpus_complete = self.production_corpus_complete
        entry = self.identifier_entries.get(name)
        if entry is None:
            complete = (
                self.identifier_section.get("truncated") is None
                and corpus_complete
            )
            return {
                "count": 0,
                "count_exact": complete,
                "files": 0,
                "files_exact": complete,
                "modules": 0,
                "modules_exact": complete,
                "locations": [],
                "locations_truncated": False,
                "scope": scope_evidence(scope),
            }
        if scope is not None:
            return {
                **_scoped_entry_occurrence(entry, scope, corpus_complete),
                "scope": scope_evidence(scope),
            }
        return {
            **_unscoped_entry_occurrence(entry, corpus_complete),
            "scope": scope_evidence(scope),
        }

    def doc_term_occurrence(
        self, term: str, scope: tuple[str, ...] | None = None
    ) -> DocOccurrence:
        wanted = tokenize_term(term)
        corpus_complete = self.production_corpus_complete
        # The documentation index is keyed by *doc words* (letters-only,
        # apostrophes kept, at least MIN_DOC_WORD_LEN long), not identifier
        # tokens: ``O'Brien`` is one doc word but tokenizes to ``brien``, and
        # ``ID``/``S3`` are no doc word at all. Look the term up the way the
        # index was built, and treat a term the index cannot hold as unproven.
        doc_keys = doc_words(term)
        if len(wanted) != 1 or len(doc_keys) != 1:
            return {
                "count": 0,
                "count_exact": False,
                "scope": scope_evidence(scope),
            }
        entry = self.doc_entries.get(doc_keys[0])
        if entry is None:
            return {
                "count": 0,
                "count_exact": (
                    self.doc_section.get("truncated") is None
                    and corpus_complete
                ),
                "scope": scope_evidence(scope),
            }
        if scope is None:
            return {
                "count": entry["count"],
                "count_exact": corpus_complete,
                "scope": scope_evidence(scope),
            }
        scoped = _scoped_entry_occurrence(entry, scope, corpus_complete)
        return {
            "count": scoped["count"],
            "count_exact": scoped["count_exact"],
            "scope": scope_evidence(scope),
        }
