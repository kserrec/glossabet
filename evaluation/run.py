#!/usr/bin/env python3
"""Reproduce Glossarize's pinned Phase 15/16 evaluation.

External source is checked out only into a caller-provided directory or a
temporary directory. Nothing is imported or executed from a target project.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from glossarize import __version__  # noqa: E402
from glossarize.cache import CACHE_ROOT_ENV  # noqa: E402
from glossarize.drift import build_drift  # noqa: E402
from glossarize.evidence import build_evidence  # noqa: E402
from glossarize.glossary import validate_glossary  # noqa: E402

EVALUATION_SCHEMA_VERSION = 2
DEFAULT_MANIFEST = PROJECT_ROOT / "evaluation" / "corpus.json"
DEFAULT_RESULTS = PROJECT_ROOT / "evaluation" / "results.json"
GIT_SAFE_CONFIG = ("-c", "core.fsmonitor=", "-c", "core.hooksPath=/dev/null")
DRIFT_SECTIONS = (
    "parallel_terms",
    "watched_terms_in_use",
    "canonical_fading",
    "canonical_overloaded",
)


class EvaluationError(ValueError):
    """The corpus, checkout, or labels cannot support a valid evaluation."""


def _read_manifest(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise EvaluationError(f"{path}: unreadable JSON ({exc})") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise EvaluationError(f"{path}: unsupported evaluation manifest")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise EvaluationError(f"{path}: sources must be a non-empty list")
    return manifest, hashlib.sha256(raw).hexdigest()


def _git(args: list[str], cwd: Path, timeout: int = 120) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }
    proc = subprocess.run(
        ["git", *GIT_SAFE_CONFIG, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if proc.returncode:
        detail = proc.stderr.strip() or proc.stdout.strip() or "git failed"
        raise EvaluationError(detail)
    return proc.stdout.strip()


def _fetch(source: dict, repositories_root: Path) -> Path:
    destination = repositories_root / source["checkout_dir"]
    if destination.exists():
        raise EvaluationError(f"refusing to replace existing {destination}")
    destination.mkdir(parents=True)
    _git(["init", "-q"], destination)
    _git(["remote", "add", "origin", source["url"]], destination)
    _git(["fetch", "--depth", "1", "origin", source["commit"]], destination)
    _git(["checkout", "--detach", "--force", "FETCH_HEAD"], destination)
    return destination


def _source_root(source: dict, repositories_root: Path | None,
                 fetch: bool) -> Path:
    if source.get("kind") == "local":
        return (PROJECT_ROOT / source["path"]).resolve()
    if repositories_root is None:
        raise EvaluationError("external sources require --fetch or --repositories-root")
    root = (
        _fetch(source, repositories_root)
        if fetch else repositories_root / source["checkout_dir"]
    ).resolve()
    if not root.is_dir():
        raise EvaluationError(f"missing checkout for {source['id']}: {root}")
    actual = _git(["rev-parse", "HEAD"], root)
    if actual != source["commit"]:
        raise EvaluationError(
            f"{source['id']}: expected {source['commit']}, found {actual}"
        )
    return root


def _check_license(source: dict, root: Path) -> None:
    base = PROJECT_ROOT if source.get("license_base") == "project" else root
    license_path = (base / source["license_path"]).resolve()
    try:
        license_path.relative_to(base.resolve())
    except ValueError as exc:
        raise EvaluationError(f"{source['id']}: license path escapes its base") from exc
    if not license_path.is_file():
        raise EvaluationError(f"{source['id']}: missing declared license file")


@contextmanager
def _cache_at(path: Path):
    previous = os.environ.get(CACHE_ROOT_ENV)
    os.environ[CACHE_ROOT_ENV] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(CACHE_ROOT_ENV, None)
        else:
            os.environ[CACHE_ROOT_ENV] = previous


def _timed_build(root: Path, *, cache: bool) -> tuple[dict, float, dict]:
    stats: dict = {}
    started = time.perf_counter()
    evidence = build_evidence(
        root,
        cache=cache,
        stats=stats,
        graphify=False,
    )
    elapsed = time.perf_counter() - started
    return evidence, elapsed, stats


def _terminology_keys(evidence: dict) -> set[str]:
    terminology = evidence["terminology"]
    keys = {
        "synonym:" + ":".join(sorted((item["a"], item["b"])))
        for item in terminology["synonym_candidates"]["items"]
    }
    keys.update(
        f"overload:{item['term']}"
        for item in terminology["overload_candidates"]["items"]
    )
    return keys


def _drift_key(section: str, finding: dict) -> tuple[str, str]:
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


def _drift_keys(drift: dict) -> dict[str, str]:
    return {
        key: kind
        for section in DRIFT_SECTIONS
        for finding in drift[section]["items"]
        for kind, key in [_drift_key(section, finding)]
    }


def _label_map(entries: list[dict]) -> dict[str, dict]:
    labels = {}
    for entry in entries:
        key = entry.get("key")
        if not isinstance(key, str) or not key or key in labels:
            raise EvaluationError("expectation keys must be unique non-empty strings")
        if not isinstance(entry.get("useful"), bool):
            raise EvaluationError(f"{key}: useful must be boolean")
        labels[key] = entry
    return labels


def _score(actual: set[str], labels: dict[str, dict],
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
        "useful": useful,
    }


def _lexical_score(evidence: dict, expectation: object) -> dict:
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
        or not isinstance(forbidden, list)
        or not all(isinstance(token, str) for token in forbidden)
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


def _truncations(evidence: dict) -> list[dict]:
    events = []
    for name in ("tokens", "identifiers", "doc_terms"):
        marker = evidence["vocabulary"][name]["truncated"]
        if marker:
            events.append({"surface": f"vocabulary.{name}", **marker})
    for name in ("synonym_candidates", "overload_candidates"):
        dropped = evidence["terminology"][name]["dropped_items"]
        if dropped:
            events.append({"surface": f"terminology.{name}", "dropped_items": dropped})
    for name in ("edges_truncated", "external_truncated"):
        dropped = evidence["imports"][name]
        if dropped:
            events.append({"surface": f"imports.{name}", "dropped_items": dropped})
    budget = evidence.get("skipped", {}).get("corpus_budget")
    if budget and not budget.get("complete", True):
        events.append({"surface": "corpus_budget", **budget})
    return events


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _evaluate_source(source: dict, root: Path, runs: int,
                     cache_root: Path) -> dict:
    errors = validate_glossary(source["glossary"])
    if errors:
        raise EvaluationError(f"{source['id']}: invalid glossary: {'; '.join(errors)}")
    _check_license(source, root)

    cold_times = []
    cold_evidence = None
    for _ in range(runs):
        cold_evidence, elapsed, _ = _timed_build(root, cache=False)
        cold_times.append(elapsed)
    assert cold_evidence is not None

    with _cache_at(cache_root / source["id"]):
        _timed_build(root, cache=True)  # populate outside the timed warm sample
        warm_times = []
        warm_stats = []
        warm_match = True
        cold_blob = json.dumps(cold_evidence, sort_keys=True)
        for _ in range(runs):
            warm, elapsed, stats = _timed_build(root, cache=True)
            warm_times.append(elapsed)
            warm_stats.append(stats)
            warm_match = warm_match and json.dumps(warm, sort_keys=True) == cold_blob

    drift = build_drift(cold_evidence, source["glossary"])
    term_expect = source["expectations"]["terminology"]
    term_labels = _label_map(term_expect["correct"])
    term_recall = set(term_labels) if term_expect["recall_complete"] else set()
    terminology_score = _score(
        _terminology_keys(cold_evidence), term_labels, term_recall
    )

    drift_expect = source["expectations"]["drift"]
    drift_labels = _label_map(drift_expect["correct"])
    actual_drift = _drift_keys(drift)
    recall_kinds = set(drift_expect["recall_kinds"])
    drift_recall = {
        key for key in drift_labels
        if key.split(":", 1)[0] in recall_kinds
    }
    drift_score = _score(set(actual_drift), drift_labels, drift_recall)
    lexical_score = _lexical_score(
        cold_evidence, source["expectations"].get("lexical")
    )

    totals = cold_evidence["totals"]
    corpus_budget = cold_evidence["skipped"]["corpus_budget"]
    source_files = totals["code_files"] + totals["doc_files"]
    warm_reused = sum(item["reused"] for item in warm_stats)
    warm_processed = warm_reused + sum(item["extracted"] for item in warm_stats)
    return {
        "id": source["id"],
        "source": {
            key: source[key]
            for key in (
                "kind", "url", "commit", "primary_language", "license_spdx",
                "license_url", "provenance",
            )
            if key in source
        },
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
            "reuse_rate": _ratio(warm_reused, warm_processed),
        },
        "truncations": _truncations(cold_evidence),
        "lexical": lexical_score,
        "terminology": terminology_score,
        "drift": drift_score,
    }


def _aggregate(cases: list[dict]) -> dict:
    def combine(surface: str, key: str) -> int:
        return sum(len(case[surface][key]) for case in cases)

    term_actual = combine("terminology", "actual")
    term_true = combine("terminology", "true_positive")
    term_false = combine("terminology", "false_positive")
    term_missed = combine("terminology", "false_negative")
    drift_actual = combine("drift", "actual")
    drift_true = combine("drift", "true_positive")
    drift_false = combine("drift", "false_positive")
    drift_missed = combine("drift", "false_negative")
    total_actual = term_actual + drift_actual
    total_true = term_true + drift_true
    total_false = term_false + drift_false
    total_useful = combine("terminology", "useful") + combine("drift", "useful")
    lexical_checks = sum(case["lexical"]["checks"] for case in cases)
    lexical_passed = sum(case["lexical"]["passed_checks"] for case in cases)
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
    return {
        "cases": len(cases),
        "source_files": source_files,
        "source_bytes": source_bytes,
        "walk_entries": walk_entries,
        "limits_per_repository": cases[0]["corpus_budget"]["limits"],
        "production_code_files": production_files,
        "quality": {
            "terminology_precision": _ratio(term_true, term_actual),
            "terminology_recall_where_complete": _ratio(
                term_true, term_true + term_missed
            ),
            "drift_precision": _ratio(drift_true, drift_actual),
            "drift_recall_where_complete": _ratio(
                drift_true, drift_true + drift_missed
            ),
            "overall_precision": _ratio(total_true, total_actual),
            "reviewer_usefulness": _ratio(total_useful, total_actual),
            "lexical_contract_rate": _ratio(lexical_passed, lexical_checks),
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
            "minimum_reuse_rate": min(
                case["cache"]["reuse_rate"] for case in cases
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


def run(manifest_path: Path, output_path: Path, repositories_root: Path | None,
        fetch: bool, runs: int, selected: set[str]) -> dict:
    manifest, manifest_sha256 = _read_manifest(manifest_path)
    sources = [
        source for source in manifest["sources"]
        if not selected or source["id"] in selected
    ]
    if selected - {source["id"] for source in sources}:
        missing = ", ".join(sorted(selected - {source["id"] for source in sources}))
        raise EvaluationError(f"unknown case(s): {missing}")
    if not sources:
        raise EvaluationError("no evaluation cases selected")

    cache_root = Path(tempfile.mkdtemp(prefix="glossarize-eval-cache-"))
    try:
        cases = [
            _evaluate_source(
                source,
                _source_root(source, repositories_root, fetch),
                runs,
                cache_root,
            )
            for source in sources
        ]
    finally:
        import shutil
        shutil.rmtree(cache_root, ignore_errors=True)

    aggregate = _aggregate(cases)
    thresholds = _thresholds(
        aggregate,
        manifest.get("release_thresholds") if not selected else None,
    )
    result = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "engine_version": __version__,
        "manifest_sha256": manifest_sha256,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "method": {
            "runtime_runs_per_case": runs,
            "graphify": False,
            "external_source_vendored": False,
        },
        "cases": cases,
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
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    try:
        if args.fetch:
            with tempfile.TemporaryDirectory(prefix="glossarize-eval-repos-") as raw:
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
