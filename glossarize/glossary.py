"""The persistent glossary: glossarize-out/glossary.json.

Deliberately minimal schema (PLAN.md: the ontology grows only when a consumer
needs a field). The status lifecycle exists from day one because drift
detection is defined against it. Only a human-approved term is ever
"canonical" — the engine validates and persists; it never promotes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GLOSSARY_SCHEMA_VERSION = 1
GLOSSARY_FILE = "glossary.json"
OUT_DIR = "glossarize-out"

STATUSES = frozenset(
    {"canonical", "proposed", "alias", "discouraged", "deprecated", "unknown"}
)
# Bindings target stable identities only (PLAN principle 7): never graph
# community numbers or node ids, which shift across rebuilds.
BINDING_KINDS = frozenset({"symbol", "file", "module"})
_REQUIRED_CONCEPT_KEYS = ("id", "term", "definition", "status")


class GlossaryError(ValueError):
    """The glossary file exists but is not usable as written."""


def validate_glossary(glossary: dict) -> list[str]:
    errors: list[str] = []
    if glossary.get("schema_version") != GLOSSARY_SCHEMA_VERSION:
        errors.append(
            f"schema_version must be {GLOSSARY_SCHEMA_VERSION}, "
            f"got {glossary.get('schema_version')!r}"
        )
    concepts = glossary.get("concepts")
    if not isinstance(concepts, list):
        errors.append("concepts must be a list")
        return errors
    seen_ids: set[str] = set()
    seen_terms: set[str] = set()
    for i, concept in enumerate(concepts):
        where = f"concepts[{i}]"
        if not isinstance(concept, dict):
            errors.append(f"{where} must be an object")
            continue
        for key in _REQUIRED_CONCEPT_KEYS:
            if not isinstance(concept.get(key), str) or not concept.get(key):
                errors.append(f"{where} needs a non-empty string {key!r}")
        status = concept.get("status")
        if status is not None and status not in STATUSES:
            errors.append(
                f"{where} status {status!r} not one of {sorted(STATUSES)}"
            )
        cid = concept.get("id")
        if isinstance(cid, str):
            if cid in seen_ids:
                errors.append(f"{where} duplicate id {cid!r}")
            seen_ids.add(cid)
        term = concept.get("term")
        if isinstance(term, str):
            folded = term.casefold()
            if folded in seen_terms:
                errors.append(f"{where} duplicate term {term!r}")
            seen_terms.add(folded)
        for j, alias in enumerate(concept.get("aliases", [])):
            aw = f"{where}.aliases[{j}]"
            if not isinstance(alias, dict) or not alias.get("term"):
                errors.append(f"{aw} needs a 'term'")
                continue
            if alias.get("status") not in STATUSES:
                errors.append(
                    f"{aw} status {alias.get('status')!r} not one of "
                    f"{sorted(STATUSES)}"
                )
        for j, binding in enumerate(concept.get("bindings", [])):
            bw = f"{where}.bindings[{j}]"
            ref = binding.get("ref") if isinstance(binding, dict) else None
            if not isinstance(ref, str) or ":" not in ref:
                errors.append(f"{bw} needs a 'ref' like 'symbol:Name'")
                continue
            kind = ref.split(":", 1)[0]
            if kind not in BINDING_KINDS:
                errors.append(
                    f"{bw} unsupported ref kind {kind!r} — bindings target "
                    f"stable identities only ({sorted(BINDING_KINDS)}); "
                    "community/node ids are not stable across graph rebuilds"
                )
    return errors


def glossary_path(root: Path) -> Path:
    return root / OUT_DIR / GLOSSARY_FILE


def load_glossary(root: Path) -> dict | None:
    """Return the validated glossary, None if absent, GlossaryError if bad."""
    path = glossary_path(root)
    if not path.is_file():
        return None
    try:
        glossary = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise GlossaryError(f"{path}: unreadable JSON ({exc})") from exc
    errors = validate_glossary(glossary)
    if errors:
        raise GlossaryError(f"{path}: " + "; ".join(errors))
    return glossary


def save_glossary(root: Path, glossary: dict) -> Path:
    errors = validate_glossary(glossary)
    if errors:
        raise GlossaryError("refusing to save invalid glossary: "
                            + "; ".join(errors))
    out = root / OUT_DIR
    out.mkdir(exist_ok=True)
    path = out / GLOSSARY_FILE
    glossary = dict(glossary)
    glossary["concepts"] = sorted(glossary["concepts"], key=lambda c: c["id"])
    path.write_text(json.dumps(glossary, indent=2, sort_keys=True) + "\n")
    return path


def show_command(path_arg: str) -> int:
    root = Path(path_arg)
    if not root.is_dir():
        print(f"glossarize: not a directory: {path_arg}", file=sys.stderr)
        return 1
    try:
        glossary = load_glossary(root.resolve())
    except GlossaryError as exc:
        print(f"glossarize: {exc}", file=sys.stderr)
        return 1
    if glossary is None:
        print(
            "no glossary yet — run /glossarize and settle terms to create "
            f"{OUT_DIR}/{GLOSSARY_FILE}"
        )
        return 0

    concepts = sorted(glossary["concepts"], key=lambda c: c["id"])
    by_status: dict[str, list[dict]] = {}
    for concept in concepts:
        by_status.setdefault(concept["status"], []).append(concept)
    counts = ", ".join(
        f"{len(v)} {k}" for k, v in sorted(by_status.items())
    )
    print(f"glossary: {counts}")
    for status in ("canonical", "proposed", "deprecated", "discouraged",
                   "alias", "unknown"):
        group = by_status.get(status)
        if not group:
            continue
        print(f"\n== {status} ==")
        for concept in group:
            print(f"{concept['term']} — {concept['definition']}")
            for alias in concept.get("aliases", []):
                note = f" ({alias['note']})" if alias.get("note") else ""
                print(f"    alias: {alias['term']} [{alias['status']}]{note}")
            if concept.get("notes"):
                print(f"    note: {concept['notes']}")
    return 0
