"""Vocabulary drift: compare fresh repository evidence against the canonical
glossary.

Four checks: new terms paralleling canonical vocabulary, discouraged or
deprecated terms still in use, canonical terms fading from code, and
canonical terms living disjoint lives (collision). Findings are evidence,
never verdicts and never auto-fixes. Heuristic thresholds are reported as
signal strength, not as unmeasured confidence.
"""

from __future__ import annotations

from itertools import combinations

from glossarize.artifacts import repo_root, write_artifact
from glossarize.coverage import capped_collection, coverage_reasons
from glossarize.display import escape_terminal_text
from glossarize.evidence import build_evidence, write_evidence
from glossarize.glossary import (
    concept_scope,
    path_in_scope,
    require_glossary,
    scope_evidence,
    scopes_overlap,
)
from glossarize.matching import (
    EvidenceIndex,
    code_term_occurrence,
    doc_term_occurrence,
    production_corpus_complete,
)
from glossarize.terminology import OVERLOAD_MIN_DISPERSION, OVERLOAD_MIN_MODULES
from glossarize.tokenize import tokenize_term

DRIFT_SCHEMA_VERSION = 5
DRIFT_FILE = "drift.json"

FINDINGS_PER_KIND_CAP = 10
FADING_MAX_COUNT = 2

_WATCHED_STATUSES = {"discouraged", "deprecated"}


def _index_glossary(glossary: dict):
    """canonical token map, watched (discouraged/deprecated) entries, and the
    scopes in which every glossary token is already owned (any status)."""
    canonical: dict[str, list[dict]] = {}
    watched: list[dict] = []
    known_scopes: dict[str, list[tuple[str, ...] | None]] = {}
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
    return canonical, watched, known_scopes


def _known_in_scope(
    token: str,
    scope: tuple[str, ...] | None,
    known_scopes: dict[str, list[tuple[str, ...] | None]],
) -> bool:
    return any(scopes_overlap(scope, owner) for owner in known_scopes.get(token, []))


def _parallel_terms(evidence: dict, canonical: dict,
                    known_scopes: dict, matcher: EvidenceIndex) -> list[dict]:
    """New prominent terms that behave like an existing canonical term."""
    findings: list[dict] = []
    for item in evidence["terminology"]["synonym_candidates"]["items"]:
        a_canon = item["a"] in canonical
        b_canon = item["b"] in canonical
        if a_canon == b_canon:
            continue
        new_term = item["b"] if a_canon else item["a"]
        canon_token = item["a"] if a_canon else item["b"]
        for concept in canonical[canon_token]:
            scope = concept_scope(concept)
            if _known_in_scope(new_term, scope, known_scopes):
                continue
            canonical_occurrence = code_term_occurrence(
                evidence, concept["term"], scope, index=matcher
            )
            new_occurrence = code_term_occurrence(
                evidence, new_term, scope, index=matcher
            )
            if not canonical_occurrence["count"] or not new_occurrence["count"]:
                continue
            similarity = item["similarity"]
            signal_strength = (
                "strong" if similarity >= 0.7
                else "moderate" if similarity >= 0.55
                else "weak"
            )
            findings.append({
                "kind": "parallel-term",
                "signal_strength": signal_strength,
                "new_term": new_term,
                "canonical_term": concept["term"],
                "concept_id": concept["id"],
                "scope": scope_evidence(scope),
                "evidence": {
                    "similarity": similarity,
                    "shared_contexts": item["shared_contexts"],
                    "canonical_occurrence": canonical_occurrence,
                    "new_occurrence": new_occurrence,
                },
                "summary": (
                    f"new term '{new_term}' parallels canonical "
                    f"'{concept['term']}' (similarity {similarity})"
                ),
            })
    findings.sort(key=lambda f: (
        -f["evidence"]["similarity"], f["new_term"], f["concept_id"]
    ))
    return findings


def _watched_in_use(
    watched: list[dict], evidence: dict, matcher: EvidenceIndex
) -> list[dict]:
    """Discouraged or deprecated terms still present in the code."""
    findings: list[dict] = []
    for entry in watched:
        occurrence = code_term_occurrence(
            evidence, entry["term"], entry["scope"], index=matcher
        )
        if occurrence["count"] == 0:
            continue
        count = occurrence["count"]
        quantity = f"at least {count}" if not occurrence["count_complete"] else str(count)
        findings.append({
            "kind": "watched-term-in-use",
            "certainty": "observed",
            "term": entry["term"],
            "status": entry["status"],
            "concept_id": entry["concept_id"],
            "scope": scope_evidence(entry["scope"]),
            "evidence": occurrence,
            "summary": (
                f"{entry['status']} term '{entry['term']}' still in use: "
                f"{quantity} lexical occurrence(s)"
            ),
        })
    findings.sort(key=lambda f: (-f["evidence"]["count"], f["term"]))
    return findings


