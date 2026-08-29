"""Reconciliation: does the glossary describe the system we actually built?

Two directions of coverage plus the mismatch taxonomy: unnamed structure,
orphaned concepts, unresolved bindings, boundary mismatch, fragmentation,
overloaded structural regions, and (delegated to the drift module)
vocabulary drift and concept collision. Heuristic thresholds are signal
strength, not unmeasured confidence — NO one-to-one community=concept
assumption anywhere, and every finding is evidence for the team, never an
automatic diagnosis.

This module composes the validation document: it runs the structural
(`structural_validation`) and binding (`binding_validation`) producers,
reuses drift, assembles the final coverage, and owns the view, the report,
and the command handler.
"""

from __future__ import annotations

import sys
from pathlib import Path

from glossabet.agent.managed_context import (
    ManagedContextReport,
    inspect_managed_context,
    print_managed_context_issues,
    unchecked_managed_context,
)
from glossabet.analysis.evidence import persist_evidence
from glossabet.analysis.evidence_types import EvidenceDocument
from glossabet.command_run import GLOSSARY_REQUIRED, open_run
from glossabet.glossary.binding_validation import (
    BindingResolution,
    build_binding_findings,
    build_concept_vocabulary,
)
from glossabet.glossary.drift import build_drift
from glossabet.glossary.findings import (
    FindingsDocumentView,
    FindingSection,
    SkippedValidationCheck,
    ValidationDocument,
    capped_section,
    collection_limitations,
    glossary_terms,
    matching_reasons,
    print_sections,
    production_corpus_reasons,
    vocabulary_omission_reasons,
)
from glossabet.glossary.matching import EvidenceIndex
from glossabet.glossary.model import GlossaryDocument
from glossabet.glossary.policy import (
    DEFAULT_RECONCILIATION_POLICY,
    ReconciliationPolicy,
)
from glossabet.glossary.repository_glossary import (
    RepositoryGlossarySection,
    repository_glossary_section,
)
from glossabet.glossary.store import concept_scope
from glossabet.glossary.structural_validation import (
    STRUCTURAL_MATCH_BUDGET,
    build_structural_validation,
)
from glossabet.runtime.artifacts import write_artifact
from glossabet.runtime.display import escape_terminal_text

__all__ = [
    "VALIDATION_SCHEMA_VERSION",
    "VALIDATION_FILE",
    "FRAGMENTATION_MIN_MODULES",
    "OVERLOADED_MIN_CONCEPTS",
    "STRUCTURAL_MATCH_BUDGET",
    "BindingResolution",
    "build_validation",
    "validate_command",
]

VALIDATION_SCHEMA_VERSION = 11
VALIDATION_FILE = "validation.json"

FRAGMENTATION_MIN_MODULES = DEFAULT_RECONCILIATION_POLICY.fragmentation_min_modules
OVERLOADED_MIN_CONCEPTS = DEFAULT_RECONCILIATION_POLICY.overloaded_min_concepts


def _unchecked_repository_glossary() -> RepositoryGlossarySection:
    """Validation's placeholder when the caller supplied no discovery
    record (pure builders without a repository)."""
    return {"checked": False}



