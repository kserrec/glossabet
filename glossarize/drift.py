"""Vocabulary drift: compare fresh repository evidence against the canonical
glossary.

Four checks: new terms paralleling canonical vocabulary, discouraged or
deprecated terms still in use, canonical terms fading from code, and
canonical terms living disjoint lives (collision). Findings are evidence
with confidence, never verdicts, and never auto-fixes.
"""

from __future__ import annotations

from glossarize.artifacts import repo_root, write_artifact
from glossarize.evidence import build_evidence, write_evidence
from glossarize.glossary import require_glossary
from glossarize.tokenize import tokenize_term

DRIFT_SCHEMA_VERSION = 1
DRIFT_FILE = "drift.json"

FINDINGS_PER_KIND_CAP = 10
FADING_MAX_COUNT = 2

_WATCHED_STATUSES = {"discouraged", "deprecated"}


def _index_glossary(glossary: dict):
    """canonical token map, watched (discouraged/deprecated) entries, and the
    set of every token any glossary entry uses (any status)."""
    canonical: dict[str, list[dict]] = {}
    watched: list[dict] = []
    all_tokens: set[str] = set()
    for concept in glossary["concepts"]:
        tokens = tokenize_term(concept["term"])
        all_tokens.update(tokens)
        if concept["status"] == "canonical":
            for token in tokens:
                canonical.setdefault(token, []).append(concept)
        if concept["status"] in _WATCHED_STATUSES:
            watched.append({"term": concept["term"], "status": concept["status"],
                            "concept_id": concept["id"], "tokens": tokens})
        for alias in concept.get("aliases", []):
            alias_tokens = tokenize_term(alias["term"])
            all_tokens.update(alias_tokens)
            if alias["status"] in _WATCHED_STATUSES:
                watched.append({
                    "term": alias["term"], "status": alias["status"],
                    "concept_id": concept["id"], "tokens": alias_tokens,
                })
    return canonical, watched, all_tokens


def _parallel_terms(evidence: dict, canonical: dict,
                    all_glossary_tokens: set[str]) -> list[dict]:
    """New prominent terms that behave like an existing canonical term."""
    findings: list[dict] = []
    for item in evidence["terminology"]["synonym_candidates"]["items"]:
        a_canon = item["a"] in canonical
        b_canon = item["b"] in canonical
        if a_canon == b_canon:
            continue
        new_term = item["b"] if a_canon else item["a"]
        canon_token = item["a"] if a_canon else item["b"]
        if new_term in all_glossary_tokens:
            continue  # already part of the settled vocabulary in some role
        concept = canonical[canon_token][0]
        similarity = item["similarity"]
        confidence = ("high" if similarity >= 0.7
                      else "medium" if similarity >= 0.55 else "low")
        findings.append({
            "kind": "parallel-term",
            "confidence": confidence,
            "new_term": new_term,
            "canonical_term": concept["term"],
            "concept_id": concept["id"],
            "evidence": {
                "similarity": similarity,
                "shared_contexts": item["shared_contexts"],
            },
            "summary": (
                f"new term '{new_term}' parallels canonical "
                f"'{concept['term']}' (similarity {similarity})"
            ),
        })
    findings.sort(key=lambda f: (-f["evidence"]["similarity"], f["new_term"]))
    return findings


def _watched_in_use(watched: list[dict], token_entries: dict) -> list[dict]:
    """Discouraged or deprecated terms still present in the code."""
    findings: list[dict] = []
    for entry in watched:
        hits = [token_entries[t] for t in entry["tokens"] if t in token_entries]
        if len(hits) != len(entry["tokens"]) or not hits:
            continue
        count = min(h["count"] for h in hits)
        weakest = min(hits, key=lambda h: h["count"])
        findings.append({
            "kind": "watched-term-in-use",
            "confidence": "high",
            "term": entry["term"],
            "status": entry["status"],
            "concept_id": entry["concept_id"],
            "evidence": {
                "count": count,
                "files": weakest["files"],
                "locations": weakest["locations"],
            },
            "summary": (
                f"{entry['status']} term '{entry['term']}' still in use: "
                f"{count} occurrence(s) across {weakest['files']} file(s)"
            ),
        })
    findings.sort(key=lambda f: (-f["evidence"]["count"], f["term"]))
    return findings


def _canonical_fading(glossary: dict, token_entries: dict,
                      doc_entries: dict) -> list[dict]:
    """Canonical terms absent from code or barely hanging on."""
    findings: list[dict] = []
    for concept in glossary["concepts"]:
        if concept["status"] != "canonical":
            continue
        tokens = tokenize_term(concept["term"])
        if not tokens:
            continue
        counts = {t: token_entries.get(t, {}).get("count", 0) for t in tokens}
        min_count = min(counts.values())
        doc_mentions = sum(doc_entries.get(t, 0) for t in tokens)
        if min_count == 0:
            confidence, state = "high", "absent from code"
        elif min_count <= FADING_MAX_COUNT and not doc_mentions:
            confidence, state = "medium", "fading"
        else:
            continue
        findings.append({
            "kind": "canonical-fading",
            "confidence": confidence,
            "term": concept["term"],
            "concept_id": concept["id"],
            "evidence": {"token_counts": counts, "doc_mentions": doc_mentions},
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
        concept = canonical[item["term"]][0]
        findings.append({
            "kind": "canonical-overloaded",
            "confidence": "high" if item["dispersion"] >= 0.95 else "medium",
            "term": concept["term"],
            "concept_id": concept["id"],
            "evidence": {
                "dispersion": item["dispersion"],
                "modules": item["modules"],
            },
            "summary": (
                f"canonical '{concept['term']}' used in disjoint contexts "
                f"across {len(item['modules'])} module(s)"
            ),
        })
    findings.sort(key=lambda f: (-f["evidence"]["dispersion"], f["term"]))
    return findings


def _capped(findings: list[dict]) -> tuple[list[dict], int]:
    return findings[:FINDINGS_PER_KIND_CAP], max(
        0, len(findings) - FINDINGS_PER_KIND_CAP
    )


def build_drift(evidence: dict, glossary: dict) -> dict:
    canonical, watched, all_glossary_tokens = _index_glossary(glossary)
    token_entries = {
        t["term"]: t for t in evidence["vocabulary"]["tokens"]["items"]
    }
    doc_entries = {
        t["term"]: t["count"]
        for t in evidence["vocabulary"]["doc_terms"]["items"]
    }

    sections = {}
    total = 0
    for name, findings in (
        ("parallel_terms",
         _parallel_terms(evidence, canonical, all_glossary_tokens)),
        ("watched_terms_in_use", _watched_in_use(watched, token_entries)),
        ("canonical_fading",
         _canonical_fading(glossary, token_entries, doc_entries)),
        ("canonical_overloaded", _canonical_overloaded(evidence, canonical)),
    ):
        kept, dropped = _capped(findings)
        sections[name] = {"items": kept, "dropped_items": dropped}
        total += len(kept)

    return {
        "schema_version": DRIFT_SCHEMA_VERSION,
        "checked_concepts": len(glossary["concepts"]),
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
            print(f"{f['summary']} [confidence {f['confidence']}]")
            ev = f["evidence"]
            if "shared_contexts" in ev:
                print(f"    shared contexts: {', '.join(ev['shared_contexts'])}")
            if "locations" in ev and ev["locations"]:
                sample = ", ".join(loc["path"] for loc in ev["locations"][:3])
                print(f"    e.g. {sample}")
            if "modules" in ev:
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
