"""Ownership and offline/live boundaries of the reviewer evaluation lane."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from evaluation.harness.io import dotenv_part
from evaluation.reviewer import results
from evaluation.reviewer.contract import DEFAULT_PACKET, DEFAULT_REVIEW_RESULTS

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "evaluation" / "reviewer"
OFFLINE_MODULES = ("contract", "packet", "results", "trace")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_offline_modules_import_no_live_host_or_process_machinery():
    for module in OFFLINE_MODULES:
        names = _imports(LANE / f"{module}.py")
        assert "evaluation.reviewer.host" not in names, module
        assert not names & {"subprocess", "shutil", "tempfile"}, (module, names)


def test_reviewer_cross_lane_dependency_is_only_deterministic_result_reading():
    cross_lane: dict[str, set[str]] = {}
    for path in LANE.glob("*.py"):
        if dotenv_part(path.name):
            continue
        imports = {
            name
            for name in _imports(path)
            if name.startswith("evaluation.")
            and not name.startswith(
                ("evaluation.reviewer", "evaluation.harness")
            )
        }
        if imports:
            cross_lane[path.name] = imports
    assert cross_lane == {
        "packet.py": {"evaluation.deterministic.results"},
    }


def test_default_verification_spawns_nothing_and_reads_no_user_state(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("offline reviewer verification must not do this")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr("shutil.which", forbidden)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: forbidden()))

    assert results.verify_results(DEFAULT_REVIEW_RESULTS, DEFAULT_PACKET) == []


def test_offline_cli_never_loads_the_live_host_module():
    code = (
        "import sys; from evaluation.reviewer.cli import main; "
        "status = main(['--verify-results', "
        "'evaluation/reviewer-results.json']); "
        "raise SystemExit(status or "
        "int('evaluation.reviewer.host' in sys.modules))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr


def test_entry_wrapper_is_thin_and_owns_no_reviewer_logic():
    wrapper = ROOT / "evaluation" / "review.py"
    assert len(wrapper.read_text(encoding="utf-8").splitlines()) <= 25
    assert _imports(wrapper) == {
        "__future__",
        "sys",
        "pathlib",
        "evaluation.reviewer.cli",
    }
