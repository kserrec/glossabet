"""The Phase 15/16 corpus and Phase 20 evidence remain reproducible."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from evaluation.run import EVALUATION_SCHEMA_VERSION, verify_results


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evaluation" / "corpus.json"
RESULTS = ROOT / "evaluation" / "results.json"


def test_manifest_pins_licensed_varied_sources():
    manifest = json.loads(MANIFEST.read_text())
    sources = manifest["sources"]

    assert manifest["schema_version"] == 2
    assert len(sources) == 5
    assert len({source["id"] for source in sources}) == len(sources)
    assert {source["primary_language"] for source in sources} == {
        "Python",
        "Go",
        "JavaScript/TypeScript declarations",
        "Python and Clojure multilingual fixture",
    }
    for source in sources:
        assert source["license_spdx"] in {"Apache-2.0", "MIT"}
        assert source["license_url"]
        assert len(source["corpus_sha256"]) == 64
        assert source["corpus_files"] > 0
        if source["kind"] == "external-git":
            assert len(source["commit"]) == 40
            assert source["url"].startswith("https://github.com/")


def test_local_calibration_case_runs_without_network(tmp_path):
    output = tmp_path / "results.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "evaluation" / "run.py"),
            "--case", "calibration-fixture",
            "--runs", "1",
            "--output", str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(output.read_text())
    assert result["schema_version"] == EVALUATION_SCHEMA_VERSION
    assert result["engine"]["version"] == "0.1.0"
    assert len(result["engine"]["source_sha256"]) == 64
    assert result["cases"][0]["corpus"]["files_hashed"] == 7
    assert len(result["cases"][0]["corpus"]["sha256"]) == 64
    assert result["aggregate"]["quality"]["false_alarms"] == 0
    assert result["aggregate"]["source_bytes"] == 903
    assert result["cases"][0]["corpus_budget"]["complete"] is True
    assert result["aggregate"]["quality"]["terminology_recall_where_complete"] == 1.0
    assert result["aggregate"]["quality"]["drift_recall_where_complete"] == 1.0
    assert result["release_thresholds"] == {
        "configured": False,
        "passed": None,
        "checks": [],
    }


def test_language_semantics_case_pins_lexical_and_scope_contracts(tmp_path):
    output = tmp_path / "results.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "evaluation" / "run.py"),
            "--case", "language-semantics-fixture",
            "--runs", "1",
            "--output", str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(output.read_text())
    case = result["cases"][0]
    assert case["lexical"]["passed"] is True
    assert case["lexical"]["checks"] == 15
    assert case["drift"]["actual"] == []
    assert result["aggregate"]["quality"]["lexical_contract_rate"] == 1.0


def test_committed_results_match_current_engine_manifest_and_local_corpora():
    assert verify_results(RESULTS, MANIFEST) == []


def test_evaluation_verifier_rejects_stale_or_weakened_evidence(tmp_path):
    original = json.loads(RESULTS.read_text(encoding="utf-8"))

    def engine_stale(result):
        result["engine"]["source_sha256"] = "0" * 64

    def manifest_stale(result):
        result["manifest_sha256"] = "0" * 64

    def corpus_stale(result):
        result["cases"][0]["corpus"]["sha256"] = "0" * 64

    def external_corpus_stale(result):
        result["cases"][2]["corpus"]["sha256"] = "0" * 64

    def sample_weakened(result):
        result["method"]["runtime_runs_per_case"] = 1

    def thresholds_weakened(result):
        result["release_thresholds"]["passed"] = False

    mutations = [
        (engine_stale, "engine version, schema, or source digest is stale"),
        (manifest_stale, "evaluation manifest digest is stale"),
        (corpus_stale, "local corpus digest is stale"),
        (external_corpus_stale, "corpus digest does not match manifest"),
        (sample_weakened, "required five-run sample"),
        (thresholds_weakened, "thresholds are not configured and passing"),
    ]
    for index, (mutate, expected) in enumerate(mutations):
        result = deepcopy(original)
        mutate(result)
        path = tmp_path / f"results-{index}.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        assert any(
            expected in error for error in verify_results(path, MANIFEST)
        )
