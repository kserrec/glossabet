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
from pathlib import Path
from typing import TypedDict

from glossabet.analysis.evidence_view import EvidenceView
from glossabet.corpus.tokenize import tokenize_term
from glossabet.glossary.findings import (
    HeuristicFinding,
    ObservedFinding,
    heuristic_finding,
    observed_finding,
    suppressed_reason,
)
from glossabet.glossary.matching import EvidenceIndex, TermOccurrence
from glossabet.glossary.model import ConceptRecord, ConceptScope, ScopeEvidence
from glossabet.glossary.policy import (
    DEFAULT_RECONCILIATION_POLICY,
    ReconciliationPolicy,
    is_fragmented,
    orphan_signal,
)
from glossabet.glossary.store import concept_scope, path_in_scope, scope_evidence


def _tokens(text: str) -> set[str]:
    return set(tokenize_term(text))


# Per canonical concept id: (term tokens, symbol-binding tokens).
_ConceptVocab = dict[str, tuple[set[str], set[str]]]


class BindingResolution(TypedDict):
    """One binding judged against the evidence: ``resolved``,
    ``out-of-scope``, ``uncertain``, or ``unresolved``."""

    ref: str
    status: str
    scope: ScopeEvidence


def _concept_vocab(concept: ConceptRecord) -> tuple[set[str], set[str]]:
    term_tokens = _tokens(concept["term"])
    binding_tokens: set[str] = set()
    for binding in concept.get("bindings", []):
        kind, _, value = binding["ref"].partition(":")
        if kind == "symbol":
            binding_tokens |= _tokens(value)
    return term_tokens, binding_tokens



# Omission ledgers whose entries are paths the scan chose not to read: a
# binding into one of them names something that may well exist, so it is
# never "unresolved" — the engine simply cannot judge it.
_EXCLUDED_PATH_LEDGERS = (
    "configured", "generated", "vendored", "sensitive", "oversized",
    "symlinks_escaping_repo", "symlinks_to_excluded_content",
    "symlinked_directories", "unreadable",
)


def _excluded_prefixes(view: EvidenceView) -> tuple[str, ...]:
    prefixes = []
    for ledger in _EXCLUDED_PATH_LEDGERS:
        for entry in view.skipped_paths(ledger):
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
) -> str:
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
    inventory_complete = matcher.view.repository_corpus_complete()
    excluded = _excluded_prefixes(matcher.view)
    scope = concept_scope(concept)

    results: list[BindingResolution] = []
    for binding in concept.get("bindings", []):
        kind, _, value = binding["ref"].partition(":")
        if kind == "symbol":
            scoped = matcher.code_identifier_occurrence(value, scope)
            global_occurrence = matcher.code_identifier_occurrence(value)
            if scoped["count"]:
                status = "resolved"
            elif not scoped["count_complete"]:
                status = "uncertain"
            elif global_occurrence["count"]:
                status = "out-of-scope"
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
    concept: ConceptRecord, scope: ConceptScope, term_tokens: set[str],
    occurrence: TermOccurrence,
    bindings: list[BindingResolution],
    resolved: list[BindingResolution],
    uncertain: list[BindingResolution],
    policy: ReconciliationPolicy,
) -> HeuristicFinding | None:
    """The orphaned-concept finding for a canonical term with weak, complete
    lexical evidence and no resolved or uncertain binding — or None."""
    if not (
        term_tokens
        and occurrence["count_complete"]
        and not resolved
        and not uncertain
    ):
        return None
    count = occurrence["count"]
    signal_strength = orphan_signal(count, policy)
    if signal_strength is None:
        return None
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
    )


def _concept_findings(
    canonical: list[ConceptRecord],
    vocab: _ConceptVocab,
    matcher: EvidenceIndex,
    root: Path | None = None,
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY,
) -> tuple[
    list[HeuristicFinding], list[ObservedFinding], list[HeuristicFinding],
    list[str], list[str],
]:
    """Direction B: glossary -> evidence.

    Returns (orphaned concepts, unresolved bindings, fragmentation,
    fragmentation incompleteness reasons, binding-ledger reasons).
    """
    orphaned: list[HeuristicFinding] = []
    unresolved: list[ObservedFinding] = []
    # (module spread, concept id, finding)
    fragmented: list[tuple[int, str, HeuristicFinding]] = []
    fragmentation_suppressed = 0
    excluded_bindings = 0
    for concept in canonical:
        scope = concept_scope(concept)
        term_tokens, _ = vocab[concept["id"]]
        occurrence = matcher.code_term_occurrence(concept["term"], scope)
        bindings = _resolve_bindings(concept, matcher, root)
        resolved = [b for b in bindings if b["status"] == "resolved"]
        uncertain = [b for b in bindings if b["status"] == "uncertain"]
        excluded_bindings += sum(
            1 for b in uncertain
            if b["ref"].partition(":")[0] in ("file", "module")
            and matcher.view.repository_corpus_complete()
        )
        unresolved.extend(_binding_findings(concept, scope, bindings))
        orphan = _orphan_finding(
            concept, scope, term_tokens, occurrence, bindings, resolved,
            uncertain, policy,
        )
        if orphan is not None:
            orphaned.append(orphan)
        spread = occurrence["modules"]
        # A scoped single-token occurrence counts modules over the entry's
        # retained location sample, so a clipped sample undercounts spread:
        # a value that still clears the threshold is a valid lower bound,
        # one below it proves nothing. For that path locations_truncated is
        # exactly the entry-level clip. Compound occurrences also fold the
        # final display clip into the same flag, which does not reduce the
        # module set — treating it as sampling would cry wolf on ordinary
        # repositories, so compound spread stays a best-effort lower bound.
        modules_sampled = (
            scope is not None
            and occurrence["match_kind"] == "token"
            and occurrence["locations_truncated"]
        )
        if is_fragmented(spread, policy):
            fragmented.append((spread, concept["id"], heuristic_finding(
                "fragmentation",
                f"'{concept['term']}' spans {spread} modules — may be "
                "legitimately cross-cutting or problematically scattered",
                {"module_spread": spread},
                signal_strength="weak",
                scope=scope_evidence(scope),
                concept_id=concept["id"],
            )))
        elif modules_sampled:
            fragmentation_suppressed += 1
    orphaned.sort(key=lambda f: f["concept_id"])
    unresolved.sort(key=lambda f: (f["concept_id"], f["ref"]))
    fragmented.sort(key=lambda row: (-row[0], row[1]))
    fragmentation_reasons = suppressed_reason(
        fragmentation_suppressed, "fragmentation"
    )
    binding_reasons = [] if not excluded_bindings else [
        f"{excluded_bindings} binding(s) name paths the scan did not read "
        "(vendored, generated, ignored, sensitive, oversized, linked, or not "
        "a code/doc file) and were not judged"
    ]
    return (
        orphaned, unresolved, [row[2] for row in fragmented],
        fragmentation_reasons, binding_reasons,
    )

