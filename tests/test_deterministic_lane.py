"""Boundaries of the deterministic evaluation lane."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "evaluation" / "deterministic"


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_scoring_is_pure():
    """Every scoring family judges documents it is handed: no process, no
    filesystem, no network, no other lane."""
    names = _imports(LANE / "scoring.py")
    assert not names & {"subprocess", "os", "shutil", "tempfile", "pathlib", "urllib"}
    assert not any(
        name.startswith("evaluation.") and not name.startswith("evaluation.deterministic")
        for name in names
    ), names


def test_contract_imports_no_lane_module():
    names = _imports(LANE / "contract.py")
    assert not any(name.startswith(("evaluation.", "scripts")) for name in names), names


def test_sources_spawn_only_git_under_the_safe_configuration():
    """The one process the sources module may start is ``git``, and every
    invocation carries the code-execution-neutralizing configuration."""
    tree = ast.parse((LANE / "sources.py").read_text(encoding="utf-8"))
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
    argv = ast.unparse(spawned[0].args[0])
    assert argv.startswith("['git', *GIT_SAFE_CONFIG"), argv
