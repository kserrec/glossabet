"""Terminology intelligence: register statistics, layer comparison, and
synonym/overload nominations.

Everything here is a nomination with evidence, never a verdict — the LLM and
the human judge. All pairwise work is bounded to the top-N vocabulary
(principle 12) and the bound is reported in the output.
"""

from __future__ import annotations

import math
from collections import Counter
from itertools import combinations

from glossabet.coverage import (
    capped_collection,
    coverage_reasons,
)
from glossabet.tokenize import (
    TOKEN_ORIGIN_DOMAIN,
    TOKEN_ORIGIN_LANGUAGE,
    tokenize_identifier,
)

PAIR_TOP_N = 150
# Phase 15's pinned corpus found only false sibling-field nominations below
# 0.55 after the file/pattern gates. Keep the nomination floor aligned with
# drift's lowest "moderate" signal instead of emitting weak 0.4 candidates.
SYNONYM_MIN_SIMILARITY = 0.55
SYNONYM_MAX_CO_RATE = 0.2
SYNONYM_MAX_FILE_OVERLAP = 0.2
SYNONYM_MIN_SHARED_CONTEXTS = 2
SYNONYM_MIN_SHARED_PATTERNS = 2
SYNONYM_REPORT_CAP = 20
OVERLOAD_MIN_MODULES = 3
OVERLOAD_MIN_DISPERSION = 0.8
OVERLOAD_REPORT_CAP = 10
OVERLOAD_MODULE_ANALYSIS_CAP = 50
SHARED_CONTEXT_SAMPLE = 5
SHARED_PATTERN_SAMPLE = 5
MODULE_CONTEXT_SAMPLE = 5
MODULE_CONTEXT_ANALYSIS_CAP = 30
REGISTER_AFFIX_CAP = 8
LAYER_CAP = 10


def _classify_style(name: str) -> str:
    core = name.strip("_")
    if "_" in core:
        return "UPPER_SNAKE" if core.isupper() else "snake_case"
    if core.isupper():
        return "upper"
    if core[:1].isupper():
        return "PascalCase" if any(c.islower() for c in core) else "upper"
    if any(c.isupper() for c in core):
        return "camelCase"
    return "flat"


def _register(identifier_counts: Counter) -> dict:
    styles: Counter = Counter()
    token_counts_dist: Counter = Counter()
    suffixes: Counter = Counter()
    prefixes: Counter = Counter()
    total = 0
    for name in identifier_counts:
        tokens = tokenize_identifier(name)
        if not tokens:
            continue
        total += 1
        styles[_classify_style(name)] += 1
        bucket = str(len(tokens)) if len(tokens) <= 3 else "4+"
        token_counts_dist[bucket] += 1
        if len(tokens) >= 2:
            suffixes[tokens[-1]] += 1
            prefixes[tokens[0]] += 1

    def pct(counter: Counter) -> dict:
        return {
            k: round(100.0 * v / total, 1)
            for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        } if total else {}

    def top_affixes(counter: Counter) -> tuple[list[dict], dict]:
        ranked = [
            {"token": token, "identifiers": count}
            for token, count in sorted(
                counter.items(), key=lambda kv: (-kv[1], kv[0])
            )
            if count >= 2
        ]
        return capped_collection(
            ranked,
            REGISTER_AFFIX_CAP,
            cap_reason=(
                f"register affix display cap is {REGISTER_AFFIX_CAP} items"
            ),
        )

    suffix_items, suffix_coverage = top_affixes(suffixes)
    prefix_items, prefix_coverage = top_affixes(prefixes)

    return {
        "unique_identifiers": total,
        "identifier_styles_pct": pct(styles),
        "token_count_distribution_pct": pct(token_counts_dist),
        "common_suffix_tokens": suffix_items,
        "common_prefix_tokens": prefix_items,
        "coverage": {
            "common_suffix_tokens": suffix_coverage,
            "common_prefix_tokens": prefix_coverage,
        },
    }


