"""Boundaries of the Codex evaluation lane: offline verification is pure
reading — no host, no process, no user configuration."""

from __future__ import annotations

import ast
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from evaluation.codex import host, results, runner
from evaluation.codex.contract import DEFAULT_RESULTS, AgentEvaluationError

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "evaluation" / "codex"
OFFLINE_MODULES = (
    "contract", "scenarios", "results", "history", "artifact", "trace", "fixtures"
)
HOST_MODULES = ("host", "runner", "cli")


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("module", OFFLINE_MODULES)
def test_offline_modules_import_no_host(module):
    """The live host (today still `scripts/agent_eval.py`) is never a
    dependency of the verifier; the wrapper depends on the lane, not the
    reverse."""
    names = _imports(LANE / f"{module}.py")
    assert not any(name.startswith("scripts") for name in names), names
    assert not any(
        name in {f"evaluation.codex.{m}" for m in HOST_MODULES} for name in names
    ), names
    assert not any(
        name.startswith("evaluation.") and not name.startswith(("evaluation.codex", "evaluation.harness"))
        for name in names
    ), names


def test_default_verification_spawns_nothing_and_reads_no_user_state(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline verification must not do this")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr("shutil.which", forbidden)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: forbidden()))
    monkeypatch.setattr("os.path.expanduser", forbidden)

    assert results.verify_results(DEFAULT_RESULTS) == []


@pytest.mark.parametrize("module", ["scenarios", "trace"])
def test_judgment_modules_spawn_nothing(module):
    """Scenario judgment and trace parsing are pure: they never reach for a
    process, an executable search, or a temporary directory — so they cannot
    install, remove, or invoke a plugin."""
    names = _imports(LANE / f"{module}.py")
    assert not names & {"subprocess", "shutil", "tempfile", "os"}, names


def test_fixtures_only_ever_run_git():
    """Fixture construction may spawn git to build the two graph fixtures and
    nothing else."""
    tree = ast.parse((LANE / "fixtures.py").read_text(encoding="utf-8"))
    spawned = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]
    assert len(spawned) == 1
    command = spawned[0].args[0]
    assert isinstance(command, ast.List)
    first = command.elts[0]
    assert isinstance(first, ast.Constant) and first.value == "git"


# --- lifecycle: cleanup removes exactly what was created, at every stage ---


@pytest.mark.parametrize("failed_call", [1, 2])
def test_install_records_cleanup_ownership_before_parsing_mutating_responses(
    monkeypatch, tmp_path, failed_call
):
    calls = 0
    mutations: list[list[str]] = []

    def mutate_then_respond(command, **_kwargs):
        nonlocal calls
        calls += 1
        mutations.append(command)
        if calls == failed_call:
            raise AgentEvaluationError("mutated state followed by malformed JSON")
        return {"marketplaceName": "temporary"}

    monkeypatch.setattr(host, "run_command", mutate_then_respond)
    lifecycle = host.PluginLifecycle()

    with pytest.raises(AgentEvaluationError, match="malformed JSON"):
        host.install_plugin(
            "codex", tmp_path / "marketplace", "temporary", lifecycle
        )

    assert len(mutations) == failed_call
    assert lifecycle.marketplace_may_exist is True
    assert lifecycle.plugin_may_exist is (failed_call == 2)
    assert (lifecycle.cache_parent is not None) is (failed_call == 2)


def _fake_host(monkeypatch, install_behavior, run_codex_behavior=None):
    """Stub every host effect of ``runner.run_evaluation``; return the
    lifecycles handed to cleanup and the attempt records retained."""
    cleanups: list[host.PluginLifecycle] = []
    recorded: list[dict] = []
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(runner, "codex_version", lambda codex: "0.0.0-test")
    monkeypatch.setattr(runner, "input_identity", lambda: {"plugin_sha256": "0" * 64})
    monkeypatch.setattr(runner, "competing_standalone_skill_paths", lambda: ())
    monkeypatch.setattr(runner, "ensure_no_installed_glossabet", lambda codex: None)
    monkeypatch.setattr(runner, "prepare_marketplace", lambda root, name: None)
    monkeypatch.setattr(runner, "install_plugin", install_behavior)
    monkeypatch.setattr(
        runner,
        "cleanup_plugin",
        lambda codex, plugin_id, name, lifecycle: cleanups.append(replace(lifecycle)),
    )
    if run_codex_behavior is not None:
        monkeypatch.setattr(runner, "run_codex", run_codex_behavior)
    monkeypatch.setattr(runner, "append_attempt", recorded.append)
    return cleanups, recorded


def _run_and_expect(tmp_path, error_type):
    with pytest.raises(error_type) as raised:
        runner.run_recorded_evaluation(tmp_path / "out.json", "attempt-test")
    return raised.value


def test_failure_before_marketplace_creation_cleans_nothing(monkeypatch, tmp_path):
    def install(codex, marketplace, name, lifecycle):
        raise AgentEvaluationError("marketplace add refused")

    cleanups, recorded = _fake_host(monkeypatch, install)
    error = _run_and_expect(tmp_path, AgentEvaluationError)

    assert cleanups == [host.PluginLifecycle()]
    assert recorded[0]["checks"]["plugin_preflight"] == "failed"
    assert recorded[0]["cleanup_verified"] is True
    assert recorded[0]["failures"] == ["marketplace add refused"]
    assert not any(hasattr(error, name) for name in (
        "cleanup_verified", "failed_stage", "attempt_usage",
        "marketplace_may_exist", "plugin_may_exist", "cache_parent",
    ))