def build_validation(
    evidence: EvidenceDocument,
    glossary: GlossaryDocument,
    *,
    managed_context: ManagedContextReport | None = None,
    repository_glossary: RepositoryGlossarySection | None = None,
    root: Path | None = None,
    policy: ReconciliationPolicy | None = None,
) -> ValidationDocument:
    """Findings are labelled under the calibrated ``policy`` (the default
    when omitted). ``root`` (the scanned repository, when the caller has it) lets a
    binding to a real file the inventory never lists (``Makefile``,
    ``config/settings.toml``) be judged ``uncertain`` rather than
    ``unresolved``; without it, existence cannot be checked and only the
    omission ledgers distinguish the two."""
    canonical = [
        c for c in glossary["concepts"] if c["status"] == "canonical"
    ]
    vocabulary = build_concept_vocabulary(canonical)
    global_canonical = [c for c in canonical if concept_scope(c) is None]
    scoped_canonical = [c for c in canonical if concept_scope(c) is not None]
    if policy is None:
        policy = DEFAULT_RECONCILIATION_POLICY
    structural = evidence["structural_groups"]
    matcher = EvidenceIndex(evidence, glossary_terms(glossary))

    structural_validation = build_structural_validation(
        structural,
        global_canonical,
        scoped_canonical,
        vocabulary,
        policy,
    )
    binding_findings = build_binding_findings(
        canonical, vocabulary, matcher, root, policy
    )
    graph = structural_validation.graph
    drift = build_drift(
        evidence,
        glossary,
        matcher=matcher,
        managed_context=managed_context,
    )
    drift_sections = FindingsDocumentView(drift)

    production_complete = matcher.production_corpus_complete
    inventory_complete = matcher.repository_corpus_complete
    production_reasons = production_corpus_reasons(production_complete)
    inventory_reasons = [] if inventory_complete else [
        "repository corpus budget omitted accepted inventory evidence"
    ]
    code_vocabulary_reasons = vocabulary_omission_reasons(
        evidence, ("tokens", "identifiers")
    )
    identifier_reasons = vocabulary_omission_reasons(
        evidence, ("identifiers",),
        "vocabulary.{name} omitted entries needed for binding resolution",
    )
    matching_limits = matching_reasons(matcher)

    sections: dict[str, FindingSection] = {
        "unnamed_structure": structural_validation.unnamed_structure,
        "boundary_mismatch": structural_validation.boundary_mismatch,
        "overloaded_structural_region": (
            structural_validation.overloaded_structural_region
        ),
        "orphaned_concepts": capped_section(
            binding_findings.orphaned_concepts,
            "orphaned concept",
            incomplete_reasons=(
                production_reasons + code_vocabulary_reasons + matching_limits
                + binding_findings.orphan_incompleteness_reasons
            ),
        ),
        "unresolved_bindings": capped_section(
            binding_findings.unresolved_bindings,
            "unresolved binding",
            incomplete_reasons=(
                inventory_reasons
                + identifier_reasons
                + binding_findings.binding_ledger_reasons
            ),
        ),
        "fragmentation": capped_section(
            binding_findings.fragmentation,
            "fragmentation",
            incomplete_reasons=(
                production_reasons + code_vocabulary_reasons + matching_limits
                + binding_findings.fragmentation_incompleteness_reasons
            ),
        ),
        "vocabulary_drift": drift_sections.section("parallel_terms"),
        "concept_collision": drift_sections.section("canonical_overloaded"),
    }
    total = sum(
        section["coverage"]["total_items"]
        for section in sections.values()
        if not section.get("skipped")
    )
    total_exact = all(
        section["coverage"]["total_items_exact"]
        for section in sections.values()
        if not section.get("skipped")
    )
    skipped_checks: list[SkippedValidationCheck] = []
    for name, section in sections.items():
        if not section.get("skipped"):
            continue
        reason = section.get("skip_reason")
        if reason is None:
            raise ValueError(f"skipped validation check {name} has no reason")
        skipped_checks.append({"name": name, "reason": reason})
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
                "structural_matches": structural_validation.matching_coverage,
            },
        },
        "finding_checks": {
            "all_executed": not skipped_checks,
            "skipped": skipped_checks,
        },
        "graph": {
            "present": graph.present,
            "usable": graph.usable,
            "freshness": graph.freshness,
            "warnings": list(graph.warnings),
            "groups_dropped": graph.groups_dropped,
            "groups_complete": graph.groups_complete,
            "coverage": graph.coverage,
        },
        "total_findings": total,
        "total_findings_exact": total_exact,
        "managed_context": managed_context or unchecked_managed_context(),
        # The repository's own root GLOSSARY.md: discovery record plus, when
        # structured state exists and the file was read completely, the
        # lexical term-presence divergence. Not a findings section: it is
        # one deterministic signal, never a diagnosis.
        "repository_glossary": (
            repository_glossary
            if repository_glossary is not None
            else _unchecked_repository_glossary()
        ),
        "unnamed_structure": sections["unnamed_structure"],
        "boundary_mismatch": sections["boundary_mismatch"],
        "overloaded_structural_region": sections["overloaded_structural_region"],
        "orphaned_concepts": sections["orphaned_concepts"],
        "unresolved_bindings": sections["unresolved_bindings"],
        "fragmentation": sections["fragmentation"],
        "vocabulary_drift": sections["vocabulary_drift"],
        "concept_collision": sections["concept_collision"],
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


