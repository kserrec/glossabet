#!/usr/bin/env python3
"""Reproduce Glossabet's pinned deterministic lexical evaluation.

External source is checked out only into a caller-provided directory or a
temporary directory. Nothing is imported or executed from a target project.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.deterministic.contract import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_RESULTS,
    EVALUATION_SCHEMA_VERSION,
    RELEASE_RUNTIME_RUNS,
    RELEASE_THRESHOLD_NAMES,
    EvaluationError,
)
from evaluation.deterministic.scoring import (  # noqa: E402
    drift_keys,
    evaluate_self_nominations,
    evaluate_self_register,
    label_map,
    lexical_score,
    ratio,
    register_score,
    review_items,
    score_labels,
    structural_score,
    terminology_keys,
    truncations,
)
from evaluation.deterministic.sources import (  # noqa: E402
    cache_at,
    check_license,
    corpus_identity,
    engine_metadata,
    manifest_corpus_identity,
    read_manifest,
    source_metadata,
    source_root,
    timed_build,
)
from evaluation.harness.io import (  # noqa: E402
    is_sha256_hex,
)
from glossabet.analysis.evidence import (  # noqa: E402
    build_evidence,
)
from glossabet.glossary.drift import (  # noqa: E402
    build_drift,
)
from glossabet.glossary.store import validate_glossary  # noqa: E402
from glossabet.runtime.artifacts import MAX_JSON_BYTES  # noqa: E402


def _evaluate_source(source: dict, root: Path, runs: int,
                     cache_root: Path) -> dict:
    errors = validate_glossary(source["glossary"])
    if errors:
        raise EvaluationError(f"{source['id']}: invalid glossary: {'; '.join(errors)}")
    check_license(source, root)
    structural_expectation = source["expectations"].get("structural")
    graphify = structural_expectation is not None

    cold_times = []
    cold_evidence = None
    for _ in range(runs):
        cold_evidence, elapsed, _ = timed_build(
            root, cache=False, graphify=graphify
        )
        cold_times.append(elapsed)
    assert cold_evidence is not None

    with cache_at(cache_root / source["id"]):
        timed_build(
            root, cache=True, graphify=graphify
        )  # populate outside the timed warm sample
        warm_times = []
        warm_stats = []
        warm_match = True
        cold_blob = json.dumps(cold_evidence, sort_keys=True)
        for _ in range(runs):
            warm, elapsed, stats = timed_build(
                root, cache=True, graphify=graphify
            )
            warm_times.append(elapsed)
            warm_stats.append(stats)
            warm_match = warm_match and json.dumps(warm, sort_keys=True) == cold_blob

    drift = build_drift(cold_evidence, source["glossary"])
    term_expect = source["expectations"]["terminology"]
    term_labels = label_map(term_expect["correct"])
    term_recall = set(term_labels) if term_expect["recall_complete"] else set()
    terminology_score = score_labels(
        terminology_keys(cold_evidence), term_labels, term_recall
    )

    drift_expect = source["expectations"]["drift"]
    drift_labels = label_map(drift_expect["correct"])
    actual_drift = drift_keys(drift)
    recall_kinds = set(drift_expect["recall_kinds"])
    drift_recall = {
        key for key in drift_labels
        if key.split(":", 1)[0] in recall_kinds
    }
    drift_score = score_labels(set(actual_drift), drift_labels, drift_recall)
    lexical = lexical_score(
        cold_evidence, source["expectations"].get("lexical")
    )
    register = register_score(
        cold_evidence, source["expectations"]["register"]
    )
    structural, validation = structural_score(
        cold_evidence,
        source["glossary"],
        structural_expectation,
    )

    totals = cold_evidence["totals"]
    corpus_budget = cold_evidence["skipped"]["corpus_budget"]
    source_files = totals["code_files"] + totals["doc_files"]
    warm_reused = sum(item["reused"] for item in warm_stats)
    warm_processed = warm_reused + sum(item["extracted"] for item in warm_stats)
    corpus = corpus_identity(root, cold_evidence, graphify=graphify)
    if corpus != manifest_corpus_identity(source):
        raise EvaluationError(
            f"{source['id']}: accepted corpus digest/count does not match manifest"
        )
    return {
        "id": source["id"],
        "source": source_metadata(source),
        "corpus": corpus,
        "files": {
            "source": source_files,
            "production_code": cold_evidence["terminology"]["scope"]["code_files"],
            "production_docs": cold_evidence["terminology"]["scope"]["doc_files"],
        },
        "bytes": {
            "code": totals["code_bytes"],
            "source_budgeted": totals.get("source_bytes"),
        },
        "corpus_budget": corpus_budget,
        "runtime_seconds": {
            "cold_samples": [round(value, 6) for value in cold_times],
            "cold_median": round(statistics.median(cold_times), 6),
            "warm_samples": [round(value, 6) for value in warm_times],
            "warm_median": round(statistics.median(warm_times), 6),
        },
        "cache": {
            "warm_output_matches_cold": warm_match,
            "reuse_rate": ratio(warm_reused, warm_processed),
        },
        "truncations": truncations(cold_evidence),
        "lexical": lexical,
        "register": register,
        "terminology": terminology_score,
        "drift": drift_score,
        "structural": structural,
        "review_items": review_items(
            source["id"], cold_evidence, drift, validation
        ),
    }


def _aggregate(
    cases: list[dict],
    self_register: dict,
    self_nominations: dict,
) -> dict:
    def combine(surface: str, key: str) -> int:
        return sum(len(case[surface][key]) for case in cases)

    term_actual = combine("terminology", "actual")
    term_true = combine("terminology", "true_positive")
    term_false = combine("terminology", "false_positive")
    term_recall_true = combine("terminology", "recall_true_positive")
    term_missed = combine("terminology", "false_negative")
    drift_actual = combine("drift", "actual")
    drift_true = combine("drift", "true_positive")
    drift_false = combine("drift", "false_positive")
    drift_recall_true = combine("drift", "recall_true_positive")
    drift_missed = combine("drift", "false_negative")
    structural_actual = combine("structural", "actual")
    structural_true = combine("structural", "true_positive")
    structural_false = combine("structural", "false_positive")
    structural_recall_true = combine("structural", "recall_true_positive")
    structural_missed = combine("structural", "false_negative")
    total_actual = term_actual + drift_actual + structural_actual
    total_true = term_true + drift_true + structural_true
    total_false = term_false + drift_false + structural_false
    total_useful = (
        combine("terminology", "useful")
        + combine("drift", "useful")
        + combine("structural", "useful")
    )
    lexical_checks = sum(case["lexical"]["checks"] for case in cases)
    lexical_passed = sum(case["lexical"]["passed_checks"] for case in cases)
    register_checks = (
        sum(case["register"]["checks"] for case in cases)
        + self_register["checks"]
    )
    register_passed = (
        sum(case["register"]["passed_checks"] for case in cases)
        + self_register["passed_checks"]
    )
    nomination_checks = self_nominations["checks"]
    nomination_passed = self_nominations["passed_checks"]
    structural_contract_checks = sum(
        case["structural"]["contracts"]["checks"] for case in cases
    )
    structural_contract_passed = sum(
        case["structural"]["contracts"]["passed_checks"] for case in cases
    )
    production_files = sum(case["files"]["production_code"] for case in cases)
    source_files = sum(case["files"]["source"] for case in cases)
    source_bytes = sum(case["bytes"]["source_budgeted"] for case in cases)
    walk_entries = sum(
        case["corpus_budget"]["used"]["walk_entries"] for case in cases
    )
    cold_seconds = sum(case["runtime_seconds"]["cold_median"] for case in cases)
    warm_seconds = sum(case["runtime_seconds"]["warm_median"] for case in cases)
    budget_truncations = sum(
        event["surface"] == "corpus_budget"
        for case in cases for event in case["truncations"]
    )
    known_reuse = [
        case["cache"]["reuse_rate"]
        for case in cases
        if case["cache"]["reuse_rate"] is not None
    ]
    return {
        "cases": len(cases),
        "source_files": source_files,
        "source_bytes": source_bytes,
        "walk_entries": walk_entries,
        "limits_per_repository": cases[0]["corpus_budget"]["limits"],
        "production_code_files": production_files,
        "quality": {
            "terminology_precision": ratio(term_true, term_actual),
            "terminology_recall_where_complete": ratio(
                term_recall_true, term_recall_true + term_missed
            ),
            "drift_precision": ratio(drift_true, drift_actual),
            "drift_recall_where_complete": ratio(
                drift_recall_true, drift_recall_true + drift_missed
            ),
            "structural_precision": ratio(
                structural_true, structural_actual
            ),
            "structural_recall_where_complete": ratio(
                structural_recall_true, structural_recall_true + structural_missed
            ),
            "overall_precision": ratio(total_true, total_actual),
            "reviewer_usefulness": ratio(total_useful, total_actual),
            "lexical_contract_rate": ratio(lexical_passed, lexical_checks),
            "register_accuracy": ratio(register_passed, register_checks),
            "nomination_quality": ratio(
                nomination_passed, nomination_checks
            ),
            "structural_contract_rate": ratio(
                structural_contract_passed, structural_contract_checks
            ),
            "false_alarms": total_false,
            "false_alarms_per_1000_production_code_files": (
                round(total_false * 1000 / production_files, 2)
                if production_files else None
            ),
        },
        "runtime": {
            "cold_median_seconds_total": round(cold_seconds, 6),
            "warm_median_seconds_total": round(warm_seconds, 6),
            "cold_seconds_per_1000_source_files": (
                round(cold_seconds * 1000 / source_files, 3)
                if source_files else None
            ),
            "warm_seconds_per_1000_source_files": (
                round(warm_seconds * 1000 / source_files, 3)
                if source_files else None
            ),
        },
        "cache": {
            "all_warm_outputs_match_cold": all(
                case["cache"]["warm_output_matches_cold"] for case in cases
            ),
            # An empty corpus has no measurable reuse rate (None); it must
            # not crash the aggregate or masquerade as a measured minimum.
            "minimum_reuse_rate": (
                min(known_reuse) if known_reuse else None
            ),
        },
        "truncation": {
            "cases_with_any_truncation": sum(bool(case["truncations"]) for case in cases),
            "corpus_budget_truncations": budget_truncations,
        },
    }


def _thresholds(aggregate: dict, thresholds: dict | None) -> dict:
    if not thresholds:
        return {"configured": False, "passed": None, "checks": []}
    metrics = {
        "terminology_precision_min": aggregate["quality"]["terminology_precision"],
        "drift_precision_min": aggregate["quality"]["drift_precision"],
        "drift_recall_min": aggregate["quality"]["drift_recall_where_complete"],
        "structural_precision_min": aggregate["quality"]["structural_precision"],
        "structural_recall_min": aggregate["quality"][
            "structural_recall_where_complete"
        ],
        "reviewer_usefulness_min": aggregate["quality"]["reviewer_usefulness"],
        "false_alarms_per_1000_max": aggregate["quality"][
            "false_alarms_per_1000_production_code_files"
        ],
        "cold_seconds_per_1000_source_files_max": aggregate["runtime"][
            "cold_seconds_per_1000_source_files"
        ],
        "corpus_budget_truncations_max": aggregate["truncation"][
            "corpus_budget_truncations"
        ],
        "minimum_cache_reuse_min": aggregate["cache"]["minimum_reuse_rate"],
        "lexical_contract_min": aggregate["quality"]["lexical_contract_rate"],
        "register_accuracy_min": aggregate["quality"]["register_accuracy"],
        "nomination_quality_min": aggregate["quality"][
            "nomination_quality"
        ],
        "structural_contract_min": aggregate["quality"][
            "structural_contract_rate"
        ],
    }
    checks = []
    for name, target in thresholds.items():
        actual = metrics.get(name)
        if actual is None:
            passed = False
        elif name.endswith("_min"):
            passed = actual >= target
        else:
            passed = actual <= target
        checks.append({
            "name": name,
            "actual": actual,
            "target": target,
            "passed": passed,
        })
    checks.append({
        "name": "warm_outputs_match_cold",
        "actual": aggregate["cache"]["all_warm_outputs_match_cold"],
        "target": True,
        "passed": aggregate["cache"]["all_warm_outputs_match_cold"],
    })
    return {
        "configured": True,
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }


_ENGINE_METADATA_KEYS = {
    "name",
    "version",
    "source_sha256",
    "evidence_schema_version",
    "drift_schema_version",
    "validation_schema_version",
    "evaluation_schema_version",
}


def _stored_threshold_targets(thresholds: object) -> dict | None:
    """Recover the threshold configuration recorded inside the results."""
    if not isinstance(thresholds, dict):
        return None
    checks = thresholds.get("checks")
    if not isinstance(checks, list) or not checks:
        return None
    targets: dict = {}
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("name"), str):
            return None
        name = check["name"]
        if name == "warm_outputs_match_cold":
            continue
        if name in targets or "target" not in check:
            return None
        targets[name] = check["target"]
    return targets


_SCORE_SET_KEYS = (
    "actual", "true_positive", "false_positive", "false_negative",
    "recall_true_positive", "useful",
)


def _score_set_problems(block: dict) -> list[str]:
    """Why a recorded score block cannot have come from ``score_labels``: every
    list must be a sorted, duplicate-free list of strings; true and false
    positives partition ``actual``; recall hits and useful hits are subsets
    of the true positives; nothing is both found and missed."""
    sets: dict[str, list] = {}
    for key in _SCORE_SET_KEYS:
        value = block.get(key)
        if (
            not isinstance(value, list)
            or not all(isinstance(item, str) for item in value)
            or value != sorted(set(value))
        ):
            return [f"{key} is not a sorted list of unique strings"]
        sets[key] = value
    actual = set(sets["actual"])
    true_positive = set(sets["true_positive"])
    false_positive = set(sets["false_positive"])
    problems = []
    if true_positive | false_positive != actual or true_positive & false_positive:
        problems.append("true and false positives do not partition actual")
    if not set(sets["recall_true_positive"]) <= true_positive:
        problems.append("recall true positives are not a subset of true positives")
    if not set(sets["useful"]) <= true_positive:
        problems.append("useful hits are not a subset of true positives")
    if set(sets["false_negative"]) & actual:
        problems.append("a false negative is also recorded as found")
    return problems


def _genuineness_errors(results: dict) -> list[str]:
    """Check the results artifact standalone: untampered, internally consistent."""
    errors: list[str] = []
    if results.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        errors.append(
            "evaluation schema does not match the current evaluator "
            f"({results.get('schema_version')!r} != {EVALUATION_SCHEMA_VERSION})"
        )
    engine = results.get("engine")
    if (
        not isinstance(engine, dict)
        or set(engine) != _ENGINE_METADATA_KEYS
        or engine.get("name") != "glossabet"
        or not isinstance(engine.get("version"), str)
        or not engine.get("version")
        or not is_sha256_hex(engine.get("source_sha256"))
    ):
        errors.append("engine identity metadata is malformed")
    if not is_sha256_hex(results.get("manifest_sha256")):
        errors.append("evaluation manifest digest is malformed")

    cases = results.get("cases")
    if not isinstance(cases, list):
        errors.append("evaluation cases are missing or malformed")
        cases = []
    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if (
        not cases
        or len(ids) != len(cases)
        or not all(isinstance(case_id, str) for case_id in ids)
        or len(set(ids)) != len(ids)
    ):
        errors.append("evaluation case ids are missing or duplicated")
    for case in cases:
        if not isinstance(case, dict):
            continue
        corpus = case.get("corpus")
        if (
            not isinstance(corpus, dict)
            or not is_sha256_hex(corpus.get("sha256"))
            or not isinstance(corpus.get("files_hashed"), int)
            or isinstance(corpus.get("files_hashed"), bool)
            or corpus["files_hashed"] < 0
        ):
            errors.append(
                f"{case.get('id', '<unknown>')}: corpus digest metadata is malformed"
            )

    method = results.get("method")
    method = method if isinstance(method, dict) else {}
    if method.get("runtime_runs_per_case") != RELEASE_RUNTIME_RUNS:
        errors.append(
            "evaluation results do not contain the required five-run sample"
        )
    graphify_cases = method.get("graphify_cases")
    if (
        not isinstance(graphify_cases, int)
        or isinstance(graphify_cases, bool)
        or not 0 <= graphify_cases <= len(cases)
    ):
        errors.append("evaluation Graphify case count is malformed")
    if (
        method.get("graphify") != "per-case"
        or method.get("external_source_vendored") is not False
    ):
        errors.append("evaluation source method is weakened or stale")

    self_register = results.get("self_register")
    self_nominations = results.get("self_nominations")
    # Each check block derives ``passed_checks``/``passed`` from its own
    # ``failures``; a block claiming more passes than its failure list
    # allows is a contradiction the aggregate would otherwise trust.
    blocks = [("self_register", self_register), ("self_nominations", self_nominations)]
    for case in cases:
        if isinstance(case, dict):
            case_id = case.get("id", "<unknown>")
            blocks.append((f"{case_id}.register", case.get("register")))
            structural = case.get("structural")
            if isinstance(structural, dict):
                blocks.append((f"{case_id}.structural.contracts", structural.get("contracts")))
    for name, block in blocks:
        if not isinstance(block, dict) or "failures" not in block:
            continue
        failures = block.get("failures")
        checks = block.get("checks")
        passed_checks = block.get("passed_checks")
        if (
            not isinstance(failures, list)
            or not isinstance(checks, int) or isinstance(checks, bool)
            or passed_checks != checks - len(failures)
            or (block.get("passed") is not None and block["passed"] is not (
                passed_checks == checks
            ))
        ):
            errors.append(f"{name}: passed counts disagree with recorded failures")
    # Every score block is a partition of ``actual`` plus subsets of it; a
    # phantom recall hit or a hit listed as both true and false positive
    # would otherwise flow into a recomputed aggregate that "matches".
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = case.get("id", "<unknown>")
        for section in ("terminology", "drift", "structural"):
            block = case.get(section)
            if not isinstance(block, dict) or "actual" not in block:
                continue
            errors.extend(
                f"{case_id}.{section}: {problem}"
                for problem in _score_set_problems(block)
            )
    aggregate = results.get("aggregate")
    expected_aggregate = None
    try:
        if cases:
            expected_aggregate = _aggregate(
                cases, self_register, self_nominations
            )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        errors.append("evaluation case metrics are malformed")
    if expected_aggregate is not None and aggregate != expected_aggregate:
        errors.append("evaluation aggregate is stale or internally inconsistent")

    thresholds = results.get("release_thresholds", {})
    stored_targets = _stored_threshold_targets(thresholds)
    if stored_targets is None:
        errors.append("evaluation release metrics are malformed")
    elif set(stored_targets) != RELEASE_THRESHOLD_NAMES:
        errors.append(
            "evaluation release thresholds are missing required checks"
        )
    else:
        expected_thresholds = None
        try:
            if isinstance(aggregate, dict):
                expected_thresholds = _thresholds(aggregate, stored_targets)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            errors.append("evaluation release metrics are malformed")
        if expected_thresholds is not None and thresholds != expected_thresholds:
            errors.append("evaluation release thresholds are stale")
    if not isinstance(thresholds, dict) or thresholds.get("configured") is not True:
        errors.append("evaluation release thresholds are not configured")
    return errors


def _release_threshold_errors(results: dict) -> list[str]:
    """Release gate only: the recorded thresholds must all pass. Genuineness
    checks that they were *computed honestly*; whether they pass is a fact
    about the engine that may legitimately be false between releases (a
    recorded open finding), never at the moment something ships."""
    thresholds = results.get("release_thresholds", {})
    if not isinstance(thresholds, dict) or thresholds.get("passed") is not True:
        return ["evaluation release thresholds are not configured and passing"]
    return []


def _currency_errors(results: dict, manifest_path: Path) -> list[str]:
    """Check that the evidence additionally describes the current tree."""
    manifest, manifest_sha256 = read_manifest(manifest_path)
    errors: list[str] = []
    if results.get("engine") != engine_metadata():
        errors.append("engine version, schema, or source digest is stale")
    if results.get("manifest_sha256") != manifest_sha256:
        errors.append("evaluation manifest digest is stale")

    cases = results.get("cases")
    if not isinstance(cases, list):
        cases = []
    case_by_id = {
        case.get("id"): case
        for case in cases
        if isinstance(case, dict) and isinstance(case.get("id"), str)
    }
    result_ids = [
        case.get("id") for case in cases if isinstance(case, dict)
    ]
    expected_ids = [source["id"] for source in manifest["sources"]]
    if result_ids != expected_ids or len(case_by_id) != len(cases):
        errors.append("evaluation case ids/order do not match the manifest")

    for source in manifest["sources"]:
        case = case_by_id.get(source["id"])
        if case is None:
            continue
        if case.get("source") != source_metadata(source):
            errors.append(f"{source['id']}: source metadata is stale")
        corpus = case.get("corpus")
        if (
            not isinstance(corpus, dict)
            or not is_sha256_hex(corpus.get("sha256"))
            or not isinstance(corpus.get("files_hashed"), int)
            or corpus["files_hashed"] < 0
        ):
            continue
        if corpus != manifest_corpus_identity(source):
            errors.append(f"{source['id']}: corpus digest does not match manifest")
        if source.get("kind") == "local":
            root = source_root(source, None, False)
            graphify = source.get("expectations", {}).get("structural") is not None
            current_evidence = build_evidence(
                root, cache=False, graphify=graphify
            )
            current = corpus_identity(
                root,
                current_evidence,
                graphify=graphify,
            )
            if corpus != current:
                errors.append(f"{source['id']}: local corpus digest is stale")
            expected_structural, _ = structural_score(
                current_evidence,
                source["glossary"],
                source.get("expectations", {}).get("structural"),
            )
            if case.get("structural") != expected_structural:
                errors.append(
                    f"{source['id']}: local structural evidence is stale"
                )
            expected_register = register_score(
                current_evidence,
                source["expectations"]["register"],
            )
            if case.get("register") != expected_register:
                errors.append(
                    f"{source['id']}: local register evidence is stale"
                )

    self_evidence = build_evidence(
        PROJECT_ROOT, cache=False, graphify=False
    )
    if results.get("self_register") != evaluate_self_register(
        manifest["self_register"], self_evidence
    ):
        errors.append("self register evidence is stale")
    if results.get("self_nominations") != evaluate_self_nominations(
        manifest["self_nominations"], self_evidence
    ):
        errors.append("self nomination evidence is stale")

    expected_graphify_cases = sum(
        source.get("expectations", {}).get("structural") is not None
        for source in manifest["sources"]
    )
    method = results.get("method")
    method = method if isinstance(method, dict) else {}
    if method.get("graphify_cases") != expected_graphify_cases:
        errors.append("evaluation Graphify case count is stale")

    aggregate = results.get("aggregate")
    try:
        if isinstance(aggregate, dict) and results.get(
            "release_thresholds"
        ) != _thresholds(aggregate, manifest.get("release_thresholds")):
            errors.append("evaluation release thresholds are stale")
    except (KeyError, TypeError, ValueError, ArithmeticError):
        errors.append("evaluation release metrics are malformed")
    return errors


def verify_results(
    results_path: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    current: bool = False,
) -> list[str]:
    """Check committed evaluation evidence.

    Always checks genuineness: the artifact is untampered and internally
    consistent, so it truthfully reports the run it records. With
    ``current=True`` (the release gate) it additionally checks currency:
    the evidence describes the current engine source, manifest, and local
    corpora, not an earlier state of the repository.
    """
    try:
        if results_path.stat().st_size > MAX_JSON_BYTES:
            raise EvaluationError(
                f"{results_path}: results exceed {MAX_JSON_BYTES} bytes — "
                "refusing to load"
            )
        results = json.loads(results_path.read_bytes())
    except (OSError, ValueError, RecursionError) as exc:
        raise EvaluationError(
            f"{results_path}: unreadable evaluation results ({exc})"
        ) from exc
    if not isinstance(results, dict):
        raise EvaluationError(f"{results_path}: results must be a JSON object")
    errors = _genuineness_errors(results)
    if current:
        errors.extend(_currency_errors(results, manifest_path))
        errors.extend(_release_threshold_errors(results))
    return errors


def run(manifest_path: Path, output_path: Path, repositories_root: Path | None,
        fetch: bool, runs: int, selected: set[str]) -> dict:
    manifest, manifest_sha256 = read_manifest(manifest_path)
    sources = [
        source for source in manifest["sources"]
        if not selected or source["id"] in selected
    ]
    if selected - {source["id"] for source in sources}:
        missing = ", ".join(sorted(selected - {source["id"] for source in sources}))
        raise EvaluationError(f"unknown case(s): {missing}")
    if not sources:
        raise EvaluationError("no evaluation cases selected")

    cache_root = Path(tempfile.mkdtemp(prefix="glossabet-eval-cache-"))
    try:
        cases = [
            _evaluate_source(
                source,
                source_root(source, repositories_root, fetch),
                runs,
                cache_root,
            )
            for source in sources
        ]
    finally:
        import shutil
        shutil.rmtree(cache_root, ignore_errors=True)

    self_evidence = build_evidence(
        PROJECT_ROOT, cache=False, graphify=False
    )
    self_register = evaluate_self_register(
        manifest["self_register"], self_evidence
    )
    self_nominations = evaluate_self_nominations(
        manifest["self_nominations"], self_evidence
    )
    aggregate = _aggregate(cases, self_register, self_nominations)
    thresholds = _thresholds(
        aggregate,
        manifest.get("release_thresholds") if not selected else None,
    )
    result = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "engine": engine_metadata(),
        "manifest_sha256": manifest_sha256,
        "environment": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "method": {
            "runtime_runs_per_case": runs,
            "graphify": "per-case",
            "graphify_cases": sum(
                source.get("expectations", {}).get("structural") is not None
                for source in sources
            ),
            "external_source_vendored": False,
        },
        "cases": cases,
        "self_register": self_register,
        "self_nominations": self_nominations,
        "aggregate": aggregate,
        "release_thresholds": thresholds,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--fetch", action="store_true")
    source.add_argument("--repositories-root", type=Path)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--verify-results",
        type=Path,
        help="verify committed results are genuine and internally consistent",
    )
    parser.add_argument(
        "--current",
        action="store_true",
        help=(
            "with --verify-results, additionally require the evidence to "
            "describe the current engine source, manifest, and corpora "
            "(the release gate)"
        ),
    )
    args = parser.parse_args(argv)
    if args.current and args.verify_results is None:
        parser.error("--current requires --verify-results")
    if args.case and args.check:
        parser.error(
            "--check gates release thresholds, which a partial --case run "
            "never computes; drop --case or --check"
        )
    if args.case and args.output.resolve() == DEFAULT_RESULTS.resolve():
        parser.error(
            "--case writes a partial document; pass an explicit --output "
            "so the committed release evidence is not overwritten"
        )
    if args.verify_results is not None:
        try:
            errors = verify_results(
                args.verify_results, args.manifest, current=args.current
            )
        except (EvaluationError, OSError, subprocess.TimeoutExpired) as exc:
            print(f"evaluation verification: {exc}", file=sys.stderr)
            return 1
        if errors:
            for error in errors:
                print(f"evaluation verification: {error}", file=sys.stderr)
            return 1
        if args.current:
            print("evaluation results match the current engine and corpus")
        else:
            print("evaluation results are genuine and internally consistent")
        return 0
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    try:
        if args.fetch:
            with tempfile.TemporaryDirectory(prefix="glossabet-eval-repos-") as raw:
                result = run(
                    args.manifest,
                    args.output,
                    Path(raw),
                    True,
                    args.runs,
                    set(args.case),
                )
        else:
            result = run(
                args.manifest,
                args.output,
                args.repositories_root,
                False,
                args.runs,
                set(args.case),
            )
    except (EvaluationError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"evaluation: {exc}", file=sys.stderr)
        return 1

    aggregate = result["aggregate"]
    print(
        f"evaluated {aggregate['cases']} case(s), "
        f"{aggregate['source_files']} source file(s): "
        f"precision {aggregate['quality']['overall_precision']}, "
        f"false alarms {aggregate['quality']['false_alarms']}"
    )
    thresholds = result["release_thresholds"]
    if thresholds["configured"]:
        print("release thresholds: " + ("pass" if thresholds["passed"] else "FAIL"))
    return 1 if args.check and thresholds.get("passed") is not True else 0


if __name__ == "__main__":
    raise SystemExit(main())
