"""Reconciliation: does the glossary describe the system we actually built?

Two directions of coverage plus the mismatch taxonomy: unnamed structure,
orphaned concepts, unresolved bindings, boundary mismatch, fragmentation,
overloaded structural regions, and (delegated to the drift module)
vocabulary drift and concept collision. Heuristic thresholds are signal
strength, not unmeasured confidence — NO one-to-one community=concept
assumption anywhere, and every finding is evidence for the team, never an
automatic diagnosis.
"""

from __future__ import annotations

import sys
from itertools import combinations

from glossarize.artifacts import repo_root, write_artifact
from glossarize.drift import build_drift
from glossarize.evidence import build_evidence, write_evidence
from glossarize.glossary import (
    concept_scope,
    path_in_scope,
    require_glossary,
    scope_evidence,
)
from glossarize.matching import code_identifier_occurrence, code_term_occurrence
from glossarize.tokenize import tokenize_term

VALIDATION_SCHEMA_VERSION = 4
VALIDATION_FILE = "validation.json"

FINDINGS_CAP = 10
FRAGMENTATION_MIN_MODULES = 5
OVERLOADED_MIN_CONCEPTS = 3

# Match strengths: 0 none, 1 weak (some token overlap), 2 strong (the
# concept's full term vocabulary appears in the group), 3 label (the group is
# literally named with the concept's vocabulary).


def _tokens(text: str) -> set[str]:
    return set(tokenize_term(text))


def _concept_vocab(concept: dict) -> tuple[set[str], set[str]]:
    term_tokens = _tokens(concept["term"])
    binding_tokens: set[str] = set()
    for binding in concept.get("bindings", []):
        kind, _, value = binding["ref"].partition(":")
        if kind == "symbol":
            binding_tokens |= _tokens(value)
    return term_tokens, binding_tokens


def _match_strength(group: dict, term_tokens: set[str],
                    binding_tokens: set[str]) -> int:
    label_tokens = _tokens(group["label"])
    member_tokens: set[str] = set()
    for member in group["members_sample"]:
        member_tokens |= _tokens(member)
    combined = label_tokens | member_tokens
    if term_tokens and term_tokens <= label_tokens:
        return 3
    if term_tokens and term_tokens <= combined:
        return 2
    if (term_tokens | binding_tokens) & combined:
        return 1
    return 0


def _resolve_bindings(concept: dict, evidence: dict) -> list[dict]:
    identifier_section = evidence["vocabulary"]["identifiers"]
    identifiers_complete = identifier_section.get("truncated") is None
    file_paths = {f["path"] for f in evidence["files"]["code"]}
    file_paths |= {f["path"] for f in evidence["files"]["docs"]}
    module_paths = {m["path"] for m in evidence["modules"]}
    scope = concept_scope(concept)

    results = []
    for binding in concept.get("bindings", []):
        kind, _, value = binding["ref"].partition(":")
        if kind == "symbol":
            scoped = code_identifier_occurrence(evidence, value, scope)
            global_occurrence = code_identifier_occurrence(evidence, value)
            if scoped["count"]:
                status = "resolved"
            elif not scoped["count_complete"] or not identifiers_complete:
                status = "uncertain"
            elif global_occurrence["count"]:
                status = "out-of-scope"
            else:
                status = "unresolved"
        elif kind == "file":
            if value in file_paths and path_in_scope(value, scope):
                status = "resolved"
            elif value in file_paths:
                status = "out-of-scope"
            else:
                status = "unresolved"
        else:  # module
            if value in module_paths and path_in_scope(value, scope):
                status = "resolved"
            elif value in module_paths:
                status = "out-of-scope"
            else:
                status = "unresolved"
        results.append({
            "ref": binding["ref"],
            "status": status,
            "scope": scope_evidence(scope),
        })
    return results


def _structure_findings(structural: dict, canonical: list[dict],
                        vocab: dict) -> tuple[list, list, list]:
    """Direction A: structure -> glossary.

    Returns (unnamed structure, boundary mismatches, overloaded regions).
    """
    unnamed, boundary, overloaded = [], [], []
    for group in structural["groups"]:
        strengths = {
            c["id"]: _match_strength(group, *vocab[c["id"]])
            for c in canonical
        }
        strong = sorted(
            cid for cid, s in strengths.items() if s >= 2
        )
        if canonical and max(strengths.values(), default=0) == 0:
            unnamed.append({
                "kind": "unnamed-structure",
                "signal_strength": "strong" if group["size"] >= 5 else "moderate",
                "group": group["label"],
                "evidence": {
                    "size": group["size"],
                    "members_sample": group["members_sample"],
                },
                "summary": (
                    f"structural group '{group['label']}' "
                    f"({group['size']} nodes) matches no canonical concept"
                ),
            })
        for a, b in combinations(strong, 2):
            boundary.append({
                "kind": "boundary-mismatch",
                "signal_strength": "moderate",
                "concepts": [a, b],
                "group": group["label"],
                "evidence": {"members_sample": group["members_sample"]},
                "summary": (
                    f"'{a}' and '{b}' are distinct in the glossary but "
                    f"both strongly match group '{group['label']}'"
                ),
            })
        if len(strong) >= OVERLOADED_MIN_CONCEPTS:
            overloaded.append({
                "kind": "overloaded-structural-region",
                "signal_strength": "moderate",
                "group": group["label"],
                "concepts": strong,
                "evidence": {"members_sample": group["members_sample"]},
                "summary": (
                    f"group '{group['label']}' matches "
                    f"{len(strong)} distinct canonical concepts"
                ),
            })
    unnamed.sort(key=lambda f: (-f["evidence"]["size"], f["group"]))
    boundary.sort(key=lambda f: (f["group"], f["concepts"]))
    overloaded.sort(key=lambda f: f["group"])
    return unnamed, boundary, overloaded


