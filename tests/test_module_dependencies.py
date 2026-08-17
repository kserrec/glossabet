"""Dependency directions the architecture relies on (Phase 35.4).

`evidence` is the aggregation hub and must not import a command module;
`brief` loads no source files and must not drag the scanner in; the managed
block lives beneath both its users; the scanner never depends on the
discovery channel that depends on it."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "glossabet"


def _imports(module: str) -> set[str]:
    tree = ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            if node.module == "glossabet":
                names.update(f"glossabet.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_forbidden_dependency_directions():
    forbidden = {
        "evidence": {"glossabet.context_sync", "glossabet.brief", "glossabet.cli"},
        "brief": {"glossabet.evidence", "glossabet.scanner"},
        "managed_block": {"glossabet.context_sync", "glossabet.evidence"},
        "scanner": {"glossabet.repository_glossary", "glossabet.evidence"},
        "git_state": {"glossabet.evidence", "glossabet.brief"},
    }
    for module, banned in forbidden.items():
        found = _imports(module) & banned
        assert not found, f"{module} imports {sorted(found)}"
