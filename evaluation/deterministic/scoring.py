"""Deterministic scoring families: lexical (terminology labels), register,
nomination, drift, and structural — each formula kept whole in one place.

Every scorer takes the production document the engine actually produced
(``EvidenceDocument``, ``DriftDocument``, ``ValidationDocument``) together
with the manifest's labelled expectation and returns a serializable score
block. Truncation is reported, never hidden: a capped evidence section
marks the affected recall as unmeasured rather than as zero.
"""

from __future__ import annotations

from evaluation.deterministic.contract import (
    DRIFT_SECTIONS,
    STRUCTURAL_SECTIONS,
    EvaluationError,
)
from glossabet.analysis.evidence_facts import vocabulary_truncation
from glossabet.analysis.evidence_types import EvidenceDocument
from glossabet.analysis.importance import (
    NOMINATION_CANONICAL_NAME,
    NOMINATION_DISAMBIGUATION,
)
from glossabet.corpus.tokenize import STRUCTURED_IDENTIFIER_STYLES
from glossabet.glossary.findings import (
    DriftDocument,
    FindingsDocumentView,
    ValidationDocument,
)
from glossabet.glossary.reconcile import (
    build_validation,
)


def terminology_keys(evidence: dict) -> set[str]:
    return set(terminology_items(evidence))


def terminology_items(evidence: dict) -> dict[str, tuple[str, dict]]:
    terminology = evidence["terminology"]
    items: dict[str, tuple[str, dict]] = {}
    for item in terminology["synonym_candidates"]["items"]:
        key = "synonym:" + ":".join(sorted((item["a"], item["b"])))
        items[key] = ("synonym-candidate", item)
    for item in terminology["overload_candidates"]["items"]:
        items[f"overload:{item['term']}"] = ("overload-candidate", item)
    return items


def drift_key(section: str, finding: dict) -> tuple[str, str]:
    if section == "parallel_terms":
        return (
            "parallel-term",
            f"parallel-term:{finding['concept_id']}:{finding['new_term']}",
        )
    if section == "watched_terms_in_use":
        return (
            "watched-term-in-use",
            "watched-term-in-use:"
            f"{finding['concept_id']}:{finding['term'].casefold()}",
        )
    if section == "canonical_fading":
        return "canonical-fading", f"canonical-fading:{finding['concept_id']}"
    return (
        "canonical-overloaded",
        f"canonical-overloaded:{finding['concept_id']}",
    )


def drift_keys(drift: dict) -> dict[str, str]:
    return {
        key: kind for key, (kind, _) in drift_items(drift).items()
    }


def drift_items(drift: dict) -> dict[str, tuple[str, dict]]:
    sections = FindingsDocumentView(drift)
    return {
        key: (kind, finding)
        for section in DRIFT_SECTIONS
        for finding in sections.items(section)
        for kind, key in [drift_key(section, finding)]
    }


def structural_key(section: str, finding: dict) -> str:
    if section == "unnamed_structure":
        return f"unnamed-structure:{finding['group']}"
    if section == "boundary_mismatch":
        a, b = sorted(finding["concepts"])
        return f"boundary-mismatch:{finding['group']}:{a}:{b}"
    if section == "overloaded_structural_region":
        return f"overloaded-structural-region:{finding['group']}"
    if section == "orphaned_concepts":
        return f"orphaned-concept:{finding['concept_id']}"
    return f"fragmentation:{finding['concept_id']}"


def structural_keys(validation: dict) -> dict[str, tuple[str, dict]]:
    sections = FindingsDocumentView(validation)
    return {
        structural_key(section, finding): (section, finding)
        for section in STRUCTURAL_SECTIONS
        for finding in sections.items(section)
    }


def review_items(
    source_id: str,
    evidence: EvidenceDocument,
    drift: DriftDocument,
    validation: ValidationDocument | None,
) -> list[dict]:
    items: list[dict] = []

    for key, (kind, finding) in sorted(terminology_items(evidence).items()):
        if kind == "synonym-candidate":
            summary = (
                f"'{finding['a']}' and '{finding['b']}' may be parallel terms"
            )
        else:
            summary = f"'{finding['term']}' may carry unrelated meanings"
        items.append({
            "review_key": f"{source_id}|terminology|{key}",
            "source_id": source_id,
            "surface": "terminology",
            "finding_key": key,
            "kind": kind,
            "summary": summary,
            "evidence": finding,
        })

    for key, (kind, finding) in sorted(drift_items(drift).items()):
        items.append({
            "review_key": f"{source_id}|drift|{key}",
            "source_id": source_id,
            "surface": "drift",
            "finding_key": key,
            "kind": kind,
            "summary": finding["summary"],
            "evidence": finding.get("evidence", {}),
        })

    if validation is not None:
        for key, (_section, finding) in sorted(
            structural_keys(validation).items()
        ):
            items.append({
                "review_key": f"{source_id}|structural|{key}",
                "source_id": source_id,
                "surface": "structural",
                "finding_key": key,
                "kind": finding["kind"],
                "summary": finding["summary"],
                "evidence": finding.get("evidence", {}),
            })
    return items


