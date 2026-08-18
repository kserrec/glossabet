"""Document key spellings live in one module per document (Phase 36.3).

RepositoryEvidence, drift, validation, and AgentContext stay plain dicts
(they round-trip as JSON), so nothing stops a consumer from spelling a key
and getting a ``KeyError`` in a branch no test reaches. This test is the
ratchet: outside the module that writes a document and the view that reads
it, no engine module (nor the evaluation runner) may subscript one of these
documents by a string key or ``.get`` a key from it. Add a view method
instead."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "glossabet").rglob("*.py")) + [
    ROOT / "evaluation" / "run.py"
]

# document variable name -> modules allowed to spell its keys
OWNERS = {
    "evidence": {"evidence_view"},          # `evidence.py` builds a literal
    "cold_evidence": set(),
    "drift": {"drift"},
    "validation": {"reconcile"},
    "context": {"agent_context"},
}


def _spelled_keys(tree: ast.AST, name: str) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == name
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            found.append(node.slice.value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == name
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            found.append(node.args[0].value)
    return found


def test_document_keys_are_spelled_only_by_their_owners():
    offenders = []
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = path.stem
        for name, owners in OWNERS.items():
            if module in owners:
                continue
            for key in _spelled_keys(tree, name):
                offenders.append(f"{path.relative_to(ROOT)}: {name}[{key!r}]")
    assert not offenders, "\n".join(offenders)


def test_views_cover_every_top_level_evidence_key(tmp_path):
    # Every key the writer emits has a view method, so a consumer never has
    # a reason to fall back to spelling one.
    from glossabet.analysis.evidence import build_evidence
    from glossabet.analysis.evidence_view import EvidenceView

    (tmp_path / "a.py").write_text("payment_id = 1\n")
    evidence = build_evidence(tmp_path)
    view = EvidenceView(evidence)
    reachable = {
        "schema_version": view.schema_version(),
        "generator": view.generator(),
        "repository": view.repository(),
        "configuration": view.configuration(),
        "totals": view.totals(),
        "languages": view.languages(),
        "modules": view.modules(),
        "imports": view.imports(),
        "naming_candidates": view.naming_candidates(),
        "structural_groups": view.structural_groups(),
        "files": view.files(),
        "vocabulary": view.vocabulary(),
        "terminology": view.terminology(),
        "monorepo": view.monorepo(),
        "skipped": view.skipped(),
    }
    assert set(reachable) == set(evidence)
    for key, value in reachable.items():
        assert value is evidence[key]
