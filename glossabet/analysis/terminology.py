"""Terminology intelligence: register statistics, layer comparison, and
synonym/overload nominations.

Everything here is a nomination with evidence, never a verdict — the LLM and
the human judge. All pairwise work is bounded to the top-N vocabulary
and every bound is reported in the output.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from itertools import combinations
from typing import TypedDict

from glossabet.analysis.evidence_types import (
    AffixRecord,
    ContextDispersionSection,
    DispersionRecord,
    LayersSection,
    OverloadCandidate,
    OverloadCandidatesSection,
    OverloadModuleRecord,
    RegisterSection,
    SynonymCandidate,
    SynonymCandidatesSection,
    TerminologyAnalysis,
)
from glossabet.analysis.policy import (
    DEFAULT_TERMINOLOGY_POLICY,
    TerminologyPolicy,
    co_occurrence_rate,
    colocated,
    context_dispersion,
    file_overlap_rate,
    has_parallel_patterns,
    has_shared_contexts,
    inverse_frequency_weight,
    is_divergent,
    related_not_synonymous,
    similar_enough,
    weighted_cosine,
    wide_enough,
)
from glossabet.analysis.vocabulary import (
    MODULE_CONTEXT_ANALYSIS_CAP,
    ProductionVocabulary,
)
from glossabet.corpus.tokenize import (
    STRUCTURED_IDENTIFIER_STYLES,
    TOKEN_ORIGIN_DOMAIN,
    TOKEN_ORIGIN_LANGUAGE,
    identifier_style,
    tokenize_identifier,
)
from glossabet.runtime.coverage import (
    CoverageLedger,
    capped_collection,
    coverage_ledger,
    coverage_reasons,
)

# The calibrated defaults, named for readers and tests; the analysis itself
# reads the policy object it was given (``analysis.policy``).
PAIR_TOP_N = DEFAULT_TERMINOLOGY_POLICY.pair_top_n
OVERLOAD_MIN_MODULES = DEFAULT_TERMINOLOGY_POLICY.overload_min_modules
OVERLOAD_MIN_DISPERSION = DEFAULT_TERMINOLOGY_POLICY.overload_min_dispersion
OVERLOAD_MODULE_ANALYSIS_CAP = DEFAULT_TERMINOLOGY_POLICY.overload_module_analysis_cap


@dataclass
class _RegisterTally:
    """Which identifier spellings the house register admits, and why."""
    styles: Counter[str] = field(default_factory=Counter)
    token_counts_dist: Counter[str] = field(default_factory=Counter)
    suffixes: Counter[str] = field(default_factory=Counter)
    prefixes: Counter[str] = field(default_factory=Counter)
    used_by_reason: Counter[str] = field(default_factory=lambda: Counter({
        "structurally_styled": 0,
        "corroborated_flat": 0,
    }))
    excluded_by_reason: Counter[str] = field(default_factory=lambda: Counter({
        "no_lexical_tokens": 0,
        "language_tagged_flat": 0,
        "prose_dominated_flat": 0,
    }))

    def count_affixes(self, tokens: list[str]) -> None:
        if len(tokens) >= 2:
            self.suffixes[tokens[-1]] += 1
            self.prefixes[tokens[0]] += 1


def _register_tally(
    identifier_counts: Counter[str],
    doc_term_counts: Counter[str],
    token_origins: dict[str, str],
) -> _RegisterTally:
    tally = _RegisterTally()
    for name, code_count in identifier_counts.items():
        tokens = tokenize_identifier(name)
        if not tokens:
            tally.excluded_by_reason["no_lexical_tokens"] += 1
            continue

        style = identifier_style(name)
        if style in STRUCTURED_IDENTIFIER_STYLES and len(tokens) >= 2:
            # These spellings carry code structure in the spelling itself;
            # a multi-token snake/camel/Pascal spelling cannot be ordinary
            # prose. A one-token capitalized or uppercase word remains flat
            # and must pass the corroboration gates below.
            tally.used_by_reason["structurally_styled"] += 1
            tally.styles[style] += 1
            bucket = str(len(tokens)) if len(tokens) <= 3 else "4+"
            tally.token_counts_dist[bucket] += 1
            tally.count_affixes(tokens)
            continue

        if any(
            token_origins.get(token, TOKEN_ORIGIN_DOMAIN)
            == TOKEN_ORIGIN_LANGUAGE
            for token in tokens
        ):
            tally.excluded_by_reason["language_tagged_flat"] += 1
            continue

        # Flat spellings carry no structural evidence that they are code.
        # A multi-token flat form (for example a language-specific hyphenated
        # name) uses the strongest constituent document count rather than the
        # sum, so one prose occurrence is not multiplied by token count.
        doc_count = max(
            (doc_term_counts.get(token, 0) for token in set(tokens)),
            default=0,
        )
        if doc_count > code_count:
            tally.excluded_by_reason["prose_dominated_flat"] += 1
            continue

        tally.used_by_reason["corroborated_flat"] += 1
        tally.count_affixes(tokens)
    return tally


def _pct(counter: Counter[str], total: int) -> dict[str, float]:
    return {
        k: round(100.0 * v / total, 1)
        for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    } if total else {}


def _top_affixes(
    counter: Counter[str], policy: TerminologyPolicy,
) -> tuple[list[AffixRecord], CoverageLedger]:
    ranked: list[AffixRecord] = [
        {"token": token, "identifiers": count}
        for token, count in sorted(
            counter.items(), key=lambda kv: (-kv[1], kv[0])
        )
        if count >= 2
    ]
    return capped_collection(
        ranked,
        policy.register_affix_cap,
        cap_reason=(
            f"register affix display cap is {policy.register_affix_cap} items"
        ),
    )


def _register(
    identifier_counts: Counter[str],
    doc_term_counts: Counter[str],
    token_origins: dict[str, str],
    policy: TerminologyPolicy,
) -> RegisterSection:
    tally = _register_tally(identifier_counts, doc_term_counts, token_origins)
    used_by_reason = tally.used_by_reason
    excluded_by_reason = tally.excluded_by_reason
    headline_total = used_by_reason["structurally_styled"]
    used_total = sum(used_by_reason.values())
    excluded_total = sum(excluded_by_reason.values())
    suffix_items, suffix_coverage = _top_affixes(tally.suffixes, policy)
    prefix_items, prefix_coverage = _top_affixes(tally.prefixes, policy)

    return {
        # Kept for consumers of the pre-v9 field; it now means the spellings
        # admitted into the register, not every lexical scanner match.
        "unique_identifiers": used_total,
        "composition": {
            "total_spellings": len(identifier_counts),
            "used_spellings": used_total,
            "excluded_spellings": excluded_total,
            "used_by_reason": dict(used_by_reason),
            "excluded_by_reason": dict(excluded_by_reason),
        },
        "identifier_styles_pct": _pct(tally.styles, headline_total),
        "token_count_distribution_pct": _pct(
            tally.token_counts_dist, headline_total
        ),
        "common_suffix_tokens": suffix_items,
        "common_prefix_tokens": prefix_items,
        "coverage": {
            "common_suffix_tokens": suffix_coverage,
            "common_prefix_tokens": prefix_coverage,
        },
    }


def _layers(
    token_counts: Counter[str], doc_term_counts: Counter[str],
    policy: TerminologyPolicy,
) -> LayersSection:
    def top(
        counter: Counter[str], keep: Callable[[str], bool], label: str,
    ) -> tuple[list[str], CoverageLedger]:
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        items = [term for term, _ in ranked if keep(term)]
        return capped_collection(
            items,
            policy.layer_cap,
            cap_reason=f"{label} layer display cap is {policy.layer_cap} items",
        )

    shared, shared_coverage = top(
        token_counts, lambda term: term in doc_term_counts, "shared"
    )
    code_only, code_coverage = top(
        token_counts, lambda term: term not in doc_term_counts, "code-only"
    )
    doc_only, doc_coverage = top(
        doc_term_counts, lambda term: term not in token_counts, "doc-only"
    )

    return {
        "shared_top": shared,
        "code_only_top": code_only,
        "doc_only_top": doc_only,
        "coverage": {
            "shared_top": shared_coverage,
            "code_only_top": code_coverage,
            "doc_only_top": doc_coverage,
        },
    }


def _pattern_label(pattern: tuple[str, ...]) -> str:
    return "_".join(pattern)


def _synonym_candidates(top_tokens: list[str], token_counts: Counter[str],
                        token_files: Mapping[str, Counter[str]],
                        token_patterns: Mapping[str, Counter[tuple[str, ...]]],
                        neighbors: Mapping[str, Counter[str]],
                        token_coverage: CoverageLedger,
                        policy: TerminologyPolicy,
                        ) -> SynonymCandidatesSection:
    def weight(k: str) -> float:
        return inverse_frequency_weight(token_counts.get(k, 1))

    ranked: list[tuple[float, str, str, SynonymCandidate]] = []
    considered = 0
    for a, b in combinations(top_tokens, 2):
        na, nb = neighbors.get(a, Counter()), neighbors.get(b, Counter())
        if not na or not nb:
            continue
        considered += 1
        co_rate = co_occurrence_rate(
            na.get(b, 0), token_counts[a], token_counts[b]
        )
        if related_not_synonymous(co_rate, policy):
            continue
        file_overlap = file_overlap_rate(
            set(token_files.get(a, ())), set(token_files.get(b, ()))
        )
        if colocated(file_overlap, policy):
            continue
        shared_patterns = sorted(
            token_patterns.get(a, Counter()).keys()
            & token_patterns.get(b, Counter()).keys(),
            key=lambda pattern: (
                -min(token_patterns[a][pattern], token_patterns[b][pattern]),
                pattern,
            ),
        )
        if not has_parallel_patterns(len(shared_patterns), policy):
            continue
        shared = sorted(
            (k for k in na.keys() & nb.keys() if k not in (a, b)),
            key=lambda k: (-min(na[k], nb[k]), k),
        )
        if not has_shared_contexts(len(shared), policy):
            continue
        similarity = weighted_cosine(na, nb, exclude={a, b}, weight=weight)
        if not similar_enough(similarity, policy):
            continue
        shared_items, shared_coverage = capped_collection(
            shared,
            policy.shared_context_sample,
            cap_reason=(
                f"shared-context display cap is {policy.shared_context_sample} items"
            ),
        )
        pattern_labels = [_pattern_label(pattern) for pattern in shared_patterns]
        pattern_items, pattern_coverage = capped_collection(
            pattern_labels,
            policy.shared_pattern_sample,
            cap_reason=(
                f"shared-pattern display cap is {policy.shared_pattern_sample} items"
            ),
        )
        ranked.append((round(similarity, 3), a, b, {
            "a": a,
            "b": b,
            "similarity": round(similarity, 3),
            "file_overlap_rate": round(file_overlap, 3),
            "shared_contexts": shared_items,
            "shared_patterns": pattern_items,
            "coverage": {
                "shared_contexts": shared_coverage,
                "shared_patterns": pattern_coverage,
            },
        }))
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    items = [row[3] for row in ranked]
    kept, coverage = capped_collection(
        items,
        policy.synonym_report_cap,
        cap_reason=(
            f"synonym-candidate detail cap is {policy.synonym_report_cap} items"
        ),
        total_items_exact=token_coverage["complete"],
        incomplete_reasons=coverage_reasons(
            token_coverage, "eligible token input"
        ),
    )
    return {
        "items": kept,
        "considered_pairs": considered,
        "dropped_items": coverage["dropped_items"],
        "coverage": coverage,
    }


class _DispersionProfile(TypedDict):
    """Internal: a ``DispersionRecord`` plus the complete per-module
    context sets overload detail is built from."""

    term: str
    dispersion: float
    module_count: int
    divergent: bool
    _per_module: dict[str, set[str]]


def _context_dispersion(
    top_tokens: list[str],
    module_neighbor_sets: Mapping[str, Mapping[str, set[str]]],
    module_neighbor_truncated: set[tuple[str, str]],
    token_coverage: CoverageLedger,
    policy: TerminologyPolicy,
) -> tuple[list[_DispersionProfile], ContextDispersionSection]:
    """Measure bounded cross-module context dispersion once.

    Internal profiles retain complete context sets for overload detail. The
    public projection keeps only plain numbers for importance consumers.
    """
    profiles: list[_DispersionProfile] = []
    wide_terms = 0
    truncated_contexts = 0
    overfull_module_terms = 0
    for token in top_tokens:
        per_module = {
            m: s for m, s in module_neighbor_sets.get(token, {}).items() if s
        }
        if not wide_enough(len(per_module), policy):
            continue
        wide_terms += 1
        token_truncated = sorted(
            module
            for module in per_module
            if (token, module) in module_neighbor_truncated
        )
        if token_truncated:
            # A capped context set can change the dispersion calculation in
            # either direction.  Skip the nomination instead of turning a
            # partial sample into a seemingly complete collision signal.
            truncated_contexts += len(token_truncated)
            continue
        if len(per_module) > policy.overload_module_analysis_cap:
            # Pairwise dispersion is quadratic in the number of modules.
            # Keep that work bounded and treat the skipped nomination as
            # unknown rather than drawing a conclusion from a module sample.
            overfull_module_terms += 1
            continue
        dispersion = context_dispersion(list(per_module.values()))
        if dispersion is None:
            continue  # unreachable: several non-empty sets always compare
        profiles.append({
            "term": token,
            "dispersion": dispersion,
            "module_count": len(per_module),
            "divergent": is_divergent(dispersion, policy),
            "_per_module": per_module,
        })

    profiles.sort(key=lambda item: item["term"])
    incomplete_reasons = coverage_reasons(
        token_coverage, "eligible token input"
    )
    if truncated_contexts:
        incomplete_reasons.append(
            f"{truncated_contexts} term/module context set(s) reached the "
            f"{MODULE_CONTEXT_ANALYSIS_CAP}-token analysis cap"
        )
    if overfull_module_terms:
        incomplete_reasons.append(
            f"{overfull_module_terms} term(s) exceeded the "
            f"{policy.overload_module_analysis_cap}-module overload analysis cap"
        )
    coverage = coverage_ledger(
        wide_terms,
        len(profiles),
        total_items_exact=token_coverage["complete"],
        reasons=incomplete_reasons,
    )
    public_items: list[DispersionRecord] = [
        {
            "term": item["term"],
            "dispersion": item["dispersion"],
            "modules": item["module_count"],
            "divergent": item["divergent"],
        }
        for item in profiles
    ]
    return profiles, {
        "items": public_items,
        "dropped_items": coverage["dropped_items"],
        "coverage": coverage,
    }


def _overload_candidates(
    dispersion_profiles: list[_DispersionProfile],
    token_modules: Mapping[str, Counter[str]],
    dispersion_coverage: CoverageLedger,
    policy: TerminologyPolicy,
) -> OverloadCandidatesSection:
    items: list[OverloadCandidate] = []
    for profile in dispersion_profiles:
        if not profile["divergent"]:
            continue
        token = profile["term"]
        dispersion = profile["dispersion"]
        per_module = profile["_per_module"]
        modules = sorted(
            per_module,
            key=lambda m: (-token_modules[token].get(m, 0), m),
        )
        module_items: list[OverloadModuleRecord] = []
        for module in modules:
            contexts = sorted(per_module[module])
            context_items, context_coverage = capped_collection(
                contexts,
                policy.module_context_sample,
                cap_reason=(
                    f"module-context display cap is {policy.module_context_sample} items"
                ),
            )
            module_items.append({
                "path": module,
                "contexts": context_items,
                "coverage": {"contexts": context_coverage},
            })
        kept_modules, module_coverage = capped_collection(
            module_items,
            policy.overload_module_display_cap,
            cap_reason=(
                "overload-candidate module display cap is "
                f"{policy.overload_module_display_cap} items"
            ),
        )
        items.append({
            "term": token,
            "dispersion": dispersion,
            "modules": kept_modules,
            "coverage": {"modules": module_coverage},
        })
    items.sort(key=lambda i: (-i["dispersion"], i["term"]))
    kept, coverage = capped_collection(
        items,
        policy.overload_report_cap,
        cap_reason=(
            f"overload-candidate detail cap is {policy.overload_report_cap} items"
        ),
        total_items_exact=dispersion_coverage["complete"],
        incomplete_reasons=coverage_reasons(dispersion_coverage),
    )
    return {
        "items": kept,
        "dropped_items": coverage["dropped_items"],
        "coverage": coverage,
    }


def build_terminology(
    vocabulary: ProductionVocabulary,
    doc_term_counts: Counter[str],
    *,
    policy: TerminologyPolicy | None = None,
) -> TerminologyAnalysis:
    """House-register statistics, layers, synonym/overload candidates, and
    context dispersion for one scan's production vocabulary, under the
    calibrated nomination ``policy`` (the module default when omitted)."""
    if policy is None:
        policy = DEFAULT_TERMINOLOGY_POLICY
    identifier_counts = vocabulary.identifier_counts
    token_counts = vocabulary.token_counts
    token_files = vocabulary.token_files
    token_modules = vocabulary.token_modules
    token_patterns = vocabulary.token_patterns
    neighbors = vocabulary.neighbors
    module_neighbor_sets = vocabulary.module_neighbor_sets
    module_neighbor_truncated = vocabulary.module_neighbor_truncated
    token_origins = vocabulary.token_origins
    language_tokens_excluded = vocabulary.language_token_count()
    eligibility_reasons = []
    if language_tokens_excluded:
        eligibility_reasons.append(
            f"{language_tokens_excluded} language-origin vocabulary token(s) "
            "excluded before terminology eligibility"
        )
    ranked = sorted(
        (
            (term, count)
            for term, count in token_counts.items()
            if token_origins.get(term, TOKEN_ORIGIN_DOMAIN)
            == TOKEN_ORIGIN_DOMAIN
        ),
        key=lambda kv: (-kv[1], kv[0]),
    )
    eligible_tokens = [term for term, count in ranked if count >= 2]
    top_tokens, token_coverage = capped_collection(
        eligible_tokens,
        policy.pair_top_n,
        cap_reason=(
            f"terminology analysis cap is the top {policy.pair_top_n} eligible tokens"
        ),
        incomplete_reasons=eligibility_reasons,
    )
    dispersion_profiles, dispersion_section = _context_dispersion(
        top_tokens,
        module_neighbor_sets,
        module_neighbor_truncated,
        token_coverage,
        policy,
    )
    return {
        "considered_tokens": len(top_tokens),
        "vocabulary_size": len(token_counts),
        "domain_vocabulary_size": len(token_counts) - language_tokens_excluded,
        "language_vocabulary_size": language_tokens_excluded,
        "coverage": {"eligible_tokens": token_coverage},
        "register": _register(
            identifier_counts, doc_term_counts, token_origins, policy
        ),
        "layers": _layers(token_counts, doc_term_counts, policy),
        "synonym_candidates": _synonym_candidates(
            top_tokens, token_counts, token_files, token_patterns, neighbors,
            token_coverage, policy,
        ),
        "context_dispersion": dispersion_section,
        "overload_candidates": _overload_candidates(
            dispersion_profiles, token_modules,
            dispersion_section["coverage"], policy,
        ),
    }
