"""Boundaries of the Claude evaluation lane: offline verification reads
retained evidence only — no host, no process, no login state."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.claude import results
from evaluation.claude.contract import DEFAULT_RESULTS

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
