"""Reconciliation: does the glossary describe the system we actually built?

Two directions of coverage plus the mismatch taxonomy: unnamed structure,
orphaned concepts, unresolved bindings, boundary mismatch, fragmentation,
overloaded structural regions, and (delegated to the drift module)
vocabulary drift and concept collision. Heuristic alignment with confidence
— NO one-to-one community=concept assumption anywhere, and every finding is
evidence for the team, never an automatic diagnosis.
"""

from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

from glossarize.drift import build_drift
from glossarize.evidence import build_evidence, write_evidence
from glossarize.glossary import GlossaryError, load_glossary
from glossarize.tokenize import tokenize_identifier

VALIDATION_SCHEMA_VERSION = 1
VALIDATION_FILE = "validation.json"
OUT_DIR = "glossarize-out"

FINDINGS_CAP = 10
FRAGMENTATION_MIN_MODULES = 5
OVERLOADED_MIN_CONCEPTS = 3

# Match strengths: 0 none, 1 weak (some token overlap), 2 strong (the
# concept's full term vocabulary appears in the group), 3 label (the group is
# literally named with the concept's vocabulary).


def _tokens(text: str) -> set[str]:
    return set(tokenize_identifier(text.replace(" ", "_").replace("-", "_")))


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
    if label_tokens & term_tokens:
        return 3
    if term_tokens and term_tokens <= combined:
        return 2
    if (term_tokens | binding_tokens) & combined:
        return 1
    return 0


def _resolve_bindings(concept: dict, evidence: dict) -> list[dict]:
    identifiers = {
        i["name"] for i in evidence["vocabulary"]["identifiers"]["items"]
    }
    token_terms = {
        t["term"] for t in evidence["vocabulary"]["tokens"]["items"]
    }
    file_paths = {f["path"] for f in evidence["files"]["code"]}
    file_paths |= {f["path"] for f in evidence["files"]["docs"]}
    module_paths = {m["path"] for m in evidence["modules"]}

    results = []
    for binding in concept.get("bindings", []):
        kind, _, value = binding["ref"].partition(":")
        if kind == "symbol":
            if value in identifiers:
                status = "resolved"
            elif _tokens(value) and _tokens(value) <= token_terms:
                # identifier list is capped; its tokens still exist in code
                status = "uncertain"
            else:
                status = "unresolved"
        elif kind == "file":
            status = "resolved" if value in file_paths else "unresolved"
        else:  # module
            status = "resolved" if value in module_paths else "unresolved"
        results.append({"ref": binding["ref"], "status": status})
    return results


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
    token_entries = {
        t["term"]: t for t in evidence["vocabulary"]["tokens"]["items"]
    }
    structural = evidence["structural_groups"]
    graph_ok = bool(structural.get("available"))

    # Direction A: structure -> glossary.
    unnamed, boundary, overloaded = [], [], []
    if graph_ok:
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
                    "confidence": "high" if group["size"] >= 5 else "medium",
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
                    "confidence": "medium",
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
                    "confidence": "medium",
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

    # Direction B: glossary -> evidence.
    orphaned, unresolved, fragmented = [], [], []
    for concept in canonical:
        term_tokens, _ = vocab[concept["id"]]
        counts = {
            t: token_entries.get(t, {}).get("count", 0) for t in term_tokens
        }
        bindings = _resolve_bindings(concept, evidence)
        resolved = [b for b in bindings if b["status"] == "resolved"]
        for binding in bindings:
            if binding["status"] == "unresolved":
                unresolved.append({
                    "kind": "binding-unresolved",
                    "confidence": "high",
                    "concept_id": concept["id"],
                    "ref": binding["ref"],
                    "summary": (
                        f"'{concept['term']}' binding {binding['ref']} no "
                        "longer resolves — drift signal, not an error"
                    ),
                })
        if counts and not resolved:
            min_count = min(counts.values())
            if min_count == 0:
                confidence = "high"
            elif min_count <= 2:
                confidence = "medium"
            else:
                confidence = None
            if confidence:
                orphaned.append({
                    "kind": "orphaned-concept",
                    "confidence": confidence,
                    "concept_id": concept["id"],
                    "evidence": {
                        "token_counts": counts,
                        "bindings_resolved": len(resolved),
                        "bindings_total": len(bindings),
                    },
                    "summary": (
                        f"canonical '{concept['term']}' has weak "
                        "implementation evidence (stale term, aspiration, "
                        "or deliberately diffuse?)"
                    ),
                })
        spread = max(
            (token_entries.get(t, {}).get("modules", 0) for t in term_tokens),
            default=0,
        )
        if spread >= FRAGMENTATION_MIN_MODULES:
            fragmented.append({
                "kind": "fragmentation",
                "confidence": "low",
                "concept_id": concept["id"],
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

    drift = build_drift(evidence, glossary)

    sections = {
        "unnamed_structure": {**_capped(unnamed), "skipped": not graph_ok},
        "boundary_mismatch": {**_capped(boundary), "skipped": not graph_ok},
        "overloaded_structural_region": {
            **_capped(overloaded), "skipped": not graph_ok
        },
        "orphaned_concepts": _capped(orphaned),
        "unresolved_bindings": _capped(unresolved),
        "fragmentation": _capped(fragmented),
        "vocabulary_drift": drift["parallel_terms"],
        "concept_collision": drift["canonical_overloaded"],
    }
    total = sum(len(s["items"]) for s in sections.values())
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "canonical_concepts": len(canonical),
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
    graph_note = (
        "" if validation["graph_available"]
        else " (no graphify graph: structural checks skipped)"
    )
    print(
        f"validate: {validation['canonical_concepts']} canonical concept(s), "
        f"{validation['total_findings']} finding(s){graph_note}"
    )
    for key, title in _TITLES.items():
        section = validation[key]
        if section.get("skipped"):
            continue
        if not section["items"] and not section["dropped_items"]:
            continue
        print(f"\n== {title} ==")
        for finding in section["items"]:
            print(f"{finding['summary']} [confidence {finding['confidence']}]")
        if section["dropped_items"]:
            print(f"... and {section['dropped_items']} more not shown")
    print(
        "\nNo one-to-one community=concept assumption; findings are evidence "
        "for the team, never automatic diagnoses."
    )


def validate_command(path_arg: str) -> int:
    root = Path(path_arg)
    if not root.is_dir():
        print(f"glossarize: not a directory: {path_arg}", file=sys.stderr)
        return 1
    root = root.resolve()
    try:
        glossary = load_glossary(root)
    except GlossaryError as exc:
        print(f"glossarize: {exc}", file=sys.stderr)
        return 1
    if glossary is None:
        print(
            "glossarize: no glossary to validate — run /glossarize and "
            f"settle terms first ({OUT_DIR}/glossary.json)",
            file=sys.stderr,
        )
        return 1
    evidence = build_evidence(root, cache=True)
    write_evidence(root, evidence)
    validation = build_validation(evidence, glossary)
    (root / OUT_DIR / VALIDATION_FILE).write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n"
    )
    _print_report(validation)
    return 0
