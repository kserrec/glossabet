"""Boundaries of the Claude evaluation lane: offline verification reads
retained evidence only — no host, no process, no login state."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.claude import results, runner
from evaluation.claude.contract import (
    DEFAULT_RESULTS,
    ClaudeEvaluationError,
    ScratchCleanupFailed,
)

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "evaluation" / "claude"
OFFLINE_MODULES = ("contract", "events", "history", "results")


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("module", OFFLINE_MODULES)
def test_offline_modules_import_no_host_and_spawn_nothing(module):
    names = _imports(LANE / f"{module}.py")
    assert not any(name.startswith("scripts") for name in names), names
    assert not any(
        name.startswith("evaluation.")
        and not name.startswith(("evaluation.claude", "evaluation.harness"))
        for name in names
    ), names
    assert not names & {"subprocess", "shutil", "tempfile"}, names


def test_default_verification_spawns_nothing_and_reads_no_login_state(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline verification must not do this")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr("shutil.which", forbidden)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: forbidden()))

    errors = results.verify_results(DEFAULT_RESULTS)
    assert errors[-1] == "Claude evaluation scenarios did not all pass"
    assert results.verify_history() == []


def test_results_verifier_never_loads_the_host_script():
    code = (
        "import sys; import evaluation.claude.results; "
        "raise SystemExit(int('scripts.claude_eval' in sys.modules))"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# --- scratch ownership: removed under failure and interruption ---


def _stub_live_host(monkeypatch, tmp_path, scenario_behavior):
    recorded: list[dict] = []
    monkeypatch.setattr(
        runner,
        "preflight",
        lambda claude, plugin, environment=None: (
            {
                "claude_version": "0.0.0-test",
                "platform": "Linux-test",
                "auth": {},
                "plugin": {},
                "enabled_plugins": [],
            },
            tmp_path / "hook",
        ),
    )
    monkeypatch.setattr(runner, "run_scenario", scenario_behavior)
    monkeypatch.setattr(runner, "append_attempt", recorded.append)
    return recorded


def _scratch_dirs(parent: Path) -> list[Path]:
    return sorted(parent.glob("glossabet-claude-eval-*"))


def test_ordinary_failure_removes_owned_scratch_and_records_cleanup(
    monkeypatch, tmp_path
):
    seen: list[Path] = []

    def failing_scenario(claude, hook, root, *args, **kwargs):
        seen.append(root.parent)
        raise ClaudeEvaluationError("synthetic host refusal")

    recorded = _stub_live_host(monkeypatch, tmp_path, failing_scenario)
    with pytest.raises(ClaudeEvaluationError, match="synthetic host refusal") as raised:
        runner.run_recorded_evaluation(
            tmp_path / "out.json",
            "attempt-failure",
            claude=tmp_path / "claude",
            installed_plugin=tmp_path / "plugin",
            scratch_parent=tmp_path,
        )

    assert seen and not seen[0].exists()
    assert _scratch_dirs(tmp_path) == []
    assert recorded[0]["cleanup_verified"] is True
    assert recorded[0]["failures"] == ["synthetic host refusal"]
    assert not hasattr(raised.value, "cleanup_verified")


def test_interrupt_removes_owned_scratch_and_records_the_attempt(
    monkeypatch, tmp_path
):
    def interrupted_scenario(*args, **kwargs):
        raise KeyboardInterrupt()

    recorded = _stub_live_host(monkeypatch, tmp_path, interrupted_scenario)
    with pytest.raises(KeyboardInterrupt):
        runner.run_recorded_evaluation(
            tmp_path / "out.json",
            "attempt-interrupt",
            claude=tmp_path / "claude",
            installed_plugin=tmp_path / "plugin",
            scratch_parent=tmp_path,
        )

    assert _scratch_dirs(tmp_path) == []
    assert recorded[0]["failures"] == ["KeyboardInterrupt"]
    assert recorded[0]["cleanup_verified"] is True


def test_cleanup_failure_is_a_typed_error_not_an_attribute(monkeypatch, tmp_path):
    def failing_scenario(*args, **kwargs):
        raise ClaudeEvaluationError("synthetic host refusal")

    recorded = _stub_live_host(monkeypatch, tmp_path, failing_scenario)

    def refuse_cleanup(root, parent):
        raise OSError("synthetic cleanup refusal")

    monkeypatch.setattr(runner, "remove_owned_scratch", refuse_cleanup)
    with pytest.raises(ScratchCleanupFailed) as raised:
        runner.run_recorded_evaluation(
            tmp_path / "out.json",
            "attempt-cleanup",
            claude=tmp_path / "claude",
            installed_plugin=tmp_path / "plugin",
            scratch_parent=tmp_path,
        )

    assert recorded[0]["cleanup_verified"] is False
    assert recorded[0]["safety_pass"] is False
    assert not hasattr(raised.value, "cleanup_verified")