def _concept_findings(canonical: list[dict], vocab: dict,
                      evidence: dict) -> tuple[list, list, list]:
    """Direction B: glossary -> evidence.

    Returns (orphaned concepts, unresolved bindings, fragmentation).
    """
    orphaned, unresolved, fragmented = [], [], []
    for concept in canonical:
        scope = concept_scope(concept)
        term_tokens, _ = vocab[concept["id"]]
        occurrence = code_term_occurrence(evidence, concept["term"], scope)
        bindings = _resolve_bindings(concept, evidence)
        resolved = [b for b in bindings if b["status"] == "resolved"]
        for binding in bindings:
            if binding["status"] in {"unresolved", "out-of-scope"}:
                out_of_scope = binding["status"] == "out-of-scope"
                unresolved.append({
                    "kind": (
                        "binding-out-of-scope" if out_of_scope
                        else "binding-unresolved"
                    ),
                    "certainty": "observed",
                    "concept_id": concept["id"],
                    "ref": binding["ref"],
                    "scope": scope_evidence(scope),
                    "binding_status": binding["status"],
                    "summary": (
                        f"'{concept['term']}' binding {binding['ref']} "
                        + (
                            "resolves outside the concept scope"
                            if out_of_scope
                            else "no longer resolves — drift signal, not an error"
                        )
                    ),
                })
        if term_tokens and occurrence["count_complete"] and not resolved:
            count = occurrence["count"]
            if count == 0:
                signal_strength = "strong"
            elif count <= 2:
                signal_strength = "moderate"
            else:
                signal_strength = None
            if signal_strength:
                finding_evidence = {
                    **occurrence,
                    "lexical_occurrences": count,
                    "bindings_resolved": len(resolved),
                    "bindings_total": len(bindings),
                }
                if len(term_tokens) == 1:
                    token = next(iter(term_tokens))
                    finding_evidence["token_counts"] = {token: count}
                orphaned.append({
                    "kind": "orphaned-concept",
                    "signal_strength": signal_strength,
                    "concept_id": concept["id"],
                    "scope": scope_evidence(scope),
                    "evidence": finding_evidence,
                    "summary": (
                        f"canonical '{concept['term']}' has weak "
                        "implementation evidence (stale term, aspiration, "
                        "or deliberately diffuse?)"
                    ),
                })
        spread = occurrence["modules"]
        if spread >= FRAGMENTATION_MIN_MODULES:
            fragmented.append({
                "kind": "fragmentation",
                "signal_strength": "weak",
                "concept_id": concept["id"],
                "scope": scope_evidence(scope),
                "evidence": {"module_spread": spread},
                "summary": (
                    f"'{concept['term']}' spans {spread} modules — may be "
                    "legitimately cross-cutting or problematically scattered"
                ),
            })
    orphaned.sort(key=lambda f: f["concept_id"])
    unresolved.sort(key=lambda f: (f["concept_id"], f["ref"]))
    fragmented.sort(
        key=lambda f: (-f["evidence"]["module_spread"], f["concept_id"])
    )
    return orphaned, unresolved, fragmented


def _capped(items: list) -> dict:
    return {
        "items": items[:FINDINGS_CAP],
        "dropped_items": max(0, len(items) - FINDINGS_CAP),
    }