def _layers(token_counts: Counter, doc_term_counts: Counter) -> dict:
    def top(counter: Counter, keep, label: str) -> tuple[list[str], dict]:
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        items = [term for term, _ in ranked if keep(term)]
        return capped_collection(
            items,
            LAYER_CAP,
            cap_reason=f"{label} layer display cap is {LAYER_CAP} items",
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


def _cosine(ca: Counter, cb: Counter, exclude: set, weight) -> float:
    keys = (set(ca) | set(cb)) - exclude
    dot = sum(ca.get(k, 0) * cb.get(k, 0) * weight(k) ** 2 for k in keys)
    if not dot:
        return 0.0
    na = math.sqrt(sum((v * weight(k)) ** 2 for k, v in ca.items() if k in keys))
    nb = math.sqrt(sum((v * weight(k)) ** 2 for k, v in cb.items() if k in keys))
    return dot / (na * nb)


def _pattern_label(pattern: tuple[str, ...]) -> str:
    return "_".join(pattern)


def _synonym_candidates(top_tokens: list[str], token_counts: Counter,
                        token_files: dict, token_patterns: dict,
                        neighbors: dict, token_coverage: dict) -> dict:
    # Inverse-frequency weighting: a ubiquitous context token (a repo's
    # "term"/"prop") says little about which two terms are parallel, so it
    # must not dominate the similarity.
    def weight(k: str) -> float:
        return 1.0 / (1.0 + math.log1p(token_counts.get(k, 1)))

    items = []
    considered = 0
    for a, b in combinations(top_tokens, 2):
        na, nb = neighbors.get(a, Counter()), neighbors.get(b, Counter())
        if not na or not nb:
            continue
        considered += 1
        # Frequent direct co-occurrence means related-not-synonymous
        # (payment_service): skip those pairs.
        co_rate = na.get(b, 0) / max(1, min(token_counts[a], token_counts[b]))
        if co_rate > SYNONYM_MAX_CO_RATE:
            continue
        files_a = set(token_files.get(a, ()))
        files_b = set(token_files.get(b, ()))
        file_overlap = len(files_a & files_b) / max(1, min(len(files_a), len(files_b)))
        # Sibling fields and related concepts commonly share both a file and
        # surrounding words. A rename usually spreads between old/new files;
        # heavy colocation is therefore evidence against synonymy.
        if file_overlap > SYNONYM_MAX_FILE_OVERLAP:
            continue
        shared_patterns = sorted(
            token_patterns.get(a, Counter()).keys()
            & token_patterns.get(b, Counter()).keys(),
            key=lambda pattern: (
                -min(token_patterns[a][pattern], token_patterns[b][pattern]),
                pattern,
            ),
        )
        # Context similarity alone confuses dimensions such as min/duration.
        # Require two exact substitution shapes (`job_queue`/`task_queue`,
        # `run_job`/`run_task`) before nominating a parallel vocabulary.
        if len(shared_patterns) < SYNONYM_MIN_SHARED_PATTERNS:
            continue
        shared = sorted(
            (k for k in na.keys() & nb.keys() if k not in (a, b)),
            key=lambda k: (-min(na[k], nb[k]), k),
        )
        # One shared context is coincidence, not a parallel vocabulary.
        if len(shared) < SYNONYM_MIN_SHARED_CONTEXTS:
            continue
        similarity = _cosine(na, nb, exclude={a, b}, weight=weight)
        if similarity < SYNONYM_MIN_SIMILARITY:
            continue
        shared_items, shared_coverage = capped_collection(
            shared,
            SHARED_CONTEXT_SAMPLE,
            cap_reason=(
                f"shared-context display cap is {SHARED_CONTEXT_SAMPLE} items"
            ),
        )
        pattern_labels = [_pattern_label(pattern) for pattern in shared_patterns]
        pattern_items, pattern_coverage = capped_collection(
            pattern_labels,
            SHARED_PATTERN_SAMPLE,
            cap_reason=(
                f"shared-pattern display cap is {SHARED_PATTERN_SAMPLE} items"
            ),
        )
        items.append({
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
        })
    items.sort(key=lambda i: (-i["similarity"], i["a"], i["b"]))
    kept, coverage = capped_collection(
        items,
        SYNONYM_REPORT_CAP,
        cap_reason=(
            f"synonym-candidate detail cap is {SYNONYM_REPORT_CAP} items"
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


def _overload_candidates(top_tokens: list[str], token_modules: dict,
                         module_neighbor_sets: dict,
                         module_neighbor_truncated: set[tuple[str, str]],
                         token_coverage: dict) -> dict:
    items = []
    truncated_contexts = 0
    overfull_module_terms = 0
    for token in top_tokens:
        per_module = {
            m: s for m, s in module_neighbor_sets.get(token, {}).items() if s
        }
        if len(per_module) < OVERLOAD_MIN_MODULES:
            continue
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
        if len(per_module) > OVERLOAD_MODULE_ANALYSIS_CAP:
            # Pairwise dispersion is quadratic in the number of modules.
            # Keep that work bounded and treat the skipped nomination as
            # unknown rather than drawing a conclusion from a module sample.
            overfull_module_terms += 1
            continue
        sets = list(per_module.values())
        sims = [
            len(x & y) / len(x | y)
            for x, y in combinations(sets, 2)
        ]
        dispersion = round(1.0 - (sum(sims) / len(sims)), 3)
        if dispersion < OVERLOAD_MIN_DISPERSION:
            continue
        modules = sorted(
            per_module,
            key=lambda m: (-token_modules[token].get(m, 0), m),
        )
        module_items = []
        for module in modules:
            contexts = sorted(per_module[module])
            context_items, context_coverage = capped_collection(
                contexts,
                MODULE_CONTEXT_SAMPLE,
                cap_reason=(
                    f"module-context display cap is {MODULE_CONTEXT_SAMPLE} items"
                ),
            )
            module_items.append({
                "path": module,
                "contexts": context_items,
                "coverage": {"contexts": context_coverage},
            })
        kept_modules, module_coverage = capped_collection(
            module_items,
            4,
            cap_reason="overload-candidate module display cap is 4 items",
        )
        items.append({
            "term": token,
            "dispersion": dispersion,
            "modules": kept_modules,
            "coverage": {"modules": module_coverage},
        })
    items.sort(key=lambda i: (-i["dispersion"], i["term"]))
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
            f"{OVERLOAD_MODULE_ANALYSIS_CAP}-module overload analysis cap"
        )
    kept, coverage = capped_collection(
        items,
        OVERLOAD_REPORT_CAP,
        cap_reason=(
            f"overload-candidate detail cap is {OVERLOAD_REPORT_CAP} items"
        ),
        total_items_exact=(
            token_coverage["complete"]
            and truncated_contexts == 0
            and overfull_module_terms == 0
        ),
        incomplete_reasons=incomplete_reasons,
    )
    return {
        "items": kept,
        "dropped_items": coverage["dropped_items"],
        "coverage": coverage,
    }


def build_terminology(identifier_counts: Counter, token_counts: Counter,
                      token_files: dict, token_modules: dict,
                      token_patterns: dict, neighbors: dict,
                      module_neighbor_sets: dict,
                      doc_term_counts: Counter,
                      module_neighbor_truncated: set[tuple[str, str]] | None = None,
                      token_origins: dict[str, str] | None = None,
                      ) -> dict:
    token_origins = token_origins or {}
    language_tokens_excluded = sum(
        token_origins.get(term) == TOKEN_ORIGIN_LANGUAGE
        for term in token_counts
    )
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
        PAIR_TOP_N,
        cap_reason=(
            f"terminology analysis cap is the top {PAIR_TOP_N} eligible tokens"
        ),
        incomplete_reasons=eligibility_reasons,
    )
    return {
        "considered_tokens": len(top_tokens),
        "vocabulary_size": len(token_counts),
        "domain_vocabulary_size": len(token_counts) - language_tokens_excluded,
        "language_vocabulary_size": language_tokens_excluded,
        "coverage": {"eligible_tokens": token_coverage},
        "register": _register(identifier_counts),
        "layers": _layers(token_counts, doc_term_counts),
        "synonym_candidates": _synonym_candidates(
            top_tokens, token_counts, token_files, token_patterns, neighbors,
            token_coverage,
        ),
        "overload_candidates": _overload_candidates(
            top_tokens, token_modules, module_neighbor_sets,
            module_neighbor_truncated or set(), token_coverage,
        ),
    }