def test_failure_after_marketplace_creation_removes_only_the_marketplace(
    monkeypatch, tmp_path
):
    def install(codex, marketplace, name, lifecycle):
        lifecycle.marketplace_may_exist = True
        raise AgentEvaluationError("plugin add refused")

    cleanups, recorded = _fake_host(monkeypatch, install)
    _run_and_expect(tmp_path, AgentEvaluationError)

    assert cleanups == [host.PluginLifecycle(marketplace_may_exist=True)]
    assert recorded[0]["checks"]["plugin_preflight"] == "failed"


def test_failure_after_plugin_installation_removes_plugin_marketplace_and_cache(
    monkeypatch, tmp_path
):
    cache = tmp_path / "cache" / "market"

    def install(codex, marketplace, name, lifecycle):
        lifecycle.marketplace_may_exist = True
        lifecycle.plugin_may_exist = True
        lifecycle.cache_parent = cache
        raise AgentEvaluationError("installed plugin has no skill-local runner")

    cleanups, recorded = _fake_host(monkeypatch, install)
    _run_and_expect(tmp_path, AgentEvaluationError)

    assert cleanups == [
        host.PluginLifecycle(
            marketplace_may_exist=True,
            plugin_may_exist=True,
            cache_parent=cache,
        )
    ]
    assert recorded[0]["checks"] == {
        "plugin_preflight": "failed",
        "plugin_scenarios": "not_run",
        "missing_cli_boundary": "not_run",
    }


def test_interrupt_during_host_run_still_cleans_up_and_records(monkeypatch, tmp_path):
    def install(codex, marketplace, name, lifecycle):
        lifecycle.marketplace_may_exist = True
        lifecycle.plugin_may_exist = True
        lifecycle.cache_parent = tmp_path / "cache"
        return "glossabet@market", tmp_path / "installed"

    def run_codex(*args, **kwargs):
        raise KeyboardInterrupt()

    cleanups, recorded = _fake_host(monkeypatch, install, run_codex)
    error = _run_and_expect(tmp_path, KeyboardInterrupt)

    assert len(cleanups) == 1 and cleanups[0].plugin_may_exist is True
    assert recorded[0]["checks"]["plugin_scenarios"] == "failed"
    assert recorded[0]["cleanup_verified"] is True
    assert recorded[0]["failures"] == ["KeyboardInterrupt"]
    assert type(error) is KeyboardInterrupt and not hasattr(error, "failed_stage")


def test_cleanup_failure_after_an_ordinary_failure_is_reported_together(
    monkeypatch, tmp_path, capsys
):
    original = AgentEvaluationError("plugin add refused")

    def install(codex, marketplace, name, lifecycle):
        lifecycle.marketplace_may_exist = True
        raise original

    cleanups, recorded = _fake_host(monkeypatch, install)

    def failing_cleanup(codex, plugin_id, name, lifecycle):
        raise AgentEvaluationError("marketplace remove refused")

    monkeypatch.setattr(runner, "cleanup_plugin", failing_cleanup)
    error = _run_and_expect(tmp_path, AgentEvaluationError)

    assert error is original
    assert str(error) == "plugin add refused"
    assert recorded[0]["cleanup_verified"] is False
    assert recorded[0]["safety_pass"] is False
    assert recorded[0]["failures"] == [
        "plugin add refused",
        "secondary cleanup failure: AgentEvaluationError: "
        "marketplace remove refused",
    ]
    assert capsys.readouterr().err == (
        "agent evaluation: secondary cleanup failure: "
        "AgentEvaluationError: marketplace remove refused\n"
    )


def test_cleanup_failure_does_not_replace_interrupt(monkeypatch, tmp_path, capsys):
    original = KeyboardInterrupt()

    def install(codex, marketplace, name, lifecycle):
        lifecycle.marketplace_may_exist = True
        lifecycle.plugin_may_exist = True
        return "glossabet@market", tmp_path / "installed"

    def run_codex(*args, **kwargs):
        raise original

    _cleanups, recorded = _fake_host(monkeypatch, install, run_codex)

    def failing_cleanup(codex, plugin_id, name, lifecycle):
        raise AgentEvaluationError("marketplace remove refused")

    monkeypatch.setattr(runner, "cleanup_plugin", failing_cleanup)
    error = _run_and_expect(tmp_path, KeyboardInterrupt)

    assert error is original
    assert recorded[0]["cleanup_verified"] is False
    assert recorded[0]["failures"] == [
        "KeyboardInterrupt",
        "secondary cleanup failure: AgentEvaluationError: "
        "marketplace remove refused",
    ]
    assert "secondary cleanup failure" in capsys.readouterr().err


def test_cleanup_interrupt_does_not_replace_an_ordinary_failure(
    monkeypatch,
    tmp_path,
    capsys,
):
    original = AgentEvaluationError("plugin add refused")

    def install(codex, marketplace, name, lifecycle):
        lifecycle.marketplace_may_exist = True
        raise original

    _cleanups, recorded = _fake_host(monkeypatch, install)

    def interrupted_cleanup(codex, plugin_id, name, lifecycle):
        raise KeyboardInterrupt()

    monkeypatch.setattr(runner, "cleanup_plugin", interrupted_cleanup)
    error = _run_and_expect(tmp_path, AgentEvaluationError)

    assert error is original
    assert recorded[0]["cleanup_verified"] is False
    assert recorded[0]["failures"] == [
        "plugin add refused",
        "secondary cleanup failure: KeyboardInterrupt: no detail",
    ]
    assert "secondary cleanup failure: KeyboardInterrupt" in capsys.readouterr().err


def test_results_verifier_never_loads_the_host_module():
    code = (
        "import sys; import evaluation.codex.results; "
        "raise SystemExit(int('evaluation.codex.host' in sys.modules))"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