def label_map(entries: list[dict]) -> dict[str, dict]:
    labels = {}
    for entry in entries:
        key = entry.get("key")
        if not isinstance(key, str) or not key or key in labels:
            raise EvaluationError("expectation keys must be unique non-empty strings")
        if not isinstance(entry.get("useful"), bool):
            raise EvaluationError(f"{key}: useful must be boolean")
        labels[key] = entry
    return labels


def score_labels(actual: set[str], labels: dict[str, dict],
           recall_expected: set[str]) -> dict:
    correct = set(labels)
    true_positive = sorted(actual & correct)
    false_positive = sorted(actual - correct)
    false_negative = sorted(recall_expected - actual)
    useful = sorted(key for key in actual if labels.get(key, {}).get("useful"))
    return {
        "actual": sorted(actual),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        # Only hits inside the *measured* expected set count toward recall;
        # a real-repository true positive where recall is not measured must
        # not inflate the fixture-only recall figure.
        "recall_true_positive": sorted(actual & recall_expected),
        "useful": useful,
    }


def lexical_score(evidence: EvidenceDocument, expectation: object) -> dict:
    if expectation is None:
        return {
            "configured": False,
            "checks": 0,
            "passed_checks": 0,
            "passed": None,
            "missing_tokens": [],
            "forbidden_tokens_present": [],
            "identifier_mismatches": [],
        }
    if not isinstance(expectation, dict):
        raise EvaluationError("lexical expectations must be an object")
    required = expectation.get("required_tokens", [])
    forbidden = expectation.get("forbidden_tokens", [])
    identifiers = expectation.get("required_identifiers", {})
    if (
        not isinstance(required, list)
        or not all(isinstance(token, str) for token in required)
        or len(set(required)) != len(required)
        or not isinstance(forbidden, list)
        or not all(isinstance(token, str) for token in forbidden)
        or len(set(forbidden)) != len(forbidden)
        or not isinstance(identifiers, dict)
        or not all(
            isinstance(name, str)
            and isinstance(tokens, list)
            and all(isinstance(token, str) for token in tokens)
            for name, tokens in identifiers.items()
        )
    ):
        raise EvaluationError("malformed lexical token/identifier expectations")

    actual_tokens = {
        item["term"] for item in evidence["vocabulary"]["tokens"]["items"]
    }
    actual_identifiers = {
        item["name"]: item["tokens"]
        for item in evidence["vocabulary"]["identifiers"]["items"]
    }
    missing = sorted(set(required) - actual_tokens)
    forbidden_present = sorted(set(forbidden) & actual_tokens)
    mismatches = [
        {
            "name": name,
            "expected": tokens,
            "actual": actual_identifiers.get(name),
        }
        for name, tokens in sorted(identifiers.items())
        if actual_identifiers.get(name) != tokens
    ]
    checks = len(required) + len(forbidden) + len(identifiers)
    failures = len(missing) + len(forbidden_present) + len(mismatches)
    return {
        "configured": True,
        "checks": checks,
        "passed_checks": checks - failures,
        "passed": failures == 0,
        "missing_tokens": missing,
        "forbidden_tokens_present": forbidden_present,
        "identifier_mismatches": mismatches,
    }


def register_score(evidence: EvidenceDocument, expectation: object) -> dict:
    if not isinstance(expectation, dict):
        raise EvaluationError("register expectations must be an object")
    expected_style = expectation.get("dominant_style")
    expected_multi_word = expectation.get("predominantly_multi_word")
    if expected_style not in STRUCTURED_IDENTIFIER_STYLES:
        raise EvaluationError(
            "register dominant_style must name a structurally styled form"
        )
    if not isinstance(expected_multi_word, bool):
        raise EvaluationError(
            "register predominantly_multi_word must be boolean"
        )

    register = evidence["terminology"]["register"]
    styles = register["identifier_styles_pct"]
    lengths = register["token_count_distribution_pct"]
    ranked_styles = sorted(
        styles.items(), key=lambda item: (-item[1], item[0])
    )
    dominant_style = ranked_styles[0][0] if ranked_styles else None
    multi_word_pct = (
        round(100.0 - lengths.get("1", 0.0), 1) if lengths else None
    )
    predominantly_multi_word = (
        multi_word_pct > 50.0 if multi_word_pct is not None else None
    )
    checks = [
        {
            "name": "dominant_style",
            "expected": expected_style,
            "actual": dominant_style,
            "passed": dominant_style == expected_style,
        },
        {
            "name": "predominantly_multi_word",
            "expected": expected_multi_word,
            "actual": predominantly_multi_word,
            "passed": predominantly_multi_word == expected_multi_word,
        },
    ]
    passed = sum(check["passed"] for check in checks)
    return {
        "configured": True,
        "expected": {
            "dominant_style": expected_style,
            "predominantly_multi_word": expected_multi_word,
        },
        "actual": {
            "dominant_style": dominant_style,
            "predominantly_multi_word": predominantly_multi_word,
            "multi_word_pct": multi_word_pct,
            "composition": register["composition"],
        },
        "checks": len(checks),
        "passed_checks": passed,
        "passed": passed == len(checks),
        "failures": [check for check in checks if not check["passed"]],
    }