def build_validation(evidence: dict, glossary: dict) -> dict:
    canonical = [
        c for c in glossary["concepts"] if c["status"] == "canonical"
    ]
    vocab = {c["id"]: _concept_vocab(c) for c in canonical}
    global_canonical = [c for c in canonical if concept_scope(c) is None]
    scoped_canonical = [c for c in canonical if concept_scope(c) is not None]
    structural = evidence["structural_groups"]
    graph_ok = bool(structural.get("available"))
    graph_present = structural.get("present") is True
    if graph_ok:
        skip_reason = None
    elif graph_present:
        skip_reason = "Graphify graph present but no usable structural groups loaded"
    else:
        skip_reason = "Graphify graph absent; structural checks require it"

    unnamed, boundary, overloaded = (
        _structure_findings(structural, global_canonical, vocab)
        if graph_ok else ([], [], [])
    )
    orphaned, unresolved, fragmented = _concept_findings(
        canonical, vocab, evidence
    )
    drift = build_drift(evidence, glossary)

    scoped_structure_reason = (
        "path-scoped concepts omitted because normalized Graphify groups do "
        "not carry repository paths"
    )
    unnamed_scope_limited = bool(scoped_canonical) and graph_ok
    if unnamed_scope_limited:
        unnamed = []
    sections = {
        "unnamed_structure": {
            **_capped(unnamed),
            "skipped": not graph_ok or unnamed_scope_limited,
            "skip_reason": (
                scoped_structure_reason if unnamed_scope_limited else skip_reason
            ),
        },
        "boundary_mismatch": {
            **_capped(boundary),
            "skipped": not graph_ok,
            "skip_reason": skip_reason,
            "partial": bool(scoped_canonical) and graph_ok,
            "partial_reason": (
                scoped_structure_reason if scoped_canonical and graph_ok else None
            ),
        },
        "overloaded_structural_region": {
            **_capped(overloaded),
            "skipped": not graph_ok,
            "skip_reason": skip_reason,
            "partial": bool(scoped_canonical) and graph_ok,
            "partial_reason": (
                scoped_structure_reason if scoped_canonical and graph_ok else None
            ),
        },
        "orphaned_concepts": _capped(orphaned),
        "unresolved_bindings": _capped(unresolved),
        "fragmentation": _capped(fragmented),
        "vocabulary_drift": drift["parallel_terms"],
        "concept_collision": drift["canonical_overloaded"],
    }
    total = sum(
        len(section["items"]) + section["dropped_items"]
        for section in sections.values()
    )
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "canonical_concepts": len(canonical),
        "scope_summary": {
            "repository": len(global_canonical),
            "path_scoped": len(scoped_canonical),
            "structural_scope_complete": not scoped_canonical,
        },
        "graph": {
            "present": structural.get("present"),
            "usable": graph_ok,
            "freshness": structural.get("freshness"),
            "warnings": list(structural.get("warnings", [])),
        },
        # Backward-compatible convenience flag; `graph` carries the complete
        # state and distinguishes absent, unusable, stale, and unverified.
        "graph_available": graph_ok,
        "total_findings": total,
        **sections,
    }


_TITLES = {
    "unnamed_structure": "unnamed structure (graph -> glossary)",
    "boundary_mismatch": "boundary mismatch",
    "overloaded_structural_region": "overloaded structural regions",
    "orphaned_concepts": "orphaned concepts (glossary -> evidence)",
    "unresolved_bindings": "unresolved bindings (drift signals)",
    "fragmentation": "fragmentation",
    "vocabulary_drift": "vocabulary drift",
    "concept_collision": "concept collision",
}


def _print_report(validation: dict) -> None:
    print(
        f"validate: {validation['canonical_concepts']} canonical concept(s), "
        f"{validation['total_findings']} finding(s)"
    )
    graph = validation["graph"]
    if graph["usable"]:
        freshness = graph["freshness"] or {
            "status": "unverified",
            "detail": "freshness metadata unavailable",
        }
        print(
            f"graphify: usable structural groups; freshness "
            f"{freshness['status']} — {freshness['detail']}"
        )
    elif graph["present"]:
        print(
            "graphify: graph present but no usable structural groups; "
            "structural checks skipped"
        )
    else:
        print("graphify: no graph; structural checks skipped")
    scopes = validation["scope_summary"]
    if scopes["path_scoped"]:
        structural_state = "partial" if graph["usable"] else "unavailable"
        print(
            f"scopes: {scopes['path_scoped']} path-scoped concept(s); lexical "
            f"checks are scoped, structural scope coverage is {structural_state}"
        )
    for key, title in _TITLES.items():
        section = validation[key]
        if section.get("skipped"):
            continue
        if not section["items"] and not section["dropped_items"]:
            continue
        print(f"\n== {title} ==")
        for finding in section["items"]:
            if "certainty" in finding:
                annotation = f"certainty {finding['certainty']}"
            else:
                annotation = f"signal {finding['signal_strength']}"
            print(f"{finding['summary']} [{annotation}]")
        if section["dropped_items"]:
            print(f"... and {section['dropped_items']} more not shown")
    print(
        "\nNo one-to-one community=concept assumption; findings are evidence "
        "for the team, never automatic diagnoses."
    )


def validate_command(path_arg: str) -> int:
    root = repo_root(path_arg)
    if root is None:
        return 1
    glossary = require_glossary(root, "no glossary to validate")
    if glossary is None:
        return 1
    evidence = build_evidence(root, cache=True)
    write_evidence(root, evidence)
    validation = build_validation(evidence, glossary)
    write_artifact(root, VALIDATION_FILE, validation)
    for warning in validation["graph"]["warnings"]:
        print(f"graphify adapter: {warning}", file=sys.stderr)
    _print_report(validation)
    return 0
