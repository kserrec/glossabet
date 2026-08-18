"""Exact lexical-unit matching for glossary terms against code evidence.

A one-token term uses the token index. A compound term is observed only when
its ordered tokens occur contiguously inside one identifier spelling, such as
``PaymentRequest`` or ``create_payment_request``. Independent token hits in a
file, module, or repository never establish a compound occurrence.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from glossabet.runtime.coverage import coverage_ledger, location_sample
from glossabet.analysis.evidence_view import EvidenceView
from glossabet.glossary.store import path_in_scope, scope_evidence
from glossabet.corpus.imports import module_of
from glossabet.corpus.tokenize import doc_words, tokenize_identifier, tokenize_term

LOCATION_SAMPLE = 5
COMPOUND_MATCH_START_BUDGET = 250_000
MAX_COMPOUND_TERM_TOKENS = 32


def _match_compounds(
    units: list[tuple[dict, list[str]]],
    supported: set[tuple[str, ...]],
    start_budget: int,
) -> tuple[dict[tuple[str, ...], list[dict]], int, int]:
    """One bounded trie pass mapping each supported compound to its entries.

    Returns (matches, processed starts, total starts). A start is one
    identifier position where a compound could begin; the budget caps how
    many are examined across the whole index.
    """
    matches: dict[tuple[str, ...], list[dict]] = {
        wanted: [] for wanted in supported
    }
    total_starts = sum(len(unit) for _, unit in units) if supported else 0
    processed_starts = 0

    trie: dict = {}
    terminal = object()
    for wanted in supported:
        node = trie
        for token in wanted:
            node = node.setdefault(token, {})
        node.setdefault(terminal, []).append(wanted)

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
                child = node.get(token)
                if child is None:
                    break
                node = child
                matched.update(node.get(terminal, ()))
        for wanted in matched:
            matches[wanted].append(entry)
        if exhausted:
            break
    return matches, processed_starts, total_starts


def _matching_locations(entry: dict, scope: tuple[str, ...]) -> list[dict]:
    return [
        location for location in entry.get("locations", [])
        if path_in_scope(location["path"], scope)
    ]


def _scoped_entry_occurrence(
    entry: dict,
    scope: tuple[str, ...],
    corpus_complete: bool,
) -> dict:
    locations = _matching_locations(entry, scope)
    modules = {module_of(location["path"]) for location in locations}
    locations_complete = not entry.get("locations_truncated", False)
    return {
        "count": sum(location["count"] for location in locations),
        "count_complete": locations_complete and corpus_complete,
        "files": len(locations),
        "files_complete": locations_complete and corpus_complete,
        "modules": len(modules),
        "locations": locations[:LOCATION_SAMPLE],
        "locations_truncated": bool(entry.get("locations_truncated", False)),
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
        evidence: dict,
        terms: Iterable[str] = (),
        *,
        compound_start_budget: int = COMPOUND_MATCH_START_BUDGET,
    ) -> None:
        if compound_start_budget < 0:
            raise ValueError("compound match budget must be non-negative")
        self.view = EvidenceView(evidence)
        self.token_section = self.view.vocabulary_table("tokens")
        self.identifier_section = self.view.vocabulary_table("identifiers")
        self.doc_section = self.view.vocabulary_table("doc_terms")
        self.token_entries = {
            entry["term"]: entry for entry in self.token_section["items"]
        }
        self.identifier_entries = {
            entry["name"]: entry for entry in self.identifier_section["items"]
        }
        self.doc_entries = {
            entry["term"]: entry for entry in self.doc_section["items"]
        }
        self.file_paths = {
            item["path"]
            for kind in ("code", "docs")
            for item in self.view.file_entries(kind)
        }
        self.module_paths = {
            module["path"] for module in self.view.modules()
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

        units = []
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
        self.coverage = {
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
        self.compound_complete = all(
            ledger["complete"] for ledger in self.coverage.values()
        )

    def code_term_occurrence(
        self, term: str, scope: tuple[str, ...] | None = None
    ) -> dict:
        wanted = tokenize_term(term)
        corpus_complete = self.view.production_corpus_complete()
        empty = {
            "term_tokens": wanted,
            "match_kind": "token" if len(wanted) <= 1 else "lexical-unit",
            "count": 0,
            "count_complete": corpus_complete,
            "files": 0,
            "files_complete": corpus_complete,
            "modules": 0,
            "locations": [],
            "locations_truncated": False,
            "scope": scope_evidence(scope),
        }
        if not wanted:
            return empty
        if len(wanted) == 1:
            return self._single_token_occurrence(
                wanted, scope, corpus_complete, empty
            )
        return self._compound_occurrence(wanted, scope, corpus_complete)

    def _single_token_occurrence(
        self, wanted: list[str], scope: tuple[str, ...] | None,
        corpus_complete: bool, empty: dict,
    ) -> dict:
        entry = self.token_entries.get(wanted[0])
        if entry is None:
            complete = (
                self.token_section.get("truncated") is None
                and corpus_complete
            )
            return {
                **empty,
                "count_complete": complete,
                "files_complete": complete,
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
            "count": entry["count"],
            "count_complete": corpus_complete,
            "files": entry["files"],
            "files_complete": corpus_complete,
            "modules": entry["modules"],
            "locations": list(entry["locations"]),
            "locations_truncated": entry["locations_truncated"],
            "scope": scope_evidence(scope),
        }

    def _compound_occurrence(
        self, wanted: list[str], scope: tuple[str, ...] | None,
        corpus_complete: bool,
    ) -> dict:
        wanted_tuple = tuple(wanted)
        entries = self._compound_matches.get(wanted_tuple, [])
        count = 0
        locations: Counter = Counter()
        locations_truncated = False
        scoped_count_complete = True
        index_complete = (
            wanted_tuple in self._compound_matches and self.compound_complete
        )
        files_complete = (
            self.identifier_section.get("truncated") is None
            and corpus_complete
            and index_complete
        )
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
                locations_truncated = True
                files_complete = False
                if scope is not None:
                    scoped_count_complete = False

        # The display sample may be clipped without making the file total a
        # lower bound: ``files`` counts every aggregated location. Only an
        # upstream entry-level clip (handled above) makes ``files`` inexact.
        kept, sample_truncated = location_sample(locations, LOCATION_SAMPLE)
        locations_truncated = locations_truncated or sample_truncated
        return {
            "term_tokens": wanted,
            "match_kind": "lexical-unit",
            "count": count,
            "count_complete": (
                self.identifier_section.get("truncated") is None
                and scoped_count_complete
                and corpus_complete
                and index_complete
            ),
            "files": len(locations),
            "files_complete": files_complete,
            "modules": len({module_of(path) for path in locations}),
            "locations": kept,
            "locations_truncated": locations_truncated,
            "scope": scope_evidence(scope),
        }

    def code_identifier_occurrence(
        self, name: str, scope: tuple[str, ...] | None = None
    ) -> dict:
        corpus_complete = self.view.production_corpus_complete()
        entry = self.identifier_entries.get(name)
        if entry is None:
            complete = (
                self.identifier_section.get("truncated") is None
                and corpus_complete
            )
            return {
                "count": 0,
                "count_complete": complete,
                "files": 0,
                "files_complete": complete,
                "modules": 0,
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
            "count": entry["count"],
            "count_complete": corpus_complete,
            "files": entry["files"],
            "files_complete": corpus_complete,
            "modules": len({
                module_of(location["path"])
                for location in entry.get("locations", [])
            }),
            "locations": list(entry.get("locations", [])),
            "locations_truncated": entry.get("locations_truncated", False),
            "scope": scope_evidence(scope),
        }

    def doc_term_occurrence(
        self, term: str, scope: tuple[str, ...] | None = None
    ) -> dict:
        wanted = tokenize_term(term)
        corpus_complete = self.view.production_corpus_complete()
        if len(wanted) != 1:
            return {
                "count": 0,
                "count_complete": False,
                "scope": scope_evidence(scope),
            }
        entry = self.doc_entries.get(wanted[0])
        if entry is None:
            # Absence proves zero mentions only if the documentation index
            # could hold this token at all: doc words are letters-only and
            # at least MIN_DOC_WORD_LEN long, so ``ID``, ``S3``, ``OAuth2``
            # never appear there however often the README uses them.
            representable = doc_words(wanted[0]) == [wanted[0]]
            return {
                "count": 0,
                "count_complete": (
                    representable
                    and self.doc_section.get("truncated") is None
                    and corpus_complete
                ),
                "scope": scope_evidence(scope),
            }
        if scope is None:
            return {
                "count": entry["count"],
                "count_complete": corpus_complete,
                "scope": scope_evidence(scope),
            }
        scoped = _scoped_entry_occurrence(entry, scope, corpus_complete)
        return {
            "count": scoped["count"],
            "count_complete": scoped["count_complete"],
            "scope": scope_evidence(scope),
        }

