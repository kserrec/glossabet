"""Vocabulary drift: compare fresh repository evidence against the canonical
glossary.

Four checks: new terms paralleling canonical vocabulary, discouraged or
deprecated terms still in use, canonical terms fading from code, and
canonical terms living disjoint lives (collision). Findings are evidence,
never verdicts and never auto-fixes. Heuristic thresholds are reported as
signal strength, not as unmeasured confidence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypedDict

from glossabet.agent.managed_context import (
    ManagedContextReport,
    inspect_managed_context,
    print_managed_context_issues,
    unchecked_managed_context,
)
from glossabet.analysis.evidence import persist_evidence
from glossabet.analysis.evidence_types import (
    EvidenceDocument,
    OverloadCandidatesSection,
    SynonymCandidatesSection,
)
from glossabet.analysis.policy import context_dispersion
from glossabet.command_run import GLOSSARY_REQUIRED, open_run
from glossabet.corpus.tokenize import tokenize_term
from glossabet.glossary.findings import (
    DriftDocument,
    FindingRecord,
    FindingsDocumentView,
    FindingSection,
    HeuristicFinding,
    ObservedFinding,
    capped_section,
    collection_limitations,
    glossary_terms,
    heuristic_finding,
    matching_reasons,
    observed_finding,
    print_sections,
    production_corpus_reasons,
    suppressed_reason,
    vocabulary_omission_reasons,
)
from glossabet.glossary.matching import EvidenceIndex, is_unproven_zero
from glossabet.glossary.model import ConceptRecord, ConceptScope, GlossaryDocument
from glossabet.glossary.policy import (
    DEFAULT_DRIFT_POLICY,
    DriftPolicy,
    fading_state,
    overload_signal,
    parallel_term_signal,
)
from glossabet.glossary.scope import (
    concept_scope,
    path_in_scope,
    scope_evidence,
    scopes_overlap,
)
from glossabet.runtime.artifacts import write_artifact
from glossabet.runtime.coverage import coverage_reasons
from glossabet.runtime.display import escape_terminal_text

DRIFT_SCHEMA_VERSION = 7
DRIFT_FILE = "drift.json"

FADING_MAX_COUNT = DEFAULT_DRIFT_POLICY.fading_max_count
# Cap on owner-scope overlap comparisons in _parallel_terms.
PARALLEL_SCOPE_COMPARISON_BUDGET = 500_000

_WATCHED_STATUSES = {"discouraged", "deprecated"}


class _WatchedEntry(TypedDict):
    """A discouraged or deprecated term (concept or alias) to look for."""

    term: str
    status: str
    concept_id: str
    tokens: list[str]
    scope: ConceptScope


def _index_glossary(glossary: GlossaryDocument) -> tuple[
    dict[str, list[ConceptRecord]], list[_WatchedEntry], dict[str, list[ConceptScope]]
]:
    """canonical token map, watched (discouraged/deprecated) entries, and the
    scopes in which every glossary token is already owned (any status)."""
    canonical: dict[str, list[ConceptRecord]] = {}
    watched: list[_WatchedEntry] = []
    known_scopes: dict[str, list[ConceptScope]] = {}
    for concept in glossary["concepts"]:
        scope = concept_scope(concept)
        tokens = tokenize_term(concept["term"])
        for token in tokens:
            known_scopes.setdefault(token, []).append(scope)
        # Synonym and overload candidates are token-level signals. Mapping one
        # word from a compound concept to the whole concept would recreate the
        # same cross-unit false match fixed by the exact occurrence checks.
        if concept["status"] == "canonical" and len(tokens) == 1:
            for token in tokens:
                canonical.setdefault(token, []).append(concept)
        if concept["status"] in _WATCHED_STATUSES:
            watched.append({"term": concept["term"], "status": concept["status"],
                            "concept_id": concept["id"], "tokens": tokens,
                            "scope": scope})
        for alias in concept.get("aliases", []):
            alias_tokens = tokenize_term(alias["term"])
            for token in alias_tokens:
                known_scopes.setdefault(token, []).append(scope)
            if alias["status"] in _WATCHED_STATUSES:
                watched.append({
                    "term": alias["term"], "status": alias["status"],
                    "concept_id": concept["id"], "tokens": alias_tokens,
                    "scope": scope,
                })
    # Distinct owner scopes only. A hostile glossary can register tens of
    # thousands of aliases mapping one token to the same scope; the overlap
    # scan below is otherwise O(owners), so deduplication removes that
    # amplification while preserving every distinct ownership.
    known_scopes = {
        token: list(dict.fromkeys(scopes))
        for token, scopes in known_scopes.items()
    }
    return canonical, watched, known_scopes


def _known_in_scope(
    token: str,
    scope: tuple[str, ...] | None,
    known_scopes: dict[str, list[ConceptScope]],
) -> bool:
    return any(scopes_overlap(scope, owner) for owner in known_scopes.get(token, []))


def _overlap_cost(
    scope: tuple[str, ...] | None,
    owners: "list[tuple[str, ...] | None] | tuple[tuple[str, ...] | None, ...]",
) -> int:
    """Prefix-pair work `_known_in_scope` will perform for this term.

    `scopes_overlap` is O(len(scope) x len(owner)) when both sides are
    path-scoped; a repository-wide (None) side short-circuits in O(1). The
    budget must be charged this real product, not the owner count, or a single
    concept carrying tens of thousands of prefixes hides a 100M+ comparison
    behind a charge of 1 and the ceiling never trips.
    """
    left = len(scope) if scope is not None else 1
    return sum(
        left * (len(owner) if owner is not None else 1) for owner in owners
    )


def _parallel_terms(
    evidence: EvidenceDocument, canonical: dict[str, list[ConceptRecord]],
    known_scopes: dict[str, list[ConceptScope]], matcher: EvidenceIndex,
    policy: DriftPolicy = DEFAULT_DRIFT_POLICY,
) -> tuple[list[HeuristicFinding], list[str]]:
    """New prominent terms that behave like an existing canonical term."""
    # (similarity, new term, concept id, finding): the ranking key beside
    # the record it orders.
    ranked: list[tuple[float, str, str, HeuristicFinding]] = []
    suppressed = 0
    # Owner-scope overlap is O(concepts x owner-scopes); a hostile glossary
    # can push that product into the hundreds of millions within the accepted
    # concept/alias ceilings. Bound the total comparisons and report the
    # section partial rather than spinning for minutes.
    comparisons_remaining = PARALLEL_SCOPE_COMPARISON_BUDGET
    budget_exhausted = False
    for item in evidence["terminology"]["synonym_candidates"]["items"]:
        a_canon = item["a"] in canonical
        b_canon = item["b"] in canonical
        if a_canon == b_canon:
            continue
        new_term = item["b"] if a_canon else item["a"]
        canon_token = item["a"] if a_canon else item["b"]
        for concept in canonical[canon_token]:
            scope = concept_scope(concept)
            owners = known_scopes.get(new_term, ())
            cost = _overlap_cost(scope, owners)
            if cost > comparisons_remaining:
                budget_exhausted = True
                break
            comparisons_remaining -= cost
            if _known_in_scope(new_term, scope, known_scopes):
                continue
            canonical_occurrence = matcher.code_term_occurrence(
                concept["term"], scope
            )
            new_occurrence = matcher.code_term_occurrence(new_term, scope)
            if not canonical_occurrence["count"] or not new_occurrence["count"]:
                zero_occurrences = [
                    occurrence
                    for occurrence in (canonical_occurrence, new_occurrence)
                    if occurrence["count"] == 0
                ]
                if all(is_unproven_zero(item) for item in zero_occurrences):
                    suppressed += 1
                continue
            similarity = item["similarity"]
            signal_strength = parallel_term_signal(similarity, policy)
            ranked.append((similarity, new_term, concept["id"], heuristic_finding(
                "parallel-term",
                f"new term '{new_term}' parallels canonical "
                f"'{concept['term']}' (similarity {similarity})",
                {
                    "similarity": similarity,
                    "shared_contexts": item["shared_contexts"],
                    "canonical_occurrence": canonical_occurrence,
                    "new_occurrence": new_occurrence,
                },
                signal_strength=signal_strength,
                scope=scope_evidence(scope),
                new_term=new_term,
                canonical_term=concept["term"],
                concept_id=concept["id"],
            )))
        if budget_exhausted:
            break
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    findings = [row[3] for row in ranked]
    reasons = suppressed_reason(suppressed, "parallel-term")
    if budget_exhausted:
        reasons.append(
            "parallel-term scope checks reached their comparison budget; "
            "results are partial"
        )
    return findings, reasons


def _watched_in_use(
    watched: list[_WatchedEntry], matcher: EvidenceIndex
) -> tuple[list[ObservedFinding], list[str]]:
    """Discouraged or deprecated terms still present in the code."""
    ranked: list[tuple[int, str, ObservedFinding]] = []  # (count, term, finding)
    suppressed = 0
    for entry in watched:
        occurrence = matcher.code_term_occurrence(entry["term"], entry["scope"])
        if occurrence["count"] == 0:
            if is_unproven_zero(occurrence):
                suppressed += 1
            continue
        count = occurrence["count"]
        quantity = f"at least {count}" if not occurrence["count_exact"] else str(count)
        ranked.append((count, entry["term"], observed_finding(
            "watched-term-in-use",
            f"{entry['status']} term '{entry['term']}' still in use: "
            f"{quantity} lexical occurrence(s)",
            occurrence,
            certainty="observed",
            scope=scope_evidence(entry["scope"]),
            term=entry["term"],
            status=entry["status"],
            concept_id=entry["concept_id"],
        )))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    findings = [row[2] for row in ranked]
    return findings, suppressed_reason(suppressed, "watched-term")


def _canonical_fading(
    glossary: GlossaryDocument, matcher: EvidenceIndex,
    policy: DriftPolicy = DEFAULT_DRIFT_POLICY,
) -> tuple[list[HeuristicFinding], list[str]]:
    """Canonical terms absent from code or barely hanging on."""
    findings: list[HeuristicFinding] = []
    suppressed = 0
    for concept in glossary["concepts"]:
        if concept["status"] != "canonical":
            continue
        tokens = tokenize_term(concept["term"])
        scope = concept_scope(concept)
        occurrence = matcher.code_term_occurrence(concept["term"], scope)
        count = occurrence["count"]
        if is_unproven_zero(occurrence):
            suppressed += 1
            continue
        # The current document index proves only one-token mentions. Separate
        # prose words are not treated as a compound occurrence.
        doc_occurrence = matcher.doc_term_occurrence(concept["term"], scope)
        doc_mentions = doc_occurrence["count"] if len(tokens) == 1 else None
        if not occurrence["count_exact"]:
            if (
                len(tokens) == 1
                and count <= policy.fading_max_count
                and doc_mentions == 0
            ):
                suppressed += 1
            continue
        if (
            count > 0
            and count <= policy.fading_max_count
            and is_unproven_zero(doc_occurrence)
        ):
            suppressed += 1
            continue
        fading = fading_state(
            count, doc_mentions, doc_occurrence["count_exact"], policy
        )
        if fading is None:
            continue
        signal_strength, state = fading
        finding_evidence: dict[str, object] = {
            **occurrence,
            "lexical_occurrences": count,
            "doc_mentions": doc_mentions,
        }
        if len(tokens) == 1:
            finding_evidence["token_counts"] = {tokens[0]: count}
        findings.append(heuristic_finding(
            "canonical-fading",
            f"canonical '{concept['term']}' is {state}",
            finding_evidence,
            signal_strength=signal_strength,
            scope=scope_evidence(scope),
            term=concept["term"],
            concept_id=concept["id"],
        ))
    findings.sort(key=lambda f: f["term"])
    return findings, suppressed_reason(suppressed, "canonical-fading")


def _overload_details_complete(item: Mapping[str, object]) -> bool:
    """Whether the retained module/context details cover the whole candidate.

    A capped display cannot be reinterpreted as an exhaustive scoped sample;
    the scoped-overload check and its omission report must agree on this.
    """
    # Read tolerantly: a candidate without ledgers (older or hand-built
    # evidence) is not reported as capped.
    coverage = item.get("coverage")
    module_coverage = (
        coverage.get("modules") if isinstance(coverage, Mapping) else None
    )
    if isinstance(module_coverage, Mapping) and not module_coverage.get(
        "complete", True
    ):
        return False
    modules = item["modules"]
    for module in modules if isinstance(modules, list) else []:
        module_ledgers = module.get("coverage") if isinstance(module, Mapping) else None
        contexts = (
            module_ledgers.get("contexts")
            if isinstance(module_ledgers, Mapping) else None
        )
        if isinstance(contexts, Mapping) and not contexts.get("complete", True):
            return False
    return True


def _canonical_overloaded(
    evidence: EvidenceDocument, canonical: dict[str, list[ConceptRecord]],
    policy: DriftPolicy = DEFAULT_DRIFT_POLICY,
) -> list[HeuristicFinding]:
    """Canonical terms used across contexts disjoint enough to collide."""
    # (dispersion, term, concept id, finding)
    ranked: list[tuple[float, str, str, HeuristicFinding]] = []
    for item in evidence["terminology"]["overload_candidates"]["items"]:
        if item["term"] not in canonical:
            continue
        module_coverage = item.get("coverage", {}).get("modules", {})
        scope_details_complete = _overload_details_complete(item)
        for concept in canonical[item["term"]]:
            scope = concept_scope(concept)
            modules = [
                module for module in item["modules"]
                if path_in_scope(module["path"], scope)
            ]
            if scope is None:
                dispersion = item["dispersion"]
                module_count = module_coverage.get(
                    "total_items", len(item["modules"])
                )
            else:
                if not scope_details_complete:
                    # The full-repository dispersion is valid, but a capped
                    # module/context display cannot be reinterpreted as an
                    # exhaustive scoped sample.
                    continue
                if len(modules) < policy.overload_min_modules:
                    continue
                scoped_dispersion = context_dispersion(
                    [set(module["contexts"]) for module in modules]
                )
                if scoped_dispersion is None:
                    continue
                dispersion = scoped_dispersion
                if dispersion < policy.overload_min_dispersion:
                    continue
                module_count = len(modules)
            ranked.append((dispersion, concept["term"], concept["id"], heuristic_finding(
                "canonical-overloaded",
                f"canonical '{concept['term']}' used in disjoint contexts "
                f"across {module_count} module(s)",
                {
                    "dispersion": dispersion,
                    "modules": modules,
                    "modules_coverage": module_coverage,
                },
                signal_strength=overload_signal(dispersion, policy),
                scope=scope_evidence(scope),
                term=concept["term"],
                concept_id=concept["id"],
            )))
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [row[3] for row in ranked]


def _terminology_reasons(
    candidate: SynonymCandidatesSection | OverloadCandidatesSection,
    name: str,
) -> list[str]:
    ledger = candidate.get("coverage")
    if isinstance(ledger, dict):
        return coverage_reasons(ledger, name)
    if candidate.get("dropped_items", 0):
        return [f"{name}: candidate details were dropped"]
    return []


def _scoped_overload_reasons(
    evidence: EvidenceDocument, canonical: dict[str, list[ConceptRecord]]
) -> list[str]:
    omitted = 0
    for item in evidence["terminology"]["overload_candidates"]["items"]:
        if _overload_details_complete(item):
            continue
        omitted += sum(
            concept_scope(concept) is not None
            for concept in canonical.get(item["term"], [])
        )
    if not omitted:
        return []
    return [
        f"{omitted} scoped overload check(s) omitted because retained "
        "module/context details are partial"
    ]


def build_drift(
    evidence: EvidenceDocument,
    glossary: GlossaryDocument,
    *,
    matcher: EvidenceIndex | None = None,
    managed_context: ManagedContextReport | None = None,
    policy: DriftPolicy | None = None,
) -> DriftDocument:
    """The drift document for ``evidence`` against ``glossary``; findings
    are labelled under the calibrated ``policy`` (the default when omitted)."""
    if policy is None:
        policy = DEFAULT_DRIFT_POLICY
    canonical, watched, known_scopes = _index_glossary(glossary)
    matcher = matcher or EvidenceIndex(evidence, glossary_terms(glossary))

    corpus_complete = matcher.production_corpus_complete
    corpus_reasons = production_corpus_reasons(corpus_complete)
    vocabulary_reasons = vocabulary_omission_reasons(
        evidence, ("tokens", "identifiers", "doc_terms")
    )
    matching_limits = matching_reasons(matcher)

    parallel_findings, parallel_suppressed = _parallel_terms(
        evidence, canonical, known_scopes, matcher, policy
    )
    watched_findings, watched_suppressed = _watched_in_use(watched, matcher)
    fading_findings, fading_suppressed = _canonical_fading(
        glossary, matcher, policy
    )
    sections: dict[str, FindingSection] = {}
    producers: list[tuple[str, Sequence[FindingRecord], list[str]]] = [
        (
            "parallel_terms",
            parallel_findings,
            corpus_reasons
            + _terminology_reasons(
                evidence["terminology"]["synonym_candidates"],
                "synonym_candidates",
            )
            + parallel_suppressed,
        ),
        (
            "watched_terms_in_use",
            watched_findings,
            corpus_reasons + vocabulary_reasons + matching_limits
            + watched_suppressed,
        ),
        (
            "canonical_fading",
            fading_findings,
            corpus_reasons + vocabulary_reasons + matching_limits
            + fading_suppressed,
        ),
        (
            "canonical_overloaded",
            _canonical_overloaded(evidence, canonical, policy),
            corpus_reasons
            + _terminology_reasons(
                evidence["terminology"]["overload_candidates"],
                "overload_candidates",
            )
            + _scoped_overload_reasons(evidence, canonical),
        ),
    ]
    for name, findings, reasons in producers:
        sections[name] = capped_section(
            findings, name, incomplete_reasons=reasons,
        )

    total = sum(
        section["coverage"]["total_items"] for section in sections.values()
    )
    total_exact = all(
        section["coverage"]["total_items_exact"]
        for section in sections.values()
    )
    return {
        "schema_version": DRIFT_SCHEMA_VERSION,
        "checked_concepts": len(glossary["concepts"]),
        "coverage": {
            "production_corpus_complete": corpus_complete,
            "collections": {
                name: section["coverage"] for name, section in sections.items()
            },
            "work": {"matching": matcher.coverage},
        },
        "total_findings_complete": total_exact,
        "scope_summary": {
            "repository": sum(
                concept_scope(concept) is None for concept in glossary["concepts"]
            ),
            "path_scoped": sum(
                concept_scope(concept) is not None for concept in glossary["concepts"]
            ),
        },
        "total_findings": total,
        "managed_context": managed_context or unchecked_managed_context(),
        "parallel_terms": sections["parallel_terms"],
        "watched_terms_in_use": sections["watched_terms_in_use"],
        "canonical_fading": sections["canonical_fading"],
        "canonical_overloaded": sections["canonical_overloaded"],
    }


_TITLES = {
    "parallel_terms": "new terms paralleling canonical vocabulary",
    "watched_terms_in_use": "discouraged/deprecated terms still in use",
    "canonical_fading": "canonical terms fading from code",
    "canonical_overloaded": "canonical terms in disjoint contexts",
}


def _print_report(document: DriftDocument) -> None:
    sections = FindingsDocumentView(document)
    complete = document.get("total_findings_complete", True)
    count_label = "finding(s)" if complete else "evaluated finding(s)"
    print(
        f"drift check against {document['checked_concepts']} glossary "
        f"concept(s): {document['total_findings']} {count_label}"
    )
    print_managed_context_issues(document["managed_context"])
    if not document["coverage"]["production_corpus_complete"]:
        print(
            "corpus coverage is partial; absence and low-use findings were "
            "suppressed where the evidence cannot prove them"
        )
    for reason in collection_limitations(document["coverage"]["collections"]):
        print(f"coverage limitation: {escape_terminal_text(reason)}")
    print_sections(sections, _TITLES, detail=True)
    if document["total_findings"]:
        print(
            "\nFindings are evidence for the team, not verdicts — "
            "nothing is auto-fixed."
        )


def drift_command(path_arg: str) -> int:
    run = open_run(
        path_arg, glossary=GLOSSARY_REQUIRED,
        missing="no glossary to check against",
    )
    evidence = persist_evidence(run.root)
    glossary = run.required_glossary
    managed_context = inspect_managed_context(run.root, glossary)
    drift = build_drift(evidence, glossary, managed_context=managed_context)
    write_artifact(run.root, DRIFT_FILE, drift)
    _print_report(drift)
    return 0
