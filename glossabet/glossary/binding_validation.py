"""Direction B of reconciliation: glossary -> evidence.

Resolves each canonical concept's stable bindings (``symbol:``, ``file:``,
``module:``) against the evidence inventory and produces the orphaned-concept,
unresolved-binding, and fragmentation evidence. Bindings into paths the scan
deliberately did not read are ``uncertain``, never ``unresolved``: existence
is not in question, only the engine's ability to judge it.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

from glossabet.analysis.evidence_facts import skipped_path_entries
from glossabet.analysis.evidence_types import EvidenceDocument
from glossabet.corpus.tokenize import tokenize_term
from glossabet.glossary.findings import (
    HeuristicFinding,
    ObservedFinding,
    heuristic_finding,
    observed_finding,
    suppressed_reason,
)
from glossabet.glossary.matching import (
    EvidenceIndex,
    TermOccurrence,
    is_unproven_zero,
)
from glossabet.glossary.model import ConceptRecord, ConceptScope, ScopeEvidence
from glossabet.glossary.policy import (
    DEFAULT_RECONCILIATION_POLICY,
    ReconciliationPolicy,
    is_fragmented,
    orphan_signal,
)
from glossabet.glossary.scope import concept_scope, path_in_scope, scope_evidence


def vocabulary_tokens(text: str) -> set[str]:
    """The normalized token set used by both validation directions."""
    return set(tokenize_term(text))


@dataclass(frozen=True)
class ConceptWords:
    """The term and stable symbol-binding vocabulary of one concept."""

    term_tokens: frozenset[str]
    binding_tokens: frozenset[str]


ConceptVocabulary = dict[str, ConceptWords]


def build_concept_vocabulary(
    concepts: Collection[ConceptRecord],
) -> ConceptVocabulary:
    """Index canonical concept vocabulary by concept id."""
    vocabulary: ConceptVocabulary = {}
    for concept in concepts:
        binding_tokens: set[str] = set()
        for binding in concept.get("bindings", []):
            kind, _, value = binding["ref"].partition(":")
            if kind == "symbol":
                binding_tokens |= vocabulary_tokens(value)
        vocabulary[concept["id"]] = ConceptWords(
            term_tokens=frozenset(vocabulary_tokens(concept["term"])),
            binding_tokens=frozenset(binding_tokens),
        )
    return vocabulary


BindingStatus = Literal["resolved", "out-of-scope", "uncertain", "unresolved"]
OrphanSuppression = Literal["occurrence", "binding"]


class BindingResolution(TypedDict):
    """One binding judged against the evidence: ``resolved``,
    ``out-of-scope``, ``uncertain``, or ``unresolved``."""

    ref: str
    status: BindingStatus
    scope: ScopeEvidence


# Omission ledgers contain paths the scan chose not to read. A binding into
# one of them has unknown existence and is therefore uncertain rather than
# unresolved.
_EXCLUDED_PATH_LEDGERS = (
    "configured", "generated", "vendored", "sensitive", "oversized",
    "symlinks_escaping_repo", "symlinks_to_excluded_content",
    "symlinked_directories", "unreadable",
)


def _excluded_prefixes(evidence: EvidenceDocument) -> tuple[str, ...]:
    prefixes = []
    for ledger in _EXCLUDED_PATH_LEDGERS:
        for entry in skipped_path_entries(evidence, ledger):
            path = entry.get("path") if isinstance(entry, dict) else entry
            if isinstance(path, str) and path:
                prefixes.append(unicodedata.normalize("NFC", path))
    return tuple(prefixes)


def _under_excluded_path(value: str, excluded: tuple[str, ...]) -> bool:
    return any(
        value == prefix or value.startswith(prefix + "/") for prefix in excluded
    )


def _exists_confined(root: Path | None, relative: str) -> bool:
    """Whether ``relative`` names something on disk inside ``root`` — an
    ordinary path only: absolute, ``..``, or symlink-escaping paths read as
    absent, so a hostile binding cannot probe outside the repository."""
    if root is None:
        return False
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        return False
    candidate = root / rel
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def _path_binding_status(
    value: str, known_paths: Collection[str], scope: ConceptScope,
    inventory_complete: bool, excluded: tuple[str, ...] = (),
    root: Path | None = None,
) -> BindingStatus:
    value = unicodedata.normalize("NFC", value)  # known_paths are NFC-keyed
    if value in known_paths and path_in_scope(value, scope):
        return "resolved"
    if value in known_paths:
        return "out-of-scope"
    if (
        not inventory_complete
        or _under_excluded_path(value, excluded)
        or _exists_confined(root, value)
    ):
        # The inventory is partial, the path was deliberately not read
        # (vendored, generated, ignored, sensitive, oversized, a link), or
        # it exists on disk but is not a file the scan reads (a Makefile,
        # a settings file): existence is not in question, only the engine's
        # ability to judge it, so this is not a drift signal.
        return "uncertain"
    return "unresolved"


def _resolve_bindings(
    concept: ConceptRecord, matcher: EvidenceIndex, root: Path | None = None
) -> list[BindingResolution]:
    inventory_complete = matcher.repository_corpus_complete
    excluded = _excluded_prefixes(matcher.evidence)
    scope = concept_scope(concept)

    results: list[BindingResolution] = []
    for binding in concept.get("bindings", []):
        kind, _, value = binding["ref"].partition(":")
        status: BindingStatus
        if kind == "symbol":
            scoped = matcher.code_identifier_occurrence(value, scope)
            global_occurrence = matcher.code_identifier_occurrence(value)
            if scoped["count"]:
                status = "resolved"
            elif is_unproven_zero(scoped):
                status = "uncertain"
            elif global_occurrence["count"]:
                status = "out-of-scope"
            elif is_unproven_zero(global_occurrence):
                status = "uncertain"
            else:
                status = "unresolved"
        elif kind == "file":
            status = _path_binding_status(
                value, matcher.file_paths, scope, inventory_complete, excluded, root
            )
        else:  # module
            status = _path_binding_status(
                value, matcher.module_paths, scope, inventory_complete, excluded, root
            )
        results.append({
            "ref": binding["ref"],
            "status": status,
            "scope": scope_evidence(scope),
        })
    return results



def _binding_findings(
    concept: ConceptRecord, scope: ConceptScope, bindings: list[BindingResolution]
) -> list[ObservedFinding]:
    """One finding per binding that no longer resolves inside the scope."""
    found: list[ObservedFinding] = []
    for binding in bindings:
        if binding["status"] not in {"unresolved", "out-of-scope"}:
            continue
        out_of_scope = binding["status"] == "out-of-scope"
        found.append(observed_finding(
            "binding-out-of-scope" if out_of_scope
            else "binding-unresolved",
            f"'{concept['term']}' binding {binding['ref']} "
            + (
                "resolves outside the concept scope"
                if out_of_scope
                else "no longer resolves — drift signal, not an error"
            ),
            certainty="observed",
            scope=scope_evidence(scope),
            concept_id=concept["id"],
            ref=binding["ref"],
            binding_status=binding["status"],
        ))
    return found


def _orphan_finding(
    concept: ConceptRecord, scope: ConceptScope, term_tokens: Collection[str],
    occurrence: TermOccurrence,
    bindings: list[BindingResolution],
    resolved: list[BindingResolution],
    uncertain: list[BindingResolution],
    policy: ReconciliationPolicy,
) -> tuple[HeuristicFinding | None, OrphanSuppression | None]:
    """An orphan finding and the uncertainty that suppressed it, if any."""
    if resolved:
        return None, None
    if not term_tokens:
        return None, "occurrence" if is_unproven_zero(occurrence) else None
    count = occurrence["count"]
    signal_strength = orphan_signal(count, policy)
    if signal_strength is None:
        return None, None
    occurrence_inexact = (
        is_unproven_zero(occurrence) or not occurrence["count_exact"]
    )
    if occurrence_inexact:
        return None, "occurrence"
    if uncertain:
        return None, "binding"
    finding_evidence: dict[str, object] = {
        **occurrence,
        "lexical_occurrences": count,
        "bindings_resolved": len(resolved),
        "bindings_total": len(bindings),
    }
    if len(term_tokens) == 1:
        token = next(iter(term_tokens))
        finding_evidence["token_counts"] = {token: count}
    return heuristic_finding(
        "orphaned-concept",
        f"canonical '{concept['term']}' has weak "
        "implementation evidence (stale term, aspiration, "
        "or deliberately diffuse?)",
        finding_evidence,
        signal_strength=signal_strength,
        scope=scope_evidence(scope),
        concept_id=concept["id"],
    ), None


@dataclass(frozen=True)
class BindingFindings:
    """Named glossary-to-evidence findings and their omission reasons."""

    orphaned_concepts: list[HeuristicFinding]
    orphan_incompleteness_reasons: list[str]
    unresolved_bindings: list[ObservedFinding]
    fragmentation: list[HeuristicFinding]
    fragmentation_incompleteness_reasons: list[str]
    binding_ledger_reasons: list[str]


def build_binding_findings(
    canonical: list[ConceptRecord],
    vocabulary: ConceptVocabulary,
    matcher: EvidenceIndex,
    root: Path | None = None,
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY,
) -> BindingFindings:
    """Build direction-B glossary-to-evidence findings."""
    orphaned: list[HeuristicFinding] = []
    unresolved: list[ObservedFinding] = []
    # (module spread, concept id, finding)
    fragmented: list[tuple[int, str, HeuristicFinding]] = []
    orphan_occurrence_suppressed = 0
    orphan_binding_suppressed = 0
    fragmentation_suppressed = 0
    symbol_binding_suppressed = 0
    excluded_bindings = 0
    for concept in canonical:
        scope = concept_scope(concept)
        term_tokens = vocabulary[concept["id"]].term_tokens
        occurrence = matcher.code_term_occurrence(concept["term"], scope)
        bindings = _resolve_bindings(concept, matcher, root)
        resolved = [b for b in bindings if b["status"] == "resolved"]
        uncertain = [b for b in bindings if b["status"] == "uncertain"]
        symbol_binding_suppressed += sum(
            1 for binding in uncertain
            if binding["ref"].partition(":")[0] == "symbol"
        )
        excluded_bindings += sum(
            1 for b in uncertain
            if b["ref"].partition(":")[0] in ("file", "module")
            and matcher.repository_corpus_complete
        )
        unresolved.extend(_binding_findings(concept, scope, bindings))
        orphan, orphan_suppression = _orphan_finding(
            concept, scope, term_tokens, occurrence, bindings, resolved,
            uncertain, policy,
        )
        orphan_occurrence_suppressed += orphan_suppression == "occurrence"
        orphan_binding_suppressed += orphan_suppression == "binding"
        if orphan is not None:
            orphaned.append(orphan)
        spread = occurrence["modules"]
        spread_exact = occurrence["modules_exact"]
        if is_fragmented(spread, policy):
            quantity = str(spread) if spread_exact else f"at least {spread}"
            fragmented.append((spread, concept["id"], heuristic_finding(
                "fragmentation",
                f"'{concept['term']}' spans {quantity} modules — may be "
                "legitimately cross-cutting or problematically scattered",
                {
                    "module_spread": spread,
                    "module_spread_exact": spread_exact,
                },
                signal_strength="weak",
                scope=scope_evidence(scope),
                concept_id=concept["id"],
            )))
        elif not spread_exact:
            fragmentation_suppressed += 1
    orphaned.sort(key=lambda f: f["concept_id"])
    unresolved.sort(key=lambda f: (f["concept_id"], f["ref"]))
    fragmented.sort(key=lambda row: (-row[0], row[1]))
    fragmentation_reasons = suppressed_reason(
        fragmentation_suppressed, "fragmentation"
    )
    binding_reasons = suppressed_reason(
        symbol_binding_suppressed, "symbol-binding"
    )
    if excluded_bindings:
        binding_reasons.append(
            f"{excluded_bindings} binding(s) name paths the scan did not read "
            "(vendored, generated, ignored, sensitive, oversized, linked, or "
            "not a code/doc file) and were not judged"
        )
    orphan_reasons = suppressed_reason(
        orphan_occurrence_suppressed, "orphaned-concept"
    )
    if orphan_binding_suppressed:
        orphan_reasons.append(
            f"{orphan_binding_suppressed} orphaned-concept check(s) suppressed "
            "because one or more bindings were uncertain"
        )
    return BindingFindings(
        orphaned_concepts=orphaned,
        orphan_incompleteness_reasons=orphan_reasons,
        unresolved_bindings=unresolved,
        fragmentation=[row[2] for row in fragmented],
        fragmentation_incompleteness_reasons=fragmentation_reasons,
        binding_ledger_reasons=binding_reasons,
    )
