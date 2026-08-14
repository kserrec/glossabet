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

from glossarize.tokenize import tokenize_identifier

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
SHARED_CONTEXT_SAMPLE = 5
SHARED_PATTERN_SAMPLE = 5
MODULE_CONTEXT_SAMPLE = 5
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

    def top_affixes(counter: Counter) -> list[dict]:
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return [
            {"token": t, "identifiers": c}
            for t, c in ranked[:REGISTER_AFFIX_CAP] if c >= 2
        ]

    return {
        "unique_identifiers": total,
        "identifier_styles_pct": pct(styles),
        "token_count_distribution_pct": pct(token_counts_dist),
        "common_suffix_tokens": top_affixes(suffixes),
        "common_prefix_tokens": top_affixes(prefixes),
    }


def _layers(token_counts: Counter, doc_term_counts: Counter) -> dict:
    def top(counter: Counter, keep) -> list[str]:
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return [t for t, _ in ranked if keep(t)][:LAYER_CAP]

    return {
        "shared_top": top(token_counts, lambda t: t in doc_term_counts),
        "code_only_top": top(token_counts, lambda t: t not in doc_term_counts),
        "doc_only_top": top(doc_term_counts, lambda t: t not in token_counts),
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
                        neighbors: dict) -> dict:
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
        items.append({
            "a": a,
            "b": b,
            "similarity": round(similarity, 3),
            "file_overlap_rate": round(file_overlap, 3),
            "shared_contexts": shared[:SHARED_CONTEXT_SAMPLE],
            "shared_patterns": [
                _pattern_label(pattern)
                for pattern in shared_patterns[:SHARED_PATTERN_SAMPLE]
            ],
        })
    items.sort(key=lambda i: (-i["similarity"], i["a"], i["b"]))
    return {
        "items": items[:SYNONYM_REPORT_CAP],
        "considered_pairs": considered,
        "dropped_items": max(0, len(items) - SYNONYM_REPORT_CAP),
    }


def _overload_candidates(top_tokens: list[str], token_modules: dict,
                         module_neighbor_sets: dict) -> dict:
    items = []
    for token in top_tokens:
        per_module = {
            m: s for m, s in module_neighbor_sets.get(token, {}).items() if s
        }
        if len(per_module) < OVERLOAD_MIN_MODULES:
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
        )[:4]
        items.append({
            "term": token,
            "dispersion": dispersion,
            "modules": [
                {"path": m, "contexts": sorted(per_module[m])[:MODULE_CONTEXT_SAMPLE]}
                for m in modules
            ],
        })
    items.sort(key=lambda i: (-i["dispersion"], i["term"]))
    return {
        "items": items[:OVERLOAD_REPORT_CAP],
        "dropped_items": max(0, len(items) - OVERLOAD_REPORT_CAP),
    }


def build_terminology(identifier_counts: Counter, token_counts: Counter,
                      token_files: dict, token_modules: dict,
                      token_patterns: dict, neighbors: dict,
                      module_neighbor_sets: dict,
                      doc_term_counts: Counter) -> dict:
    ranked = sorted(token_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top_tokens = [t for t, c in ranked[:PAIR_TOP_N] if c >= 2]
    return {
        "considered_tokens": len(top_tokens),
        "vocabulary_size": len(token_counts),
        "register": _register(identifier_counts),
        "layers": _layers(token_counts, doc_term_counts),
        "synonym_candidates": _synonym_candidates(
            top_tokens, token_counts, token_files, token_patterns, neighbors
        ),
        "overload_candidates": _overload_candidates(
            top_tokens, token_modules, module_neighbor_sets
        ),
    }
