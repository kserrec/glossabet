"""The Phase 15/16 corpus and evaluator remain locally reproducible."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evaluation" / "corpus.json"


def test_manifest_pins_licensed_varied_sources():
    manifest = json.loads(MANIFEST.read_text())
    sources = manifest["sources"]

    assert manifest["schema_version"] == 1
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
    assert result["aggregate"]["quality"]["false_alarms"] == 0
    assert result["aggregate"]["source_bytes"] == 904
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
