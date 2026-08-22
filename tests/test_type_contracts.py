"""Exported production functions carry parameterized container types.

The static gate (``mypy`` with ``disallow_any_generics``) already rejects a
bare ``dict`` in a checked definition; this source check keeps the rule
visible and independent of the checker's configuration: a new exported
function or method may not annotate a parameter or return value with an
unparameterized ``dict``/``list``/``set``/``tuple``/``Mapping`` (or the other
abstract containers below). Private helpers (``_name``) are left to mypy.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "glossabet"

BARE_CONTAINERS = {
    "dict", "list", "set", "frozenset", "tuple", "Counter", "defaultdict",
    "Mapping", "MutableMapping", "Sequence", "MutableSequence", "Iterable",
    "Iterator", "Collection", "Set", "Callable",
}


def _bare_container_names(annotation: ast.expr | None) -> list[str]:
    """Container names used without ``[...]`` anywhere in ``annotation``."""
    if annotation is None:
        return []
    found: list[str] = []
    subscripted: set[int] = set()
    for node in ast.walk(annotation):
        if isinstance(node, ast.Subscript):
            subscripted.add(id(node.value))
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name) and node.id in BARE_CONTAINERS:
            if id(node) not in subscripted:
                found.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in BARE_CONTAINERS:
            if id(node) not in subscripted:
                found.append(node.attr)
    return found


def _exported_functions(tree: ast.Module):
    """Top-level public functions and public methods of public classes."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                yield node.name, node
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not item.name.startswith("_") or item.name == "__init__":
                        yield f"{node.name}.{item.name}", item


def test_exported_functions_have_no_bare_container_annotations():
    offenders: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name, function in _exported_functions(tree):
            annotations = [
                *(arg.annotation for arg in function.args.args),
                *(arg.annotation for arg in function.args.kwonlyargs),
                *(arg.annotation for arg in function.args.posonlyargs),
                function.args.vararg.annotation if function.args.vararg else None,
                function.args.kwarg.annotation if function.args.kwarg else None,
                function.returns,
            ]
            bare = [
                container
                for annotation in annotations
                for container in _bare_container_names(annotation)
            ]
            if bare:
                rel = path.relative_to(PACKAGE.parent)
                offenders.append(f"{rel}:{function.lineno} {name}: {sorted(set(bare))}")
    assert offenders == [], "\n".join(offenders)


def test_source_check_recognizes_a_bare_container():
    tree = ast.parse("def f(a: dict, b: list[str]) -> Mapping:\n    return {}\n")
    names = dict(_exported_functions(tree))
    function = names["f"]
    assert _bare_container_names(function.args.args[0].annotation) == ["dict"]
    assert _bare_container_names(function.args.args[1].annotation) == []
    assert _bare_container_names(function.returns) == ["Mapping"]
