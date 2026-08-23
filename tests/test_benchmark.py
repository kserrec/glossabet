"""The performance baseline script runs offline and reports every case."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_CASES = [
    "evidence_cold", "evidence_warm", "evidence_multilanguage", "terminology",
    "compound_matching", "drift", "graphify_complete", "graphify_truncated",
    "agent_context_lean", "agent_context_full",
]
SCALE_CASES = [
    "scale_evidence_repository", "scale_terminology_top_n",
    "scale_compound_matching", "scale_graphify_group_cap",
    "scale_agent_context",
]


def test_benchmark_runs_every_case_and_writes_json(tmp_path):
    output = tmp_path / "bench.json"
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "benchmark.py"),
         "--repeat", "1", "--json", str(output)],
        cwd=ROOT, capture_output=True, text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    for case in EXPECTED_CASES:
        assert case in completed.stdout
    document = json.loads(output.read_text(encoding="utf-8"))
    assert [m["name"] for m in document["measurements"]] == EXPECTED_CASES
    assert document["repeat"] == 1
    for measurement in document["measurements"]:
        assert measurement["median_ms"] > 0
        assert measurement["output_bytes"] > 0
        assert measurement["ledger"]
    assert "fixtures" in document["environment"]
    assert not list(ROOT.glob("glossabet-benchmark-*"))


def test_benchmark_generates_reduced_scale_cases_in_temporary_space(tmp_path):
    output = tmp_path / "scale.json"
    command = [
        sys.executable,
        str(ROOT / "scripts" / "benchmark.py"),
        "--scale",
        "--scale-size",
        "ci",
        "--repeat",
        "1",
        "--json",
        str(output),
    ]
    for case in SCALE_CASES:
        command.extend(("--only", case))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    document = json.loads(output.read_text(encoding="utf-8"))
    assert [item["name"] for item in document["measurements"]] == SCALE_CASES
    assert document["environment"]["scale"] == {
        "source_files": 40,
        "source_directories": 8,
        "terminology_terms": 40,
        "compound_terms": 30,
        "graph_groups": 8,
        "graph_members_per_group": 6,
    }
    ledgers = {
        item["name"]: item["ledger"] for item in document["measurements"]
    }
    assert ledgers["scale_evidence_repository"]["source_files_complete"] is True
    assert ledgers["scale_terminology_top_n"]["considered_pairs"] > 0
    assert ledgers["scale_compound_matching"]["match_work_complete"] is True
    assert ledgers["scale_graphify_group_cap"]["groups_included"] == 8
    assert ledgers["scale_agent_context"]["source_files"] == 40
    assert not list(ROOT.glob("glossabet-benchmark-*"))
