"""Boundaries of the Codex evaluation lane: offline verification is pure
reading — no host, no process, no user configuration."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from evaluation.codex import results
from evaluation.codex.contract import DEFAULT_RESULTS

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "evaluation" / "codex"
OFFLINE_MODULES = ("contract", "scenarios", "results", "history", "artifact")


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