def evaluate_self_register(expectation: object, evidence: EvidenceDocument) -> dict:
    return {
        "id": "glossabet",
        "source": {"kind": "local", "path": "."},
        **register_score(evidence, expectation),
    }


def nomination_score(evidence: EvidenceDocument, expectation: object) -> dict:
    if not isinstance(expectation, dict):
        raise EvaluationError("nomination expectations must be an object")
    required = expectation.get("required", [])
    forbidden = expectation.get("forbidden_terms", [])
    require_all_typed = expectation.get("require_all_typed")
    valid_kinds = {
        NOMINATION_CANONICAL_NAME,
        NOMINATION_DISAMBIGUATION,
    }
    if (
        not isinstance(required, list)
        or not all(
            isinstance(item, dict)
            and isinstance(item.get("term"), str)
            and item.get("nomination_kind") in valid_kinds
            for item in required
        )
        or len({item["term"] for item in required}) != len(required)
        or not isinstance(forbidden, list)
        or not all(isinstance(term, str) and term for term in forbidden)
        or len(set(forbidden)) != len(forbidden)
        or not isinstance(require_all_typed, bool)
    ):
        raise EvaluationError("malformed nomination expectations")

    candidates = {
        item["term"]: item
        for item in evidence["naming_candidates"]["terms"]
    }
    checks: list[dict] = []
    for expected in required:
        term = expected["term"]
        actual = candidates.get(term, {}).get("nomination_kind")
        checks.append({
            "name": f"required:{term}",
            "expected": expected["nomination_kind"],
            "actual": actual,
            "passed": actual == expected["nomination_kind"],
        })
    for term in forbidden:
        actual = term in candidates
        checks.append({
            "name": f"forbidden:{term}",
            "expected": False,
            "actual": actual,
            "passed": not actual,
        })
    if require_all_typed:
        untyped = sorted(
            term for term, item in candidates.items()
            if item.get("nomination_kind") not in valid_kinds
        )
        checks.append({
            "name": "all_candidates_typed",
            "expected": [],
            "actual": untyped,
            "passed": not untyped,
        })

    passed = sum(check["passed"] for check in checks)
    return {
        "id": "glossabet",
        "source": {"kind": "local", "path": "."},
        "configured": True,
        "expected": expectation,
        "actual": [
            {
                "term": term,
                "nomination_kind": item.get("nomination_kind"),
            }
            for term, item in sorted(candidates.items())
        ],
        "checks": len(checks),
        "passed_checks": passed,
        "passed": passed == len(checks),
        "failures": [check for check in checks if not check["passed"]],
    }


def evaluate_self_nominations(expectation: object, evidence: EvidenceDocument) -> dict:
    return nomination_score(evidence, expectation)


