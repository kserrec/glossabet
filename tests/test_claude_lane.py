"""Boundaries of the Claude evaluation lane: offline verification reads
retained evidence only — no host, no process, no login state."""

from __future__ import annotations

import ast
import os
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from evaluation.claude import host, results, runner
from evaluation.claude.contract import (
    DEFAULT_RESULTS,
    ClaudeEvaluationError,
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
    original = ClaudeEvaluationError("synthetic host refusal")

    def failing_scenario(claude, hook, root, *args, **kwargs):
        seen.append(root.parent)
        raise original

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
    assert raised.value is original
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


def test_cleanup_failure_does_not_replace_ordinary_failure(
    monkeypatch, tmp_path, capsys
):
    original = ClaudeEvaluationError("synthetic host refusal")

    def failing_scenario(*args, **kwargs):
        raise original

    recorded = _stub_live_host(monkeypatch, tmp_path, failing_scenario)

    def refuse_cleanup(_scratch):
        raise OSError("synthetic cleanup refusal")

    monkeypatch.setattr(runner, "remove_owned_scratch", refuse_cleanup)
    with pytest.raises(ClaudeEvaluationError) as raised:
        runner.run_recorded_evaluation(
            tmp_path / "out.json",
            "attempt-cleanup",
            claude=tmp_path / "claude",
            installed_plugin=tmp_path / "plugin",
            scratch_parent=tmp_path,
        )

    assert raised.value is original
    assert recorded[0]["cleanup_verified"] is False
    assert recorded[0]["safety_pass"] is False
    assert recorded[0]["failures"] == [
        "synthetic host refusal",
        "secondary cleanup failure: OSError: synthetic cleanup refusal",
    ]
    assert capsys.readouterr().err == (
        "Claude evaluation: secondary cleanup failure: "
        "OSError: synthetic cleanup refusal\n"
    )
    assert not hasattr(raised.value, "cleanup_verified")


def test_cleanup_failure_does_not_replace_interrupt(monkeypatch, tmp_path, capsys):
    original = KeyboardInterrupt()

    def interrupted_scenario(*args, **kwargs):
        raise original

    recorded = _stub_live_host(monkeypatch, tmp_path, interrupted_scenario)

    def refuse_cleanup(_scratch):
        raise OSError("synthetic cleanup refusal")

    monkeypatch.setattr(runner, "remove_owned_scratch", refuse_cleanup)
    with pytest.raises(KeyboardInterrupt) as raised:
        runner.run_recorded_evaluation(
            tmp_path / "out.json",
            "attempt-interrupt-cleanup",
            claude=tmp_path / "claude",
            installed_plugin=tmp_path / "plugin",
            scratch_parent=tmp_path,
        )

    assert raised.value is original
    assert recorded[0]["cleanup_verified"] is False
    assert recorded[0]["failures"] == [
        "KeyboardInterrupt",
        "secondary cleanup failure: OSError: synthetic cleanup refusal",
    ]
    assert "secondary cleanup failure" in capsys.readouterr().err


def test_owned_scratch_removes_windows_readonly_git_objects(
    monkeypatch, tmp_path
):
    scratch = host.owned_scratch(tmp_path)
    git_object = scratch.path / "fixture" / ".git" / "objects" / "14" / "object"
    git_object.parent.mkdir(parents=True)
    git_object.write_bytes(b"git object")
    git_object.chmod(stat.S_IREAD)
    real_unlink = host.os.unlink
    object_unlink_attempts = 0
    retry_was_writable = False

    def windows_readonly_unlink(path, *, dir_fd=None):
        nonlocal object_unlink_attempts, retry_was_writable
        if Path(path).name == git_object.name:
            object_unlink_attempts += 1
            if object_unlink_attempts == 1:
                raise PermissionError("synthetic Windows read-only bit")
            retry_was_writable = bool(
                git_object.stat().st_mode & stat.S_IWRITE
            )
        return real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(host.os, "unlink", windows_readonly_unlink)

    try:
        assert host.remove_owned_scratch(scratch) is True
    finally:
        if git_object.exists():
            git_object.chmod(stat.S_IWRITE)

    assert not scratch.path.exists()
    assert object_unlink_attempts == 2
    assert retry_was_writable is True


def test_owned_scratch_accepts_a_confined_entry_vanishing_during_delete(
    monkeypatch, tmp_path
):
    scratch = host.owned_scratch(tmp_path)
    maintenance_lock = scratch.path / "fixture" / ".git" / "maintenance.lock"
    maintenance_lock.parent.mkdir(parents=True)
    maintenance_lock.touch()
    real_rmtree = host.shutil.rmtree
    simulated_race = False

    def vanish_during_remove(path, *, onerror=None):
        nonlocal simulated_race
        maintenance_lock.unlink()
        try:
            maintenance_lock.unlink()
        except FileNotFoundError:
            assert onerror is not None
            simulated_race = True
            onerror(host.os.unlink, str(maintenance_lock), sys.exc_info())
        real_rmtree(path)

    monkeypatch.setattr(host.shutil, "rmtree", vanish_during_remove)

    assert host.remove_owned_scratch(scratch) is True
    assert simulated_race is True
    assert not scratch.path.exists()


def test_owned_scratch_rejects_an_outside_path(tmp_path):
    scratch = host.owned_scratch(tmp_path)
    outside_parent = tmp_path / "outside"
    outside_parent.mkdir()
    outside = outside_parent / scratch.path.name
    outside.mkdir()

    with pytest.raises(
        ClaudeEvaluationError, match="outside its owned parent"
    ):
        host.remove_owned_scratch(replace(scratch, path=outside))

    assert outside.is_dir()
    assert host.remove_owned_scratch(scratch) is True


def test_owned_scratch_rejects_a_parent_swapped_during_resolution(
    monkeypatch, tmp_path
):
    requested = tmp_path / "requested"
    requested.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    real_resolve = Path.resolve
    swapped = False

    def swap_then_resolve(self, *args, **kwargs):
        nonlocal swapped
        if self == requested and not swapped:
            requested.rmdir()
            requested.symlink_to(outside, target_is_directory=True)
            swapped = True
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", swap_then_resolve)

    with pytest.raises(
        ClaudeEvaluationError, match="changed while being inspected"
    ):
        host.owned_scratch(requested)

    assert swapped is True
    assert _scratch_dirs(outside) == []


def test_owned_scratch_anchors_creation_before_a_parent_swap(
    monkeypatch,
    tmp_path,
):
    if not host._supports_anchored_scratch_creation():
        pytest.skip("directory-relative scratch creation is unavailable")
    requested = tmp_path / "requested"
    requested.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    real_mkdir = host.os.mkdir
    swapped = False

    def swap_then_mkdir(path, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if (
            not swapped
            and dir_fd is not None
            and str(path).startswith(host._SCRATCH_PREFIX)
        ):
            requested.rmdir()
            requested.symlink_to(outside, target_is_directory=True)
            swapped = True
        return real_mkdir(path, mode=mode, dir_fd=dir_fd)

    monkeypatch.setattr(host, "_supports_anchored_scratch_creation", lambda: True)
    monkeypatch.setattr(host.os, "mkdir", swap_then_mkdir)

    with pytest.raises(
        ClaudeEvaluationError, match="changed while being inspected"
    ):
        host.owned_scratch(requested)

    assert swapped is True
    assert _scratch_dirs(outside) == []


def test_owned_scratch_path_fallback_removes_a_redirected_empty_scratch(
    monkeypatch,
    tmp_path,
):
    requested = tmp_path / "requested"
    requested.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink_probe = tmp_path / "symlink-probe"
    try:
        symlink_probe.symlink_to(outside, target_is_directory=True)
        symlink_probe.unlink()
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    real_mkdtemp = host.tempfile.mkdtemp
    swapped = False

    def swap_then_create(*, prefix, dir):
        nonlocal swapped
        requested.rmdir()
        requested.symlink_to(outside, target_is_directory=True)
        swapped = True
        return real_mkdtemp(prefix=prefix, dir=dir)

    monkeypatch.setattr(host, "_supports_anchored_scratch_creation", lambda: False)
    monkeypatch.setattr(host.tempfile, "mkdtemp", swap_then_create)

    with pytest.raises(
        ClaudeEvaluationError, match="changed while being inspected"
    ):
        host.owned_scratch(requested)

    assert swapped is True
    assert _scratch_dirs(outside) == []


def test_owned_scratch_rejects_a_child_replaced_before_open(
    monkeypatch,
    tmp_path,
):
    if not host._supports_anchored_scratch_creation():
        pytest.skip("directory-relative scratch creation is unavailable")
    requested = tmp_path / "requested"
    requested.mkdir()
    replacement_source = tmp_path / "replacement"
    replacement_source.mkdir()
    (replacement_source / "KEEP.txt").write_text("KEEP", encoding="utf-8")
    real_open = host.os.open
    replacement: Path | None = None

    def replace_then_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal replacement
        if (
            replacement is None
            and dir_fd is not None
            and str(path).startswith(host._SCRATCH_PREFIX)
        ):
            replacement = requested / str(path)
            replacement.rmdir()
            replacement_source.rename(replacement)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(host, "_supports_anchored_scratch_creation", lambda: True)
    monkeypatch.setattr(host.os, "open", replace_then_open)

    with pytest.raises(
        ClaudeEvaluationError, match="changed while being created"
    ):
        host.owned_scratch(requested)

    assert replacement is not None
    assert (replacement / "KEEP.txt").read_text(encoding="utf-8") == "KEEP"
    assert not (replacement / host._SCRATCH_MARKER).exists()


def test_owned_scratch_rejects_a_replaced_root(tmp_path):
    scratch = host.owned_scratch(tmp_path)
    host.shutil.rmtree(scratch.path)
    scratch.path.mkdir()

    with pytest.raises(ClaudeEvaluationError, match="replaced evaluator scratch"):
        host.remove_owned_scratch(scratch)

    assert scratch.path.is_dir()
    scratch.path.rmdir()


def test_owned_scratch_does_not_follow_nested_symlink(tmp_path):
    scratch = host.owned_scratch(tmp_path)
    canary = tmp_path / "canary"
    canary.mkdir()
    keep = canary / "keep.txt"
    keep.write_text("KEEP", encoding="utf-8")
    link = scratch.path / "external"
    try:
        link.symlink_to(canary, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    assert host.remove_owned_scratch(scratch) is True
    assert keep.read_text(encoding="utf-8") == "KEEP"


def test_owned_scratch_root_swap_does_not_follow_symlink(
    monkeypatch, tmp_path
):
    scratch = host.owned_scratch(tmp_path)
    canary = tmp_path / "canary"
    canary.mkdir()
    keep = canary / "keep.txt"
    keep.write_text("KEEP", encoding="utf-8")
    real_rmtree = host.shutil.rmtree
    swapped = False

    def swap_before_remove(path, *, onerror=None):
        nonlocal swapped
        if not swapped:
            swapped = True
            real_rmtree(path)
            Path(path).symlink_to(canary, target_is_directory=True)
        return real_rmtree(path, onerror=onerror)

    monkeypatch.setattr(host.shutil, "rmtree", swap_before_remove)
    try:
        completed = host.remove_owned_scratch(scratch)
    except OSError:
        completed = False

    assert keep.read_text(encoding="utf-8") == "KEEP"
    assert canary.is_dir()
    assert completed == (not os.path.lexists(scratch.path))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction contract")
def test_owned_scratch_does_not_follow_windows_junction(tmp_path):
    scratch = host.owned_scratch(tmp_path)
    canary = tmp_path / "junction-canary"
    canary.mkdir()
    keep = canary / "keep.txt"
    keep.write_text("KEEP", encoding="utf-8")
    junction = scratch.path / "external-junction"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(canary)],
        text=True,
        capture_output=True,
        check=False,
    )
    if created.returncode:
        pytest.skip(f"directory junctions unavailable: {created.stderr}")

    assert host.remove_owned_scratch(scratch) is True
    assert keep.read_text(encoding="utf-8") == "KEEP"
