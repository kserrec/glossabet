"""Calibrated nomination policy for drift and validation findings.

These thresholds decide which glossary-versus-evidence observations become
findings and how strong a signal each is labelled. They are judgment calls
tuned on the pinned corpus, not measured probabilities; the signal strength
orders a report for a human, it does not assert a fact. Reconciliation-only
thresholds live here, in the glossary layer, so the analysis layer stays
below them; the overload thresholds default to the terminology policy's so
drift re-derives scoped dispersion with the same calibration.
"""

from __future__ import annotations

from dataclasses import dataclass

from glossabet.analysis.policy import DEFAULT_TERMINOLOGY_POLICY


@dataclass(frozen=True)
class DriftPolicy:
    """Calibration of the drift findings."""

    # parallel-term: cosine similarity bands for the signal label.
    parallel_strong_min_similarity: float = 0.7
    parallel_moderate_min_similarity: float = 0.55
    # canonical-fading: at most this many code uses, with no doc mention,
    # reads as "fading"; zero uses reads as "absent from code".
    fading_max_count: int = 2
    # canonical-overloaded: the scoped re-derivation of dispersion uses the
    # terminology calibration; this is the band for a "strong" signal.
    overload_min_modules: int = DEFAULT_TERMINOLOGY_POLICY.overload_min_modules
    overload_min_dispersion: float = DEFAULT_TERMINOLOGY_POLICY.overload_min_dispersion
    overload_strong_min_dispersion: float = 0.95


DEFAULT_DRIFT_POLICY = DriftPolicy()


@dataclass(frozen=True)
class ReconciliationPolicy:
    """Calibration of the validation findings."""

    # fragmentation: a canonical term spanning this many modules.
    fragmentation_min_modules: int = 5
    # overloaded-structural-region: a group strongly matching this many
    # distinct concepts.
    overloaded_min_concepts: int = 3
    # unnamed-structure: a group at least this large is a "strong" signal.
    unnamed_strong_min_group_size: int = 5
    # orphaned-concept: zero uses is "strong"; up to this many is "moderate".
    orphaned_max_count: int = 2


DEFAULT_RECONCILIATION_POLICY = ReconciliationPolicy()


# --- drift formulas ---------------------------------------------------------


def parallel_term_signal(similarity: float, policy: DriftPolicy) -> str:
    if similarity >= policy.parallel_strong_min_similarity:
        return "strong"
    if similarity >= policy.parallel_moderate_min_similarity:
        return "moderate"
    return "weak"


def fading_state(
    count: int,
    doc_mentions: int | None,
    doc_count_complete: bool,
    policy: DriftPolicy,
) -> tuple[str, str] | None:
    """``(signal_strength, state)`` for a canonical term with a complete
    code count, or ``None`` when it is in ordinary use."""
    if count == 0:
        return "strong", "absent from code"
    if (
        count <= policy.fading_max_count
        and doc_mentions == 0
        and doc_count_complete
    ):
        return "moderate", "fading"
    return None


def overload_signal(dispersion: float, policy: DriftPolicy) -> str:
    if dispersion >= policy.overload_strong_min_dispersion:
        return "strong"
    return "moderate"


# --- validation formulas ----------------------------------------------------


# Match strengths: 0 none, 1 weak (some token overlap), 2 strong (the
# concept's full term vocabulary appears in the group), 3 label (the group is
# literally named with the concept's vocabulary).
MATCH_NONE = 0
MATCH_WEAK = 1
MATCH_STRONG = 2
MATCH_LABEL = 3


def structural_match_strength(
    label_tokens: set[str],
    combined: set[str],
    term_tokens: set[str],
    binding_tokens: set[str],
) -> int:
    """How strongly one concept's vocabulary matches one structural group."""
    if term_tokens and term_tokens <= label_tokens:
        return MATCH_LABEL
    if term_tokens and term_tokens <= combined:
        return MATCH_STRONG
    if (term_tokens | binding_tokens) & combined:
        return MATCH_WEAK
    return MATCH_NONE


def unnamed_structure_signal(group_size: int, policy: ReconciliationPolicy) -> str:
    if group_size >= policy.unnamed_strong_min_group_size:
        return "strong"
    return "moderate"


def is_overloaded_region(strong_matches: int, policy: ReconciliationPolicy) -> bool:
    return strong_matches >= policy.overloaded_min_concepts


def orphan_signal(count: int, policy: ReconciliationPolicy) -> str | None:
    """Signal for a canonical term with ``count`` complete lexical uses and
    no resolved or uncertain binding; ``None`` when it is in ordinary use."""
    if count == 0:
        return "strong"
    if count <= policy.orphaned_max_count:
        return "moderate"
    return None


def is_fragmented(module_spread: int, policy: ReconciliationPolicy) -> bool:
    return module_spread >= policy.fragmentation_min_modules