def structural_contract_score(
    evidence: dict,
    validation: dict,
    expectation: dict,
) -> dict:
    contracts = expectation.get("contracts", {})
    if not isinstance(contracts, dict):
        raise EvaluationError("structural contracts must be an object")
    checks: list[dict] = []

    def check(name: str, actual: object, expected: object) -> None:
        checks.append({
            "name": name,
            "actual": actual,
            "expected": expected,
            "passed": actual == expected,
        })

    groups = evidence["structural_groups"].get("groups", [])
    group_by_label = {
        group.get("label"): group
        for group in groups
        if isinstance(group, dict) and isinstance(group.get("label"), str)
    }
    group_contracts = contracts.get("groups", [])
    if (
        not isinstance(group_contracts, list)
        or not all(isinstance(item, dict) for item in group_contracts)
    ):
        raise EvaluationError("structural contract groups must be a list of objects")
    for expected_group in group_contracts:
        label = expected_group.get("label")
        if not isinstance(label, str) or not label:
            raise EvaluationError("each structural group contract needs a label")
        group = group_by_label.get(label)
        check(f"group:{label}:present", group is not None, True)
        if group is None:
            continue
        if "size" in expected_group:
            check(f"group:{label}:size", group.get("size"), expected_group["size"])
        if "provenance" in expected_group:
            check(
                f"group:{label}:provenance",
                group.get("provenance"),
                expected_group["provenance"],
            )
        required_tokens = expected_group.get("required_member_tokens", [])
        if not isinstance(required_tokens, list):
            raise EvaluationError("required_member_tokens must be a list")
        member_tokens = set(group.get("member_tokens", []))
        for token in required_tokens:
            check(
                f"group:{label}:member-token:{token}",
                token in member_tokens,
                True,
            )
        excluded_sample = expected_group.get("excluded_members_sample", [])
        if not isinstance(excluded_sample, list):
            raise EvaluationError("excluded_members_sample must be a list")
        members_sample = set(group.get("members_sample", []))
        required_sample = expected_group.get("required_members_sample", [])
        if not isinstance(required_sample, list):
            raise EvaluationError("required_members_sample must be a list")
        for member in required_sample:
            check(
                f"group:{label}:sample-includes:{member}",
                member in members_sample,
                True,
            )
        for member in excluded_sample:
            check(
                f"group:{label}:sample-excludes:{member}",
                member not in members_sample,
                True,
            )

    coverage_contract = contracts.get("group_coverage", {})
    if not isinstance(coverage_contract, dict):
        raise EvaluationError("structural group_coverage contract must be an object")
    group_coverage = evidence["structural_groups"].get(
        "coverage", {}
    ).get("groups", {})
    for name, expected in sorted(coverage_contract.items()):
        check(f"group-coverage:{name}", group_coverage.get(name), expected)

    if "validation_total_findings_complete" in contracts:
        check(
            "validation:total-findings-complete",
            validation.get("total_findings_complete", True),
            contracts["validation_total_findings_complete"],
        )
    partial_sections = contracts.get("partial_sections", [])
    if not isinstance(partial_sections, list):
        raise EvaluationError("structural partial_sections must be a list")
    for section in partial_sections:
        if section not in STRUCTURAL_SECTIONS:
            raise EvaluationError(f"unknown structural partial section: {section}")
        check(
            f"validation:{section}:complete",
            FindingsDocumentView(validation).section(section)["coverage"].get(
                "complete"
            ),
            False,
        )

    passed = sum(item["passed"] for item in checks)
    return {
        "checks": len(checks),
        "passed_checks": passed,
        "passed": passed == len(checks),
        "failures": [item for item in checks if not item["passed"]],
    }


def structural_score(
    evidence: dict,
    glossary: dict,
    expectation: object,
) -> tuple[dict, dict | None]:
    if expectation is None:
        return ({
            "configured": False,
            "recall_complete": False,
            "actual": [],
            "true_positive": [],
            "false_positive": [],
            "false_negative": [],
            "recall_true_positive": [],
            "useful": [],
            "contracts": {
                "checks": 0,
                "passed_checks": 0,
                "passed": None,
                "failures": [],
            },
        }, None)
    if not isinstance(expectation, dict):
        raise EvaluationError("structural expectations must be an object")
    recall_complete = expectation.get("recall_complete")
    if not isinstance(recall_complete, bool):
        raise EvaluationError("structural recall_complete must be boolean")
    labels = label_map(expectation.get("correct", []))
    validation = build_validation(evidence, glossary)
    actual = structural_keys(validation)
    score = score_labels(
        set(actual),
        labels,
        set(labels) if recall_complete else set(),
    )
    return ({
        "configured": True,
        "recall_complete": recall_complete,
        **score,
        "contracts": structural_contract_score(
            evidence, validation, expectation
        ),
        "coverage": {
            "groups": evidence["structural_groups"]["coverage"]["groups"],
            "validation_complete": validation.get("total_findings_complete", True),
        },
    }, validation)


def truncations(evidence: EvidenceDocument) -> list[dict]:
    events = []
    for name in ("tokens", "identifiers", "doc_terms"):
        marker = vocabulary_truncation(evidence, name)
        if marker:
            events.append({"surface": f"vocabulary.{name}", **marker})
    for name in (
        "synonym_candidates", "context_dispersion", "overload_candidates"
    ):
        dropped = evidence["terminology"][name]["dropped_items"]
        if dropped:
            events.append({"surface": f"terminology.{name}", "dropped_items": dropped})
    for name in ("edges_truncated", "external_truncated"):
        dropped = evidence["imports"][name]
        if dropped:
            events.append({"surface": f"imports.{name}", "dropped_items": dropped})
    budget = evidence["skipped"]["corpus_budget"]
    if budget and not budget.get("complete", True):
        events.append({"surface": "corpus_budget", **budget})
    structural = evidence["structural_groups"]
    group_coverage = structural.get("coverage", {}).get("groups")
    if group_coverage and not group_coverage.get("complete", True):
        events.append({
            "surface": "structural_groups.groups",
            **group_coverage,
        })
    return events


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None
