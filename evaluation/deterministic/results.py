"""Deterministic result assembly and offline verification.

``aggregate`` and ``thresholds`` turn per-source score blocks into the
release-facing summary. ``verify_results`` judges a recorded document:
genuineness (the default) proves it is internally consistent and that no
gated metric has been dropped, without consulting the current manifest,
engine, or corpora; currency (``current=True``, the release gate) rebuilds
the self-evidence and compares every identity and score to the current
tree, and may honestly report a retained result as stale.
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.deterministic.contract import (
    DEFAULT_MANIFEST,
    EVALUATION_SCHEMA_VERSION,
    PROJECT_ROOT,
    RELEASE_RUNTIME_RUNS,
    RELEASE_THRESHOLD_NAMES,
    EvaluationError,
)
from evaluation.deterministic.scoring import (
    evaluate_self_nominations,
    evaluate_self_register,
    ratio,
    register_score,
    structural_score,
)
from evaluation.deterministic.sources import (
    corpus_identity,
    engine_metadata,
    manifest_corpus_identity,
    read_manifest,
    source_metadata,
    source_root,
)
from evaluation.harness.io import is_sha256_hex
from glossabet.analysis.evidence import build_evidence
from glossabet.runtime.artifacts import MAX_JSON_BYTES


def aggregate(
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


def thresholds(aggregate: dict, thresholds: dict | None) -> dict:
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


ENGINE_METADATA_KEYS = {
    "name",
    "version",
    "source_sha256",
    "evidence_schema_version",
    "drift_schema_version",
    "validation_schema_version",
    "evaluation_schema_version",
}


def stored_threshold_targets(thresholds: object) -> dict | None:
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


SCORE_SET_KEYS = (
    "actual", "true_positive", "false_positive", "false_negative",
    "recall_true_positive", "useful",
)


def score_set_problems(block: dict) -> list[str]:
    """Why a recorded score block cannot have come from ``score_labels``: every
    list must be a sorted, duplicate-free list of strings; true and false
    positives partition ``actual``; recall hits and useful hits are subsets
    of the true positives; nothing is both found and missed."""
    sets: dict[str, list] = {}
    for key in SCORE_SET_KEYS:
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


def genuineness_errors(results: dict) -> list[str]:
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
        or set(engine) != ENGINE_METADATA_KEYS
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
                for problem in score_set_problems(block)
            )
    recorded_aggregate = results.get("aggregate")
    expected_aggregate = None
    try:
        if cases:
            expected_aggregate = aggregate(
                cases, self_register, self_nominations
            )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        errors.append("evaluation case metrics are malformed")
    if expected_aggregate is not None and recorded_aggregate != expected_aggregate:
        errors.append("evaluation aggregate is stale or internally inconsistent")

    recorded_thresholds = results.get("release_thresholds", {})
    stored_targets = stored_threshold_targets(recorded_thresholds)
    if stored_targets is None:
        errors.append("evaluation release metrics are malformed")
    elif set(stored_targets) != RELEASE_THRESHOLD_NAMES:
        errors.append(
            "evaluation release thresholds are missing required checks"
        )
    else:
        expected_thresholds = None
        try:
            if isinstance(recorded_aggregate, dict):
                expected_thresholds = thresholds(recorded_aggregate, stored_targets)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            errors.append("evaluation release metrics are malformed")
        if expected_thresholds is not None and recorded_thresholds != expected_thresholds:
            errors.append("evaluation release thresholds are stale")
    if (
        not isinstance(recorded_thresholds, dict)
        or recorded_thresholds.get("configured") is not True
    ):
        errors.append("evaluation release thresholds are not configured")
    return errors


def release_threshold_errors(results: dict) -> list[str]:
    """Release gate only: the recorded thresholds must all pass. Genuineness
    checks that they were *computed honestly*; whether they pass is a fact
    about the engine that may legitimately be false between releases (a
    recorded open finding), never at the moment something ships."""
    thresholds = results.get("release_thresholds", {})
    if not isinstance(thresholds, dict) or thresholds.get("passed") is not True:
        return ["evaluation release thresholds are not configured and passing"]
    return []


def currency_errors(results: dict, manifest_path: Path) -> list[str]:
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

    recorded_aggregate = results.get("aggregate")
    try:
        if isinstance(recorded_aggregate, dict) and results.get(
            "release_thresholds"
        ) != thresholds(recorded_aggregate, manifest.get("release_thresholds")):
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
    errors = genuineness_errors(results)
    if current:
        errors.extend(currency_errors(results, manifest_path))
        errors.extend(release_threshold_errors(results))
    return errors
