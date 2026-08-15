"""Installed Codex boundary evidence is current, bounded, and fail-closed."""

import json
from copy import deepcopy
from pathlib import Path

from scripts.agent_eval import _tree_sha256, verify_results


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evaluation" / "agent-scenarios.json"
RESULTS = ROOT / "evaluation" / "agent-results.json"


def test_agent_manifest_covers_every_phase_22_boundary():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert [scenario["id"] for scenario in manifest["scenarios"]] == [
        "fresh",
        "stale",
        "absent",
        "malformed",
        "oversized",
        "symlinked",
        "partial",
        "monorepo",
        "resumed-glossary",
        "sensitive-file",
        "missing-cli",
    ]
    sensitive = manifest["scenarios"][-2]
    assert sensitive["accepted_statuses"] == [
        "grounded",
        "grounded-with-warning",
    ]


def test_committed_installed_agent_evidence_is_current_and_complete():
    assert verify_results(RESULTS) == []
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert results["summary"] == {
        "required": 11,
        "passed": 11,
        "failed": 0,
        "all_passed": True,
    }
    assert results["delivery"]["installed_plugin_skill_read"] is True
    assert results["delivery"]["temporary_plugin_state_removed"] is True
    sensitive = next(
        item for item in results["scenarios"] if item["id"] == "sensitive-file"
    )
    assert sensitive["observed"]["sensitive_paths"] == [
        ".env",
        "api-secret.txt",
    ]
    assert sensitive["unexpected_writes"] == []


def test_plugin_identity_ignores_interpreter_bytecode_cache(tmp_path):
    plugin = tmp_path / "plugin"
    source = plugin / "skills" / "glossabet" / "scripts" / "run_glossabet.py"
    source.parent.mkdir(parents=True)
    source.write_text("print('glossabet')\n", encoding="utf-8")
    clean_identity = _tree_sha256(plugin)

    cache = source.parent / "__pycache__" / "run_glossabet.cpython-312.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"generated interpreter cache")

    assert _tree_sha256(plugin) == clean_identity


def test_agent_verifier_rejects_stale_weakened_or_failing_evidence(tmp_path):
    original = json.loads(RESULTS.read_text(encoding="utf-8"))

    mutations = []

    stale = deepcopy(original)
    stale["inputs"]["evaluator_sha256"] = "0" * 64
    mutations.append((stale, "inputs are stale"))

    weakened = deepcopy(original)
    weakened["method"]["host_runs"] = 1
    mutations.append((weakened, "method is weakened or stale"))

    delivery_missing = deepcopy(original)
    delivery_missing["delivery"]["installed_plugin_skill_read"] = False
    mutations.append((delivery_missing, "delivery evidence is missing or stale"))

    scenario_failed = deepcopy(original)
    scenario_failed["scenarios"][0]["passed"] = False
    mutations.append((scenario_failed, "scenario does not pass"))

    for index, (value, expected) in enumerate(mutations):
        path = tmp_path / f"agent-results-{index}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        assert any(expected in error for error in verify_results(path))
