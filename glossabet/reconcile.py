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
from collections import defaultdict
from itertools import combinations, islice

from glossabet.artifacts import repo_root, write_artifact
from glossabet.coverage import coverage_ledger, coverage_reasons
from glossabet.context_sync import (
    inspect_managed_context,
    print_managed_context_issues,
    unchecked_managed_context,
)
from glossabet.display import escape_terminal_text
from glossabet.drift import build_drift
from glossabet.evidence import build_evidence, write_evidence
from glossabet.glossary import (
    concept_scope,
    path_in_scope,
    require_glossary,
    scope_evidence,
)
from glossabet.matching import (
    EvidenceIndex,
    code_identifier_occurrence,
    code_term_occurrence,
    production_corpus_complete,
    repository_corpus_complete,
)
from glossabet.tokenize import tokenize_term

VALIDATION_SCHEMA_VERSION = 7
VALIDATION_FILE = "validation.json"

FINDINGS_CAP = 10
FRAGMENTATION_MIN_MODULES = 5
OVERLOADED_MIN_CONCEPTS = 3
STRUCTURAL_MATCH_BUDGET = 50_000

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
    raw_member_tokens = group.get("member_tokens")
    if isinstance(raw_member_tokens, list):
        member_tokens = {
            token for token in raw_member_tokens if isinstance(token, str)
        }
    else:
        # Compatibility for evidence produced before RepositoryEvidence v7.
        # Validation marks this fallback partial; it never treats the display
        # sample as complete structural coverage.
        member_tokens = set()
        for member in group.get("members_sample", []):
            member_tokens |= _tokens(member)
    return _match_strength_from_tokens(
        label_tokens, label_tokens | member_tokens,
        term_tokens, binding_tokens,
    )


def _match_strength_from_tokens(
    label_tokens: set[str],
    combined: set[str],
    term_tokens: set[str],
    binding_tokens: set[str],
) -> int:
    if term_tokens and term_tokens <= label_tokens:
        return 3
    if term_tokens and term_tokens <= combined:
        return 2
    if (term_tokens | binding_tokens) & combined:
        return 1
    return 0


def _resolve_bindings(
    concept: dict, evidence: dict, matcher: EvidenceIndex
) -> list[dict]:
    inventory_complete = repository_corpus_complete(evidence)
    scope = concept_scope(concept)

    results = []
    for binding in concept.get("bindings", []):
        kind, _, value = binding["ref"].partition(":")
        if kind == "symbol":
            scoped = code_identifier_occurrence(
                evidence, value, scope, index=matcher
            )
            global_occurrence = code_identifier_occurrence(
                evidence, value, index=matcher
            )
            if scoped["count"]:
                status = "resolved"
            elif not scoped["count_complete"]:
                status = "uncertain"
            elif global_occurrence["count"]:
                status = "out-of-scope"
            else:
                status = "unresolved"
        elif kind == "file":
            if value in matcher.file_paths and path_in_scope(value, scope):
                status = "resolved"
            elif value in matcher.file_paths:
                status = "out-of-scope"
            elif not inventory_complete:
                status = "uncertain"
            else:
                status = "unresolved"
        else:  # module
            if value in matcher.module_paths and path_in_scope(value, scope):
                status = "resolved"
            elif value in matcher.module_paths:
                status = "out-of-scope"
            elif not inventory_complete:
                status = "uncertain"
            else:
                status = "unresolved"
        results.append({
            "ref": binding["ref"],
            "status": status,
            "scope": scope_evidence(scope),
        })
    return results


def _covered_section(
    items: list[dict],
    total_items: int,
    name: str,
    *,
    total_items_exact: bool,
    incomplete_reasons: list[str],
) -> dict:
    kept = items[:FINDINGS_CAP]
    reasons = list(incomplete_reasons)
    if total_items > len(kept):
        reasons.append(
            f"{name} finding detail cap is {FINDINGS_CAP} items"
        )
    coverage = coverage_ledger(
        total_items,
        len(kept),
        total_items_exact=total_items_exact,
        reasons=reasons,
    )
    return {
        "items": kept,
        "dropped_items": coverage["dropped_items"],
        "coverage": coverage,
    }


