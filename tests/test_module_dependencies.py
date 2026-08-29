"""Selected dependency boundaries whose inversion would obscure ownership.

These tests protect a small set of load-bearing module relationships. They do
not prove that the entire package follows one global layer hierarchy or that
every possible dependency is architecturally desirable.
"""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "glossabet"

_MODULE_PATHS = {
    "glossabet." + ".".join(path.relative_to(PACKAGE).with_suffix("").parts): path
    for path in PACKAGE.rglob("*.py")
    if path.stem != "__init__"
    and "_skill" not in path.parts
    and not any(
        part == ".env"
        or part.endswith(".env")
        or part.startswith(".env.")
        or ".env." in part
        for part in path.relative_to(PACKAGE).parts
    )
}


def _imports_of(
    path: Path, *, package_parts: list[str] | None = None
) -> set[str]:
    """Return absolute import names, resolving package-relative imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    if package_parts is None:
        package_parts = [
            "glossabet", *path.relative_to(PACKAGE).parent.parts
        ]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            if not module:
                continue
            names.add(module)
            if module.startswith("glossabet"):
                names.update(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def _imports(module: str) -> set[str]:
    return _imports_of(_MODULE_PATHS[module])


def _names_imported_from(module: str, source: str) -> set[str]:
    """Return the names one product module imports from an exact module."""
    tree = ast.parse(_MODULE_PATHS[module].read_text(encoding="utf-8"))
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.level == 0
        and node.module == source
        for alias in node.names
    }


def _matches(name: str, target: str) -> bool:
    return name == target or name.startswith(target + ".")


def _forbidden_imports(module: str, forbidden: tuple[str, ...]) -> set[str]:
    return {
        name
        for name in _imports(module)
        if any(_matches(name, target) for target in forbidden)
    }


def test_duplicate_basenames_have_distinct_module_identities():
    assert _MODULE_PATHS["glossabet.analysis.policy"] == (
        PACKAGE / "analysis" / "policy.py"
    )
    assert _MODULE_PATHS["glossabet.glossary.policy"] == (
        PACKAGE / "glossary" / "policy.py"
    )
    assert (
        _MODULE_PATHS["glossabet.analysis.policy"]
        != _MODULE_PATHS["glossabet.glossary.policy"]
    )


def test_runtime_is_an_infrastructure_boundary():
    runtime_modules = sorted(
        name for name in _MODULE_PATHS if name.startswith("glossabet.runtime.")
    )
    for module in runtime_modules:
        outside_runtime = {
            name
            for name in _imports(module)
            if name.startswith("glossabet.")
            and not name.startswith("glossabet.runtime.")
        }
        assert not outside_runtime, f"{module} imports {sorted(outside_runtime)}"


def test_shared_managed_block_format_imports_no_package_feature():
    package_imports = {
        name
        for name in _imports("glossabet.managed_block")
        if name.startswith("glossabet.")
    }
    assert package_imports == set()


def test_aggregation_and_read_boundaries_do_not_import_their_callers():
    rules = {
        "glossabet.analysis.evidence": (
            "glossabet.agent.context_sync",
            "glossabet.agent.brief",
            "glossabet.cli",
            "glossabet.analysis.evidence_report",
        ),
        "glossabet.corpus.extraction": (
            "glossabet.analysis.evidence",
            "glossabet.corpus.scanner",
        ),
        "glossabet.agent.brief": (
            "glossabet.analysis.evidence",
            "glossabet.corpus.scanner",
        ),
        "glossabet.corpus.scanner": (
            "glossabet.glossary.repository_glossary",
            "glossabet.analysis.evidence",
        ),
    }
    for module, forbidden in rules.items():
        found = _forbidden_imports(module, forbidden)
        assert not found, f"{module} imports {sorted(found)}"


def test_graphify_and_validation_ownership_directions():
    rules = {
        "glossabet.analysis.graphify_input": (
            "glossabet.analysis.graphify",
            "glossabet.analysis.graphify_groups",
        ),
        "glossabet.analysis.graphify_groups": (
            "glossabet.analysis.graphify",
        ),
        "glossabet.glossary.binding_validation": (
            "glossabet.glossary.structural_validation",
            "glossabet.glossary.reconcile",
        ),
        "glossabet.glossary.structural_validation": (
            "glossabet.glossary.reconcile",
        ),
    }
    for module, forbidden in rules.items():
        found = _forbidden_imports(module, forbidden)
        assert not found, f"{module} imports {sorted(found)}"


def test_glossary_model_imports_nothing_from_the_package():
    """The persisted glossary schema stays a leaf to avoid dependency cycles."""
    package_imports = {
        name
        for name in _imports("glossabet.glossary.model")
        if name.startswith("glossabet.")
    }
    assert package_imports == set()


def test_glossary_internal_imports_name_the_conceptual_owner():
    """The store's historical facade is compatibility, not ownership."""
    compatibility_exports = {
        "BINDING_KINDS",
        "GLOSSARY_SCHEMA_VERSION",
        "SCOPE_PATHS_KEY",
        "STATUSES",
        "checked_glossary",
        "concept_scope",
        "path_in_scope",
        "scope_evidence",
        "scopes_overlap",
        "validate_glossary",
    }
    offenders = {
        module: sorted(imported)
        for module in sorted(_MODULE_PATHS)
        if module != "glossabet.glossary.store"
        and (
            imported := _names_imported_from(
                module, "glossabet.glossary.store"
            ) & compatibility_exports
        )
    }
    assert not offenders, offenders


def test_glossary_owner_core_dependencies_follow_acyclic_order():
    """The conceptual owners may depend only on owners below them."""
    order = {
        "glossabet.glossary.model": 0,
        "glossabet.glossary.scope": 1,
        "glossabet.glossary.schema": 2,
        "glossabet.glossary.store": 3,
    }
    for module, rank in order.items():
        backward = {
            imported
            for imported in _imports(module)
            if imported in order and order[imported] >= rank
        }
        assert not backward, f"{module} imports {sorted(backward)}"


def test_agent_context_protocol_is_projection_independent():
    """Versioned shape is lower than projection mechanics and commands."""
    protocol = "glossabet.agent.agent_context_protocol"
    projection = "glossabet.agent.agent_context"

    assert protocol in _MODULE_PATHS
    assert protocol in _imports(projection)
    forbidden = _forbidden_imports(
        protocol,
        (projection, "glossabet.cli", "glossabet.command_run"),
    )
    assert not forbidden, f"{protocol} imports {sorted(forbidden)}"


def test_runtime_boundary_rule_detects_a_domain_import(tmp_path):
    """A focused mutation proves the runtime boundary sees violations."""
    module = tmp_path / "probe.py"
    module.write_text(
        "from glossabet.glossary.store import load_glossary\n",
        encoding="utf-8",
    )
    imports = _imports_of(
        module,
        package_parts=["glossabet", "runtime"],
    )
    outside_runtime = {
        name
        for name in imports
        if name.startswith("glossabet.")
        and not name.startswith("glossabet.runtime.")
    }
    assert "glossabet.glossary.store" in outside_runtime
