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
from glossarize.evidence import build_evidence, write_evidence
from glossarize.glossary import (
    concept_scope,
    path_in_scope,
    require_glossary,
    scope_evidence,
    scopes_overlap,
)
from glossarize.matching import code_term_occurrence, doc_term_occurrence
from glossarize.terminology import OVERLOAD_MIN_DISPERSION, OVERLOAD_MIN_MODULES
from glossarize.tokenize import tokenize_term

DRIFT_SCHEMA_VERSION = 3
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
                    known_scopes: dict) -> list[dict]:
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
                evidence, concept["term"], scope
            )
            new_occurrence = code_term_occurrence(evidence, new_term, scope)
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


def _watched_in_use(watched: list[dict], evidence: dict) -> list[dict]:
    """Discouraged or deprecated terms still present in the code."""
    findings: list[dict] = []
    for entry in watched:
        occurrence = code_term_occurrence(
            evidence, entry["term"], entry["scope"]
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


def _canonical_fading(glossary: dict, evidence: dict) -> list[dict]:
    """Canonical terms absent from code or barely hanging on."""
    findings: list[dict] = []
    for concept in glossary["concepts"]:
        if concept["status"] != "canonical":
            continue
        tokens = tokenize_term(concept["term"])
        if not tokens:
            continue
        scope = concept_scope(concept)
        occurrence = code_term_occurrence(evidence, concept["term"], scope)
        if not occurrence["count_complete"]:
            continue  # capped evidence cannot prove absence or low use
        count = occurrence["count"]
        # The current document index proves only one-token mentions. Separate
        # prose words are not treated as a compound occurrence.
        doc_occurrence = doc_term_occurrence(evidence, concept["term"], scope)
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
        for concept in canonical[item["term"]]:
            scope = concept_scope(concept)
            modules = [
                module for module in item["modules"]
                if path_in_scope(module["path"], scope)
            ]
            if scope is None:
                dispersion = item["dispersion"]
            else:
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
                },
                "summary": (
                    f"canonical '{concept['term']}' used in disjoint contexts "
                    f"across {len(modules)} module(s)"
                ),
            })
    findings.sort(key=lambda f: (
        -f["evidence"]["dispersion"], f["term"], f["concept_id"]
    ))
    return findings


def _capped(findings: list[dict]) -> tuple[list[dict], int]:
    return findings[:FINDINGS_PER_KIND_CAP], max(
        0, len(findings) - FINDINGS_PER_KIND_CAP
    )


def build_drift(evidence: dict, glossary: dict) -> dict:
    canonical, watched, known_scopes = _index_glossary(glossary)

    sections = {}
    total = 0
    for name, findings in (
        ("parallel_terms",
         _parallel_terms(evidence, canonical, known_scopes)),
        ("watched_terms_in_use", _watched_in_use(watched, evidence)),
        ("canonical_fading", _canonical_fading(glossary, evidence)),
        ("canonical_overloaded", _canonical_overloaded(evidence, canonical)),
    ):
        kept, dropped = _capped(findings)
        sections[name] = {"items": kept, "dropped_items": dropped}
        total += len(kept) + dropped

    return {
        "schema_version": DRIFT_SCHEMA_VERSION,
        "checked_concepts": len(glossary["concepts"]),
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
    print(
        f"drift check against {drift['checked_concepts']} glossary "
        f"concept(s): {drift['total_findings']} finding(s)"
    )
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
        for f in section["items"]:
            if "certainty" in f:
                annotation = f"certainty {f['certainty']}"
            else:
                annotation = f"signal {f['signal_strength']}"
            print(f"{f['summary']} [{annotation}]")
            if f.get("scope", {}).get("kind") == "path-prefixes":
                print(
                    "    scope: "
                    + ", ".join(f["scope"]["path_prefixes"])
                )
            ev = f["evidence"]
            if "shared_contexts" in ev:
                print(f"    shared contexts: {', '.join(ev['shared_contexts'])}")
            if "locations" in ev and ev["locations"]:
                sample = ", ".join(loc["path"] for loc in ev["locations"][:3])
                print(f"    e.g. {sample}")
            if isinstance(ev.get("modules"), list):
                print(
                    "    modules: "
                    + ", ".join(m["path"] for m in ev["modules"])
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
