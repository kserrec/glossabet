"""Evaluator-code identity: one digest per evaluation lane covering every
Python source file that governs that lane's judgments.

A recorded result binds itself to the evaluator that produced it. Hashing
only the thin entry wrapper would leave imported implementation free to
change without changing the recorded identity, so the identity covers:

1. the lane's entry wrapper;
2. every module under the lane's package (``evaluation/<lane>/``);
3. every ``evaluation.harness`` module those files import, transitively.

Production ``glossabet`` code and other lanes are deliberately excluded —
they have their own identities where they matter. Paths are hashed together
with their bytes in sorted repository-relative order with length-prefixed
framing (see ``framed_digest``).
"""

from __future__ import annotations

import ast
from pathlib import Path

from evaluation.harness.io import dotenv_part, framed_digest

ROOT = Path(__file__).resolve().parents[2]
HARNESS_PACKAGE = "evaluation.harness"

LANE_WRAPPERS: dict[str, str] = {
    "codex": "scripts/agent_eval.py",
    "claude": "scripts/claude_eval.py",
    "deterministic": "evaluation/run.py",
    "reviewer": "evaluation/review.py",
}


def _module_path(root: Path, module: str) -> Path | None:
    """Repository path of an ``evaluation.*`` module, or None if absent."""
    candidate = root / Path(*module.split("."))
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    if (candidate / "__init__.py").is_file():
        return candidate / "__init__.py"
    return None


def _imported_modules(path: Path) -> set[str]:
    """Absolute names of every module imported by ``path``."""
    tree = ast.parse(path.read_bytes(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _lane_package_files(root: Path, lane: str) -> list[Path]:
    package = root / "evaluation" / lane
    if not package.is_dir():
        return []
    return sorted(
        path
        for path in package.rglob("*.py")
        if "__pycache__" not in path.parts
        and not any(dotenv_part(part) for part in path.relative_to(root).parts)
    )


def lane_source_paths(lane: str, *, root: Path = ROOT) -> list[str]:
    """Sorted repository-relative paths governing ``lane``."""
    if lane not in LANE_WRAPPERS:
        raise ValueError(f"unknown evaluation lane: {lane}")
    governing: set[Path] = {root / LANE_WRAPPERS[lane]}
    governing.update(_lane_package_files(root, lane))
    pending = list(governing)
    while pending:
        for module in _imported_modules(pending.pop()):
            if module != HARNESS_PACKAGE and not module.startswith(
                HARNESS_PACKAGE + "."
            ):
                continue
            path = _module_path(root, module)
            if path is not None and path not in governing:
                governing.add(path)
                pending.append(path)
    return sorted(path.relative_to(root).as_posix() for path in governing)


def lane_source_identity(lane: str, *, root: Path = ROOT) -> str:
    """Deterministic digest of the source that governs ``lane``."""
    paths = lane_source_paths(lane, root=root)
    return framed_digest((path, (root / path).read_bytes()) for path in paths)
