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
