"""Lexical, register, drift, and structural evidence stays reproducible."""

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

    assert manifest["schema_version"] == 5
    assert len(sources) == 7
    assert len({source["id"] for source in sources}) == len(sources)
    assert {source["primary_language"] for source in sources} == {
        "Python",
        "Go",
        "JavaScript/TypeScript declarations",
        "Python and Clojure multilingual fixture",
        "Python with Graphify fixture",
        "Python with capped Graphify fixture",
    }
    for source in sources:
        assert source["license_spdx"] in {"Apache-2.0", "MIT"}
        assert source["license_url"]
        assert len(source["corpus_sha256"]) == 64
        assert source["corpus_files"] > 0
        assert source["expectations"]["register"]["dominant_style"] in {
            "snake_case", "camelCase", "PascalCase", "UPPER_SNAKE"
        }
        assert isinstance(
            source["expectations"]["register"]["predominantly_multi_word"],
            bool,
        )
        if source["kind"] == "external-git":
            assert len(source["commit"]) == 40
            assert source["url"].startswith("https://github.com/")
    assert manifest["self_register"] == {
        "dominant_style": "snake_case",
        "predominantly_multi_word": True,
    }
    assert manifest["self_nominations"] == {
        "required": [
            {
                "term": "structural",
                "nomination_kind": "deserves disambiguation",
            },
            {
                "term": "plugin",
                "nomination_kind": "deserves a canonical name",
            },
            {
                "term": "coverage",
                "nomination_kind": "deserves a canonical name",
            },
            {
                "term": "drift",
                "nomination_kind": "deserves a canonical name",
            },
        ],
        "forbidden_terms": ["json", "path", "file", "name", "run", "root"],
        "require_all_typed": True,
    }


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
    assert result["cases"][0]["register"]["passed"] is True
    assert result["self_register"]["expected"] == {
        "dominant_style": "snake_case",
        "predominantly_multi_word": True,
    }
    assert result["self_register"]["actual"]["dominant_style"] == "snake_case"
    assert result["self_register"]["actual"]["predominantly_multi_word"] is True
    assert result["aggregate"]["quality"]["register_accuracy"] == 1.0
    assert result["self_nominations"]["passed"] is True
    assert result["self_nominations"]["checks"] == 11
    assert result["aggregate"]["quality"]["nomination_quality"] == 1.0
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
    assert case["register"]["passed"] is True


def test_structural_cases_pin_findings_provenance_and_truncation(tmp_path):
    output = tmp_path / "results.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "evaluation" / "run.py"),
            "--case", "structural-complete-fixture",
            "--case", "structural-truncation-fixture",
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
    complete, truncated = result["cases"]
    assert result["method"]["graphify_cases"] == 2
    assert complete["structural"]["actual"] == [
        "boundary-mismatch:Identity Boundary:authentication:authorization",
        "boundary-mismatch:Mixed Region:payment:run",
        "boundary-mismatch:Mixed Region:payment:tenant",
        "boundary-mismatch:Mixed Region:run:tenant",
        "fragmentation:tenant",
        "orphaned-concept:workspace",
        "overloaded-structural-region:Mixed Region",
        "unnamed-structure:Lease Boundary",
    ]
    assert complete["structural"]["false_positive"] == []
    assert complete["structural"]["false_negative"] == []
    assert complete["structural"]["contracts"] == {
        "checks": 17,
        "passed_checks": 17,
        "passed": True,
        "failures": [],
    }
    assert truncated["structural"]["actual"] == []
    assert truncated["structural"]["coverage"]["groups"] == {
        "complete": False,
        "dropped_items": 1,
        "included_items": 50,
        "reasons": ["structural group detail cap is 50 items"],
        "total_items": 51,
        "total_items_exact": True,
    }
    assert truncated["structural"]["coverage"]["validation_complete"] is False
    assert truncated["structural"]["contracts"]["passed"] is True
    assert result["aggregate"]["quality"]["structural_precision"] == 1.0
    assert (
        result["aggregate"]["quality"]["structural_recall_where_complete"]
        == 1.0
    )
    assert result["aggregate"]["quality"]["structural_contract_rate"] == 1.0


