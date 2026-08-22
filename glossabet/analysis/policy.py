"""Calibrated nomination policy for the analysis heuristics.

Every number here is a judgment call that was tuned against the pinned
evaluation corpus so the nominations read well to a human: the weights order
candidates, the thresholds decide what is worth nominating, and the caps
bound the work and the report. None of them measures a probability or a
truth — a score orders a list and a gate admits a nomination, nothing more.

The pure functions beside the policies are the formulas themselves, kept
apart from the report assembly that calls them so they can be read and
tested on their own. The defaults are frozen; a caller that wants different
calibration passes its own policy object.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class TerminologyPolicy:
    """Calibration of the register, layer, synonym, and overload analyses."""

    # Pairwise work is bounded to the most frequent eligible domain tokens.
    pair_top_n: int = 150
    # Synonym nomination gates. The pinned corpus found only false
    # sibling-field nominations below 0.55 after the file/pattern gates, so
    # the floor is aligned with drift's lowest "moderate" signal.
    synonym_min_similarity: float = 0.55
    synonym_max_co_occurrence_rate: float = 0.2
    synonym_max_file_overlap: float = 0.2
    synonym_min_shared_contexts: int = 2
    synonym_min_shared_patterns: int = 2
    synonym_report_cap: int = 20
    # Overload (context dispersion) nomination.
    overload_min_modules: int = 3
    overload_min_dispersion: float = 0.8
    overload_report_cap: int = 10
    overload_module_analysis_cap: int = 50
    overload_module_display_cap: int = 4
    # Detail samples shown per nomination.
    shared_context_sample: int = 5
    shared_pattern_sample: int = 5
    module_context_sample: int = 5
    # Register and layer report caps.
    register_affix_cap: int = 8
    layer_cap: int = 10


DEFAULT_TERMINOLOGY_POLICY = TerminologyPolicy()


@dataclass(frozen=True)
class ImportancePolicy:
    """Calibration of the module and term naming-candidate scores."""

    module_candidate_cap: int = 10
    term_candidate_cap: int = 15
    # A term needs repository breadth before naming importance applies.
    term_min_module_spread: int = 2
    # Module score terms.
    module_importer_weight: float = 3
    module_code_file_log_weight: float = 2
    module_import_count_log_weight: float = 1
    module_doc_mention_log_weight: float = 2
    # Term score terms.
    term_module_spread_weight: float = 2
    term_use_count_log_ceiling: int = 100
    term_doc_mention_log_weight: float = 2
    term_compound_diversity_weight: float = 8
    term_patterns_per_file_weight: float = 6
    term_compound_density_weight: float = 4
    # A term that literally names a source file is anchored in the codebase.
    source_unit_anchor_weight: float = 15


DEFAULT_IMPORTANCE_POLICY = ImportancePolicy()


# --- terminology formulas ---------------------------------------------------


def inverse_frequency_weight(count: int) -> float:
    """Context weight for a token seen ``count`` times: a ubiquitous context
    token (a repo's "term"/"prop") says little about which two terms are
    parallel, so it must not dominate the similarity."""
    return 1.0 / (1.0 + math.log1p(count))


def weighted_cosine(
    counts_a: Counter[str],
    counts_b: Counter[str],
    exclude: set[str],
    weight: Callable[[str], float],
) -> float:
    """Cosine similarity of two context-count vectors under ``weight``,
    ignoring the ``exclude`` keys (the pair itself)."""
    keys = (set(counts_a) | set(counts_b)) - exclude
    dot = sum(counts_a.get(k, 0) * counts_b.get(k, 0) * weight(k) ** 2 for k in keys)
    if not dot:
        return 0.0
    na = math.sqrt(sum((v * weight(k)) ** 2 for k, v in counts_a.items() if k in keys))
    nb = math.sqrt(sum((v * weight(k)) ** 2 for k, v in counts_b.items() if k in keys))
    return dot / (na * nb)


def co_occurrence_rate(direct: int, count_a: int, count_b: int) -> float:
    """How often the pair appears side by side, relative to the rarer term."""
    return direct / max(1, min(count_a, count_b))


def file_overlap_rate(files_a: set[str], files_b: set[str]) -> float:
    """Share of the rarer term's files that also hold the other term."""
    return len(files_a & files_b) / max(1, min(len(files_a), len(files_b)))


def related_not_synonymous(co_rate: float, policy: TerminologyPolicy) -> bool:
    """Frequent direct co-occurrence (``payment_service``) marks a pair as
    related rather than parallel."""
    return co_rate > policy.synonym_max_co_occurrence_rate


def colocated(file_overlap: float, policy: TerminologyPolicy) -> bool:
    """Sibling fields and related concepts share files; a rename usually
    spreads between old and new files, so heavy colocation is evidence
    against synonymy."""
    return file_overlap > policy.synonym_max_file_overlap


def has_parallel_patterns(shared_patterns: int, policy: TerminologyPolicy) -> bool:
    """Context similarity alone confuses dimensions such as min/duration;
    exact substitution shapes (``job_queue``/``task_queue``) are required."""
    return shared_patterns >= policy.synonym_min_shared_patterns


def has_shared_contexts(shared_contexts: int, policy: TerminologyPolicy) -> bool:
    """One shared context is coincidence, not a parallel vocabulary."""
    return shared_contexts >= policy.synonym_min_shared_contexts


def similar_enough(similarity: float, policy: TerminologyPolicy) -> bool:
    return similarity >= policy.synonym_min_similarity


def context_dispersion(context_sets: Sequence[set[str]]) -> float | None:
    """One minus the mean pairwise Jaccard similarity of the per-module
    context sets, rounded to three places; ``None`` when no pair of sets has
    anything to compare."""
    similarities = [
        len(left & right) / len(left | right)
        for left, right in combinations(context_sets, 2)
        if left | right
    ]
    if not similarities:
        return None
    return round(1.0 - (sum(similarities) / len(similarities)), 3)


def wide_enough(module_count: int, policy: TerminologyPolicy) -> bool:
    """A term must reach this many modules before dispersion is measured."""
    return module_count >= policy.overload_min_modules


def is_divergent(dispersion: float, policy: TerminologyPolicy) -> bool:
    """Disjoint enough across modules to nominate as an overload."""
    return dispersion >= policy.overload_min_dispersion


# --- importance formulas ----------------------------------------------------


def module_score(
    *,
    importers: int,
    code_files: int,
    import_count: int,
    doc_mentions: int,
    policy: ImportancePolicy,
) -> float:
    """Ordering score for a module naming candidate (unrounded)."""
    return (
        importers * policy.module_importer_weight
        + math.log1p(code_files) * policy.module_code_file_log_weight
        + math.log1p(import_count) * policy.module_import_count_log_weight
        + math.log1p(doc_mentions) * policy.module_doc_mention_log_weight
    )


def compound_density(compound_uses: int, use_count: int) -> float:
    """Compound uses per use of the term."""
    return compound_uses / max(1, use_count)


def compound_diversity(distinct_compounds: int, use_count: int) -> float:
    """Distinct compound patterns, damped by the square root of use count."""
    return distinct_compounds / math.sqrt(max(1, use_count))


def has_repository_breadth(module_spread: int, policy: ImportancePolicy) -> bool:
    return module_spread >= policy.term_min_module_spread


def term_score(
    *,
    module_spread: int,
    use_count: int,
    doc_mentions: int,
    compound_diversity: float,
    patterns_per_file: float,
    compound_density: float,
    source_units_named: int,
    policy: ImportancePolicy,
) -> float:
    """Ordering score for a term naming candidate (unrounded)."""
    return (
        module_spread * policy.term_module_spread_weight
        + math.log1p(min(use_count, policy.term_use_count_log_ceiling))
        + math.log1p(doc_mentions) * policy.term_doc_mention_log_weight
        + compound_diversity * policy.term_compound_diversity_weight
        + patterns_per_file * policy.term_patterns_per_file_weight
        + compound_density * policy.term_compound_density_weight
        + min(source_units_named, 1) * policy.source_unit_anchor_weight
    )