def _canonical_fading(
    glossary: dict, evidence: dict, matcher: EvidenceIndex
) -> list[dict]:
    """Canonical terms absent from code or barely hanging on."""
    findings: list[dict] = []
    for concept in glossary["concepts"]:
        if concept["status"] != "canonical":
            continue
        tokens = tokenize_term(concept["term"])
        if not tokens:
            continue
        scope = concept_scope(concept)
        occurrence = code_term_occurrence(
            evidence, concept["term"], scope, index=matcher
        )
        if not occurrence["count_complete"]:
            continue  # capped evidence cannot prove absence or low use
        count = occurrence["count"]
        # The current document index proves only one-token mentions. Separate
        # prose words are not treated as a compound occurrence.
        doc_occurrence = doc_term_occurrence(
            evidence, concept["term"], scope, index=matcher
        )
        doc_mentions = doc_occurrence["count"] if len(tokens) == 1 else None
        if count == 0:
            signal_strength, state = "strong", "absent from code"
        elif (
            count <= FADING_MAX_COUNT
            and doc_mentions == 0
            and doc_occurrence["count_complete"]
        ):
            signal_strength, state = "moderate", "fading"
        else:
            continue
        finding_evidence = {
            **occurrence,
            "lexical_occurrences": count,
            "doc_mentions": doc_mentions,
        }
        if len(tokens) == 1:
            finding_evidence["token_counts"] = {tokens[0]: count}
        findings.append({
            "kind": "canonical-fading",
            "signal_strength": signal_strength,
            "term": concept["term"],
            "concept_id": concept["id"],
            "scope": scope_evidence(scope),
            "evidence": finding_evidence,
            "summary": f"canonical '{concept['term']}' is {state}",
        })
    findings.sort(key=lambda f: f["term"])
    return findings


def _canonical_overloaded(evidence: dict, canonical: dict) -> list[dict]:
    """Canonical terms used across contexts disjoint enough to collide."""
    findings: list[dict] = []
    for item in evidence["terminology"]["overload_candidates"]["items"]:
        if item["term"] not in canonical:
            continue
        module_coverage = item.get("coverage", {}).get("modules", {})
        scope_details_complete = (
            module_coverage.get("complete", True)
            and all(
                module.get("coverage", {}).get("contexts", {}).get(
                    "complete", True
                )
                for module in item["modules"]
            )
        )
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
                if len(modules) < OVERLOAD_MIN_MODULES:
                    continue
                context_sets = [set(module["contexts"]) for module in modules]
                similarities = [
                    len(left & right) / len(left | right)
                    for left, right in combinations(context_sets, 2)
                    if left | right
                ]
                if not similarities:
                    continue
                dispersion = round(1.0 - sum(similarities) / len(similarities), 3)
                if dispersion < OVERLOAD_MIN_DISPERSION:
                    continue
                module_count = len(modules)
            findings.append({
                "kind": "canonical-overloaded",
                "signal_strength": (
                    "strong" if dispersion >= 0.95 else "moderate"
                ),
                "term": concept["term"],
                "concept_id": concept["id"],
                "scope": scope_evidence(scope),
                "evidence": {
                    "dispersion": dispersion,
                    "modules": modules,
                    "modules_coverage": module_coverage,
                },
                "summary": (
                    f"canonical '{concept['term']}' used in disjoint contexts "
                    f"across {module_count} module(s)"
                ),
            })
    findings.sort(key=lambda f: (
        -f["evidence"]["dispersion"], f["term"], f["concept_id"]
    ))
    return findings


def _capped(
    findings: list[dict], name: str, incomplete_reasons: list[str]
) -> dict:
    kept, coverage = capped_collection(
        findings,
        FINDINGS_PER_KIND_CAP,
        cap_reason=(
            f"{name} finding detail cap is {FINDINGS_PER_KIND_CAP} items"
        ),
        total_items_exact=not incomplete_reasons,
        incomplete_reasons=incomplete_reasons,
    )
    return {
        "items": kept,
        "dropped_items": coverage["dropped_items"],
        "coverage": coverage,
    }


def _glossary_terms(glossary: dict) -> list[str]:
    return [
        term
        for concept in glossary["concepts"]
        for term in (
            concept["term"],
            *(alias["term"] for alias in concept.get("aliases", [])),
        )
    ]


def _terminology_reasons(evidence: dict, section: str) -> list[str]:
    candidate = evidence["terminology"][section]
    ledger = candidate.get("coverage")
    if isinstance(ledger, dict):
        return coverage_reasons(ledger, section)
    if candidate.get("dropped_items", 0):
        return [f"{section}: candidate details were dropped"]
    return []