def _structure_findings(
    structural: dict,
    canonical: list[dict],
    vocab: dict,
    upstream_reasons: list[str],
) -> tuple[dict, dict, dict, dict]:
    """Direction A: structure -> glossary.

    Canonical concepts are reached through an inverted token index. Boundary
    totals use n*(n-1)/2 and only the report prefix is streamed, so a group
    matching many concepts never materializes every pair.
    """
    token_index: dict[str, set[str]] = defaultdict(set)
    for concept in canonical:
        term_tokens, binding_tokens = vocab[concept["id"]]
        for token in term_tokens | binding_tokens:
            token_index[token].add(concept["id"])

    contexts = []
    missing_member_tokens = 0
    for group in structural["groups"]:
        label_tokens = _tokens(group["label"])
        raw_member_tokens = group.get("member_tokens")
        if isinstance(raw_member_tokens, list):
            member_tokens = {
                token for token in raw_member_tokens if isinstance(token, str)
            }
        else:
            missing_member_tokens += 1
            member_tokens = set()
            for member in group.get("members_sample", []):
                member_tokens |= _tokens(member)
        combined = label_tokens | member_tokens
        candidate_ids = sorted({
            concept_id
            for token in combined
            for concept_id in token_index.get(token, ())
        })
        contexts.append((group, label_tokens, combined, candidate_ids))
    contexts.sort(key=lambda item: (item[0]["label"], item[0]["id"]))

    total_match_work = sum(len(item[3]) for item in contexts)
    processed_match_work = 0
    unnamed: list[dict] = []
    boundary: list[dict] = []
    overloaded: list[dict] = []
    boundary_total = 0
    partial_group_matches = False

    for group, label_tokens, combined, candidate_ids in contexts:
        remaining = max(0, STRUCTURAL_MATCH_BUDGET - processed_match_work)
        evaluated_ids = candidate_ids[:remaining]
        processed_match_work += len(evaluated_ids)
        group_complete = len(evaluated_ids) == len(candidate_ids)
        partial_group_matches |= not group_complete
        strengths = {
            concept_id: _match_strength_from_tokens(
                label_tokens, combined, *vocab[concept_id]
            )
            for concept_id in evaluated_ids
        }
        strong = sorted(
            concept_id
            for concept_id, strength in strengths.items()
            if strength >= 2
        )
        if group_complete and max(strengths.values(), default=0) == 0:
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
        group_pair_total = len(strong) * (len(strong) - 1) // 2
        boundary_total += group_pair_total
        detail_slots = max(0, FINDINGS_CAP - len(boundary))
        for a, b in islice(combinations(strong, 2), detail_slots):
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
    overloaded.sort(key=lambda f: f["group"])

    reasons = list(upstream_reasons)
    if missing_member_tokens:
        reasons.append(
            f"{missing_member_tokens} structural group(s) lack complete "
            "member_tokens and fell back to the display sample"
        )
    if partial_group_matches:
        reasons.append(
            "structural concept matching reached its "
            f"{STRUCTURAL_MATCH_BUDGET}-candidate evaluation budget"
        )
    exact = not reasons
    work_reasons = []
    if processed_match_work < total_match_work:
        work_reasons.append(
            "structural concept matching reached its "
            f"{STRUCTURAL_MATCH_BUDGET}-candidate evaluation budget"
        )
    work_coverage = coverage_ledger(
        total_match_work,
        processed_match_work,
        reasons=work_reasons,
    )
    return (
        _covered_section(
            unnamed, len(unnamed), "unnamed structure",
            total_items_exact=exact, incomplete_reasons=reasons,
        ),
        _covered_section(
            boundary, boundary_total, "boundary mismatch",
            total_items_exact=exact, incomplete_reasons=reasons,
        ),
        _covered_section(
            overloaded, len(overloaded), "overloaded structural region",
            total_items_exact=exact, incomplete_reasons=reasons,
        ),
        work_coverage,
    )


def _concept_findings(canonical: list[dict], vocab: dict,
                      evidence: dict,
                      matcher: EvidenceIndex) -> tuple[list, list, list]:
    """Direction B: glossary -> evidence.

    Returns (orphaned concepts, unresolved bindings, fragmentation).
    """
    orphaned, unresolved, fragmented = [], [], []
    for concept in canonical:
        scope = concept_scope(concept)
        term_tokens, _ = vocab[concept["id"]]
        occurrence = code_term_occurrence(
            evidence, concept["term"], scope, index=matcher
        )
        bindings = _resolve_bindings(concept, evidence, matcher)
        resolved = [b for b in bindings if b["status"] == "resolved"]
        uncertain = [b for b in bindings if b["status"] == "uncertain"]
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
        if (
            term_tokens
            and occurrence["count_complete"]
            and not resolved
            and not uncertain
        ):
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


def _capped(items: list, name: str, incomplete_reasons: list[str]) -> dict:
    return _covered_section(
        items,
        len(items),
        name,
        total_items_exact=not incomplete_reasons,
        incomplete_reasons=incomplete_reasons,
    )