def test_committed_results_are_genuine_and_internally_consistent():
    assert verify_results(RESULTS, MANIFEST) == []


def test_genuineness_verifier_catches_internal_tampering_without_currency(
    tmp_path,
):
    original = json.loads(RESULTS.read_text(encoding="utf-8"))

    tampered_aggregate = deepcopy(original)
    tampered_aggregate["aggregate"]["quality"]["false_alarms"] += 1
    aggregate_path = tmp_path / "tampered-aggregate.json"
    aggregate_path.write_text(json.dumps(tampered_aggregate), encoding="utf-8")
    assert any(
        "aggregate is stale or internally inconsistent" in error
        for error in verify_results(aggregate_path, MANIFEST)
    )

    weakened_thresholds = deepcopy(original)
    weakened_thresholds["release_thresholds"]["passed"] = False
    thresholds_path = tmp_path / "weakened-thresholds.json"
    thresholds_path.write_text(
        json.dumps(weakened_thresholds), encoding="utf-8"
    )
    assert any(
        "thresholds are not configured and passing" in error
        for error in verify_results(thresholds_path, MANIFEST)
    )

    dropped_check = deepcopy(original)
    dropped_check["release_thresholds"]["checks"] = [
        check
        for check in dropped_check["release_thresholds"]["checks"]
        if check["name"] != "terminology_precision_min"
    ]
    dropped_path = tmp_path / "dropped-check.json"
    dropped_path.write_text(json.dumps(dropped_check), encoding="utf-8")
    assert any(
        "thresholds are missing required checks" in error
        for error in verify_results(dropped_path, MANIFEST)
    )

    malformed_engine = deepcopy(original)
    malformed_engine["engine"]["source_sha256"] = "not-a-digest"
    engine_path = tmp_path / "malformed-engine.json"
    engine_path.write_text(json.dumps(malformed_engine), encoding="utf-8")
    assert any(
        "engine identity metadata is malformed" in error
        for error in verify_results(engine_path, MANIFEST)
    )

    method_as_list = deepcopy(original)
    method_as_list["method"] = ["not", "a", "mapping"]
    method_path = tmp_path / "method-as-list.json"
    method_path.write_text(json.dumps(method_as_list), encoding="utf-8")
    assert any(
        "required five-run sample" in error
        for error in verify_results(method_path, MANIFEST)
    )


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

    def graphify_weakened(result):
        result["method"]["graphify_cases"] = 0

    def structural_stale(result):
        result["cases"][-2]["structural"]["contracts"]["passed"] = False

    def thresholds_weakened(result):
        result["release_thresholds"]["passed"] = False

    def register_stale(result):
        result["self_register"]["actual"]["dominant_style"] = "camelCase"

    def nomination_stale(result):
        result["self_nominations"]["passed"] = False

    mutations = [
        (engine_stale, "engine version, schema, or source digest is stale"),
        (manifest_stale, "evaluation manifest digest is stale"),
        (corpus_stale, "local corpus digest is stale"),
        (external_corpus_stale, "corpus digest does not match manifest"),
        (sample_weakened, "required five-run sample"),
        (graphify_weakened, "Graphify case count is stale"),
        (structural_stale, "local structural evidence is stale"),
        (register_stale, "self register evidence is stale"),
        (nomination_stale, "self nomination evidence is stale"),
        (thresholds_weakened, "thresholds are not configured and passing"),
    ]
    for index, (mutate, expected) in enumerate(mutations):
        result = deepcopy(original)
        mutate(result)
        path = tmp_path / f"results-{index}.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        assert any(
            expected in error
            for error in verify_results(path, MANIFEST, current=True)
        )
