"""Composition of one deterministic evaluation run: each manifest source is
checked out or located, built cold and warm under a private cache, scored
by every family, and aggregated into one result document.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import tempfile
from pathlib import Path

from evaluation.deterministic.contract import (
    EVALUATION_SCHEMA_VERSION,
    PROJECT_ROOT,
    EvaluationError,
)
from evaluation.deterministic.results import aggregate, thresholds
from evaluation.deterministic.scoring import (
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
from evaluation.deterministic.sources import (
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
from glossabet.analysis.evidence import build_evidence
from glossabet.glossary.drift import build_drift
from glossabet.glossary.schema import validate_glossary


def evaluate_source(source: dict, root: Path, runs: int,
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


def run_evaluation(manifest_path: Path, output_path: Path, repositories_root: Path | None,
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
            evaluate_source(
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
    summary = aggregate(cases, self_register, self_nominations)
    gates = thresholds(
        summary,
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
        "aggregate": summary,
        "release_thresholds": gates,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result