def _print_report(document: ValidationDocument) -> None:
    sections = FindingsDocumentView(document)
    total_exact = document["total_findings_exact"]
    all_executed = document["finding_checks"]["all_executed"]
    if not total_exact:
        count_label = "known finding(s) from evaluated checks"
    elif not all_executed:
        count_label = "finding(s) from evaluated checks"
    else:
        count_label = "finding(s)"
    print(
        f"validate: {document['canonical_concepts']} canonical concept(s), "
        f"{document['total_findings']} {count_label}"
    )
    print_managed_context_issues(document["managed_context"])
    graph = document["graph"]
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
    if not document["coverage"]["production_corpus_complete"]:
        print(
            "corpus coverage: partial — absence and low-use findings were "
            "suppressed where the evidence cannot prove them"
        )
    for reason in collection_limitations(
        document["coverage"]["collections"], skip=sections.section_skipped,
    ):
        print(f"coverage limitation: {escape_terminal_text(reason)}")
    scopes = document["scope_summary"]
    if scopes["path_scoped"]:
        structural_state = "partial" if graph["usable"] else "unavailable"
        print(
            f"scopes: {scopes['path_scoped']} path-scoped concept(s); lexical "
            f"checks are scoped, structural scope coverage is {structural_state}"
        )
    print_sections(sections, _TITLES, detail=False)
    _print_repository_glossary(
        document.get("repository_glossary", _unchecked_repository_glossary())
    )
    print(
        "\nNo one-to-one community=concept assumption; findings are evidence "
        "for the team, never automatic diagnoses."
    )


def _print_repository_glossary(section: RepositoryGlossarySection) -> None:
    if not section.get("present"):
        return
    if not section.get("readable"):
        print(
            "\nrepository GLOSSARY.md: present but not read "
            f"({escape_terminal_text(str(section.get('reason')))}); "
            "no absence claims about it are possible"
        )
        return
    divergence = section.get("divergence")
    if divergence is None:
        return
    missing = divergence["canonical_missing_from_markdown"]
    superseded = divergence["superseded_terms_still_present"]
    if not missing and not superseded and divergence["complete"]:
        return
    print("\n== repository GLOSSARY.md divergence (lexical presence only) ==")
    for term in missing:
        print(
            f"canonical term {escape_terminal_text(term)} does not appear "
            "in GLOSSARY.md"
        )
    for item in superseded:
        print(
            f"{item['status']} term {escape_terminal_text(item['term'])} "
            "appears in GLOSSARY.md while its canonical term "
            f"{escape_terminal_text(item['canonical_term'])} does not"
        )
    if not divergence["complete"]:
        reason = divergence.get("reason")
        if reason:
            print(
                "... term-presence check not run: normalized GLOSSARY.md text "
                f"exceeds {divergence['text_cap']} characters; "
                f"{divergence['skipped_terms']} term(s) not checked"
            )
        else:
            print(
                f"... term-presence check capped at {divergence['term_cap']} "
                f"terms; {divergence['skipped_terms']} not checked"
            )


def validate_command(path_arg: str) -> int:
    run = open_run(
        path_arg, glossary=GLOSSARY_REQUIRED, missing="no glossary to validate"
    )
    evidence = persist_evidence(run.root)
    glossary = run.required_glossary
    managed_context = inspect_managed_context(run.root, glossary)
    validation = build_validation(
        evidence,
        glossary,
        managed_context=managed_context,
        repository_glossary=repository_glossary_section(
            run.root, evidence, run.glossary
        ),
        root=run.root,
    )
    write_artifact(run.root, VALIDATION_FILE, validation)
    for warning in validation["graph"]["warnings"]:
        print(
            f"graphify adapter: {escape_terminal_text(warning)}",
            file=sys.stderr,
        )
    _print_report(validation)
    return 0