def _mark_incomplete(section: dict, reason: str) -> dict:
    ledger = section["coverage"]
    coverage = coverage_ledger(
        ledger["total_items"],
        ledger["included_items"],
        total_items_exact=False,
        reasons=[*ledger["reasons"], reason],
    )
    return {
        **section,
        "dropped_items": coverage["dropped_items"],
        "coverage": coverage,
    }


def build_validation(
    evidence: dict,
    glossary: dict,
    *,
    managed_context: dict | None = None,
) -> dict:
    canonical = [
        c for c in glossary["concepts"] if c["status"] == "canonical"
    ]
    vocab = {c["id"]: _concept_vocab(c) for c in canonical}
    global_canonical = [c for c in canonical if concept_scope(c) is None]
    scoped_canonical = [c for c in canonical if concept_scope(c) is not None]
    structural = evidence["structural_groups"]
    graph_ok = bool(structural.get("available"))
    graph_present = structural.get("present") is True
    groups_dropped = int(structural.get("groups_dropped", 0))
    groups_complete = (
        structural.get("groups_complete", groups_dropped == 0)
        if graph_ok else None
    )
    if graph_ok:
        skip_reason = None
    elif graph_present:
        skip_reason = "Graphify graph present but no usable structural groups loaded"
    else:
        skip_reason = "Graphify graph absent; structural checks require it"

    matching_terms = [
        term
        for concept in glossary["concepts"]
        for term in (
            concept["term"],
            *(alias["term"] for alias in concept.get("aliases", [])),
        )
    ]
    matcher = EvidenceIndex(evidence, matching_terms)

    scoped_structure_reason = (
        "path-scoped concepts omitted because normalized Graphify groups do "
        "not carry repository paths"
    )
    group_cap_reason = (
        f"{groups_dropped} normalized Graphify group(s) omitted by the "
        "group cap"
        if groups_dropped else None
    )
    structural_source_reasons = [
        reason for reason in (group_cap_reason,) if reason is not None
    ]
    if graph_ok:
        unnamed, boundary, overloaded, structural_work = _structure_findings(
            structural, global_canonical, vocab, structural_source_reasons
        )
    else:
        skipped_coverage = coverage_ledger(
            0, 0, reasons=[skip_reason]
        )
        unnamed = boundary = overloaded = {
            "items": [],
            "dropped_items": 0,
            "coverage": skipped_coverage,
        }
        structural_work = coverage_ledger(0, 0)

    unnamed_scope_limited = bool(scoped_canonical) and graph_ok
    if unnamed_scope_limited:
        coverage = coverage_ledger(
            0,
            0,
            total_items_exact=False,
            reasons=[scoped_structure_reason],
        )
        unnamed = {
            "items": [], "dropped_items": 0, "coverage": coverage
        }
    if scoped_canonical and graph_ok:
        boundary = _mark_incomplete(boundary, scoped_structure_reason)
        overloaded = _mark_incomplete(overloaded, scoped_structure_reason)

    orphaned, unresolved, fragmented = _concept_findings(
        canonical, vocab, evidence, matcher
    )
    drift = build_drift(
        evidence,
        glossary,
        matcher=matcher,
        managed_context=managed_context,
    )

    production_complete = production_corpus_complete(evidence)
    inventory_complete = repository_corpus_complete(evidence)
    production_reasons = [] if production_complete else [
        "production corpus budget omitted accepted source evidence"
    ]
    inventory_reasons = [] if inventory_complete else [
        "repository corpus budget omitted accepted inventory evidence"
    ]
    code_vocabulary_reasons = [
        f"vocabulary.{name} omitted entries needed for exact matching"
        for name in ("tokens", "identifiers")
        if evidence["vocabulary"][name].get("truncated") is not None
    ]
    identifier_reasons = [
        "vocabulary.identifiers omitted entries needed for binding resolution"
    ] if evidence["vocabulary"]["identifiers"].get("truncated") is not None else []
    matching_reasons = [
        reason
        for name, ledger in matcher.coverage.items()
        for reason in coverage_reasons(ledger, f"matching.{name}")
    ]

    def structural_partial(section: dict) -> tuple[bool, str | None]:
        ledger = section["coverage"]
        partial = graph_ok and not ledger["total_items_exact"]
        return (
            partial,
            "; ".join(ledger["reasons"]) if partial else None,
        )

    unnamed_partial, unnamed_partial_reason = structural_partial(unnamed)
    boundary_partial, boundary_partial_reason = structural_partial(boundary)
    overloaded_partial, overloaded_partial_reason = structural_partial(overloaded)

    sections = {
        "unnamed_structure": {
            **unnamed,
            "skipped": not graph_ok or unnamed_scope_limited,
            "skip_reason": (
                scoped_structure_reason if unnamed_scope_limited else skip_reason
            ),
            "partial": unnamed_partial,
            "partial_reason": unnamed_partial_reason,
        },
        "boundary_mismatch": {
            **boundary,
            "skipped": not graph_ok,
            "skip_reason": skip_reason,
            "partial": boundary_partial,
            "partial_reason": boundary_partial_reason,
        },
        "overloaded_structural_region": {
            **overloaded,
            "skipped": not graph_ok,
            "skip_reason": skip_reason,
            "partial": overloaded_partial,
            "partial_reason": overloaded_partial_reason,
        },
        "orphaned_concepts": _capped(
            orphaned,
            "orphaned concept",
            production_reasons + code_vocabulary_reasons + matching_reasons,
        ),
        "unresolved_bindings": _capped(
            unresolved,
            "unresolved binding",
            inventory_reasons + identifier_reasons,
        ),
        "fragmentation": _capped(
            fragmented,
            "fragmentation",
            production_reasons + code_vocabulary_reasons + matching_reasons,
        ),
        "vocabulary_drift": drift["parallel_terms"],
        "concept_collision": drift["canonical_overloaded"],
    }
    total = sum(
        section["coverage"]["total_items"]
        for section in sections.values()
    )
    total_complete = all(
        section["coverage"]["total_items_exact"]
        for section in sections.values()
        if not section.get("skipped")
    )
    return {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "canonical_concepts": len(canonical),
        "scope_summary": {
            "repository": len(global_canonical),
            "path_scoped": len(scoped_canonical),
            "structural_scope_complete": not scoped_canonical,
        },
        "coverage": {
            "production_corpus_complete": production_complete,
            "repository_corpus_complete": inventory_complete,
            "collections": {
                name: section["coverage"] for name, section in sections.items()
            },
            "work": {
                "matching": matcher.coverage,
                "structural_matches": structural_work,
            },
        },
        "graph": {
            "present": structural.get("present"),
            "usable": graph_ok,
            "freshness": structural.get("freshness"),
            "warnings": list(structural.get("warnings", [])),
            "groups_dropped": groups_dropped,
            "groups_complete": groups_complete,
            "coverage": structural.get("coverage", {}).get("groups"),
        },
        # Backward-compatible convenience flag; `graph` carries the complete
        # state and distinguishes absent, unusable, stale, and unverified.
        "graph_available": graph_ok,
        "total_findings": total,
        "total_findings_complete": total_complete,
        "managed_context": managed_context or unchecked_managed_context(),
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
    complete = validation.get("total_findings_complete", True)
    count_label = "finding(s)" if complete else "evaluated finding(s)"
    print(
        f"validate: {validation['canonical_concepts']} canonical concept(s), "
        f"{validation['total_findings']} {count_label}"
    )
    print_managed_context_issues(validation["managed_context"])
    graph = validation["graph"]
    if graph["usable"]:
        freshness = graph["freshness"] or {
            "status": "unverified",
            "detail": "freshness metadata unavailable",
        }
        print(
            f"graphify: usable structural groups; freshness "
            f"{escape_terminal_text(freshness['status'])} — "
            f"{escape_terminal_text(freshness['detail'])}"
        )
        if graph.get("groups_dropped"):
            print(
                f"graphify coverage: partial — {graph['groups_dropped']} "
                "normalized group(s) omitted by the group cap"
            )
    elif graph["present"]:
        print(
            "graphify: graph present but no usable structural groups; "
            "structural checks skipped"
        )
    else:
        print("graphify: no graph; structural checks skipped")
    coverage = validation.get("coverage", {})
    if not coverage.get("production_corpus_complete", True):
        print(
            "corpus coverage: partial — absence and low-use findings were "
            "suppressed where the evidence cannot prove them"
        )
    collection_coverage = coverage.get("collections", {})
    limitations = list(dict.fromkeys(
        reason
        for key, ledger in collection_coverage.items()
        if (
            isinstance(ledger, dict)
            and not ledger.get("total_items_exact", True)
            and not validation.get(key, {}).get("skipped")
        )
        for reason in ledger.get("reasons", [])
    ))
    for reason in limitations:
        print(f"coverage limitation: {escape_terminal_text(reason)}")
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
            summary = escape_terminal_text(finding["summary"])
            safe_annotation = escape_terminal_text(annotation)
            print(f"{summary} [{safe_annotation}]")
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
    managed_context = inspect_managed_context(root, glossary)
    validation = build_validation(
        evidence,
        glossary,
        managed_context=managed_context,
    )
    write_artifact(root, VALIDATION_FILE, validation)
    for warning in validation["graph"]["warnings"]:
        print(
            f"graphify adapter: {escape_terminal_text(warning)}",
            file=sys.stderr,
        )
    _print_report(validation)
    return 0