def _scoped_overload_reasons(evidence: dict, canonical: dict) -> list[str]:
    omitted = 0
    for item in evidence["terminology"]["overload_candidates"]["items"]:
        module_coverage = item.get("coverage", {}).get("modules", {})
        details_complete = (
            module_coverage.get("complete", True)
            and all(
                module.get("coverage", {}).get("contexts", {}).get(
                    "complete", True
                )
                for module in item["modules"]
            )
        )
        if details_complete:
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
    evidence: dict,
    glossary: dict,
    *,
    matcher: EvidenceIndex | None = None,
) -> dict:
    canonical, watched, known_scopes = _index_glossary(glossary)
    matcher = matcher or EvidenceIndex(evidence, _glossary_terms(glossary))

    corpus_complete = production_corpus_complete(evidence)
    corpus_reasons = [] if corpus_complete else [
        "production corpus budget omitted accepted source evidence"
    ]
    vocabulary_reasons = []
    for name in ("tokens", "identifiers", "doc_terms"):
        if evidence["vocabulary"][name].get("truncated") is not None:
            vocabulary_reasons.append(
                f"vocabulary.{name} omitted entries needed for exact matching"
            )
    matching_reasons = [
        reason
        for name, ledger in matcher.coverage.items()
        for reason in coverage_reasons(ledger, f"matching.{name}")
    ]

    sections = {}
    for name, findings, reasons in (
        (
            "parallel_terms",
            _parallel_terms(evidence, canonical, known_scopes, matcher),
            corpus_reasons
            + _terminology_reasons(evidence, "synonym_candidates"),
        ),
        (
            "watched_terms_in_use",
            _watched_in_use(watched, evidence, matcher),
            corpus_reasons + vocabulary_reasons + matching_reasons,
        ),
        (
            "canonical_fading",
            _canonical_fading(glossary, evidence, matcher),
            corpus_reasons + vocabulary_reasons + matching_reasons,
        ),
        (
            "canonical_overloaded",
            _canonical_overloaded(evidence, canonical),
            corpus_reasons
            + _terminology_reasons(evidence, "overload_candidates")
            + _scoped_overload_reasons(evidence, canonical),
        ),
    ):
        sections[name] = _capped(findings, name, reasons)

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
        **sections,
    }


def _print_report(drift: dict) -> None:
    complete = drift.get("total_findings_complete", True)
    count_label = "finding(s)" if complete else "evaluated finding(s)"
    print(
        f"drift check against {drift['checked_concepts']} glossary "
        f"concept(s): {drift['total_findings']} {count_label}"
    )
    if not drift.get("coverage", {}).get("production_corpus_complete", True):
        print(
            "corpus coverage is partial; absence and low-use findings were "
            "suppressed where the evidence cannot prove them"
        )
    collection_coverage = drift.get("coverage", {}).get("collections", {})
    limitations = list(dict.fromkeys(
        reason
        for ledger in collection_coverage.values()
        if isinstance(ledger, dict) and not ledger.get("total_items_exact", True)
        for reason in ledger.get("reasons", [])
    ))
    for reason in limitations:
        print(f"coverage limitation: {escape_terminal_text(reason)}")
    titles = {
        "parallel_terms": "new terms paralleling canonical vocabulary",
        "watched_terms_in_use": "discouraged/deprecated terms still in use",
        "canonical_fading": "canonical terms fading from code",
        "canonical_overloaded": "canonical terms in disjoint contexts",
    }
    for key, title in titles.items():
        section = drift[key]
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
            if finding.get("scope", {}).get("kind") == "path-prefixes":
                print(
                    "    scope: "
                    + ", ".join(
                        escape_terminal_text(path)
                        for path in finding["scope"]["path_prefixes"]
                    )
                )
            evidence = finding["evidence"]
            if "shared_contexts" in evidence:
                print(
                    "    shared contexts: "
                    + ", ".join(
                        escape_terminal_text(context)
                        for context in evidence["shared_contexts"]
                    )
                )
            if "locations" in evidence and evidence["locations"]:
                sample = ", ".join(
                    escape_terminal_text(location["path"])
                    for location in evidence["locations"][:3]
                )
                print(f"    e.g. {sample}")
            if isinstance(evidence.get("modules"), list):
                print(
                    "    modules: "
                    + ", ".join(
                        escape_terminal_text(module["path"])
                        for module in evidence["modules"]
                    )
                )
        if section["dropped_items"]:
            print(f"... and {section['dropped_items']} more not shown")
    if drift["total_findings"]:
        print(
            "\nFindings are evidence for the team, not verdicts — "
            "nothing is auto-fixed."
        )


def drift_command(path_arg: str) -> int:
    root = repo_root(path_arg)
    if root is None:
        return 1
    glossary = require_glossary(root, "no glossary to check against")
    if glossary is None:
        return 1
    evidence = build_evidence(root, cache=True)
    write_evidence(root, evidence)
    drift = build_drift(evidence, glossary)
    write_artifact(root, DRIFT_FILE, drift)
    _print_report(drift)
    return 0
