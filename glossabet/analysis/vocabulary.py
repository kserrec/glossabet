"""The vocabularies of one scan as aggregates with named views.

``ProductionVocabulary`` is the identifier vocabulary of production code;
``DocumentationVocabulary`` is the prose vocabulary of production docs. Each
owns the fold that keeps its views consistent, so callers take the aggregate
and never carry its insides around as parallel dicts."""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations

from glossabet.corpus.tokenize import (
    TOKEN_ORIGIN_DOMAIN,
    token_origin,
    tokenize_identifier,
)

# Per-(token, module) neighbor sets are capped so the context-dispersion
# analysis stays bounded; every set that hit the cap is recorded.
MODULE_CONTEXT_ANALYSIS_CAP = 30
# A real identifier has a handful of tokens. The pattern and co-occurrence
# views are O(t^2) in token count, so a single pathological spelling
# (permitted up to the 2 MB file cap) would otherwise exhaust CPU and
# memory; the token list is cut here and the spelling counted.
MAX_IDENTIFIER_TOKENS = 64


class ProductionVocabulary:
    """The production identifier vocabulary of one scan.

    Built by folding each production code file's identifier counts in
    (``fold``); read through its named views. The views are kept in step by
    the fold — the same normalized tokens key every one of them — and that
    invariant is this module's job, not the callers': the terminology and
    naming analyses take the vocabulary, never its insides as parallel
    arguments.

    Views (all keyed by normalized token unless stated):
    ``token_counts`` total occurrences · ``token_files`` per-file counts ·
    ``token_modules`` per-module counts · ``token_patterns`` positional
    compound patterns (``("run", "*")``) with counts · ``token_origins``
    domain/language origin (domain wins across occurrences) · ``neighbors``
    co-occurrence counts within one identifier · ``module_neighbor_sets``
    per-module neighbor sets capped at ``MODULE_CONTEXT_ANALYSIS_CAP`` with
    ``module_neighbor_truncated`` recording every (token, module) that hit
    the cap · ``identifier_counts`` / ``identifier_files`` keyed by the raw
    identifier spelling · ``oversized_identifiers`` the number of spellings
    whose token list was cut at ``MAX_IDENTIFIER_TOKENS``.
    """

    def __init__(self) -> None:
        self.token_counts: Counter = Counter()
        self.token_files: dict[str, Counter] = defaultdict(Counter)
        self.token_modules: dict[str, Counter] = defaultdict(Counter)
        self.token_patterns: dict[str, Counter] = defaultdict(Counter)
        self.token_origins: dict[str, str] = {}
        self.neighbors: dict[str, Counter] = defaultdict(Counter)
        self.module_neighbor_sets: dict[str, dict[str, set]] = defaultdict(
            lambda: defaultdict(set)
        )
        self.module_neighbor_truncated: set[tuple[str, str]] = set()
        self.identifier_counts: Counter = Counter()
        self.identifier_files: dict[str, Counter] = defaultdict(Counter)
        self.oversized_identifiers = 0

    def fold(
        self,
        identifiers: dict[str, int],
        rel: str,
        module: str,
        language: str,
    ) -> None:
        """Fold one code file's identifier counts into every view."""
        for name, count in sorted(identifiers.items()):
            self.identifier_counts[name] += count
            self.identifier_files[name][rel] += count
            tokens = tokenize_identifier(name)
            if len(tokens) > MAX_IDENTIFIER_TOKENS:
                # See MAX_IDENTIFIER_TOKENS.
                tokens = tokens[:MAX_IDENTIFIER_TOKENS]
                self.oversized_identifiers += 1
            uniq = sorted(set(tokens))
            for token in tokens:
                self.token_counts[token] += count
                self.token_files[token][rel] += count
                self.token_modules[token][module] += count
                occurrence_origin = token_origin(token, language)
                if (
                    token not in self.token_origins
                    or occurrence_origin == TOKEN_ORIGIN_DOMAIN
                ):
                    # Domain wins across occurrences. A Python builtin named
                    # ``dict`` must not hide a same-spelled project concept in
                    # another language.
                    self.token_origins[token] = occurrence_origin
            if len(tokens) >= 2:
                for index, token in enumerate(tokens):
                    pattern = tuple(tokens[:index] + ["*"] + tokens[index + 1:])
                    self.token_patterns[token][pattern] += count
            for a, b in combinations(uniq, 2):
                self.neighbors[a][b] += count
                self.neighbors[b][a] += count
            for token in uniq:
                seen = self.module_neighbor_sets[token][module]
                for neighbor in uniq:
                    if neighbor == token or neighbor in seen:
                        continue
                    if len(seen) < MODULE_CONTEXT_ANALYSIS_CAP:
                        seen.add(neighbor)
                    else:
                        self.module_neighbor_truncated.add((token, module))

    @classmethod
    def from_files(
        cls, files: list[tuple[str, str, str, dict[str, int]]]
    ) -> "ProductionVocabulary":
        """Fold ``(relative path, module, language, {identifier: count})``
        entries in order — the way tests build a vocabulary from text."""
        vocabulary = cls()
        for rel, module, language, identifiers in files:
            vocabulary.fold(identifiers, rel, module, language)
        return vocabulary


class DocumentationVocabulary:
    """The production documentation vocabulary of one scan.

    Built by folding each production doc file's word counts in (``fold``);
    read through its named views, both keyed by the doc term as
    ``tokenize.doc_words`` normalized it: ``term_counts`` total mentions ·
    ``term_files`` per-file mention counts. Docs are not module-attributed,
    so there is no per-module view. The terminology and naming analyses need
    only ``term_counts``; the evidence artifact's ``doc_terms`` table also
    reads ``term_files`` for its location samples.
    """

    def __init__(self) -> None:
        self.term_counts: Counter = Counter()
        self.term_files: dict[str, Counter] = defaultdict(Counter)

    def fold(self, words: dict[str, int], rel: str) -> None:
        """Fold one doc file's word counts into every view."""
        self.term_counts.update(words)
        for term, count in words.items():
            self.term_files[term][rel] += count
