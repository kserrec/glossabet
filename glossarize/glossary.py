"""The persistent glossary: glossarize-out/glossary.json.

Deliberately minimal schema (PLAN.md: the ontology grows only when a consumer
needs a field). The status lifecycle exists from day one because drift
detection is defined against it. Only a human-approved term is ever
"canonical" — the engine validates and persists; it never promotes. An
optional path-prefix scope lets a term have different owners in disjoint
subsystems; an omitted scope retains the original repository-wide meaning.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from glossarize.artifacts import (
    ArtifactError,
    MAX_JSON_BYTES,
    OUT_DIR,
    confined_artifact_path,
    oversized,
    repo_root,
    write_artifact,
)

GLOSSARY_SCHEMA_VERSION = 1
GLOSSARY_FILE = "glossary.json"

STATUSES = frozenset(
    {"canonical", "proposed", "alias", "discouraged", "deprecated", "unknown"}
)
# Bindings target stable identities only (PLAN principle 7): never graph
# community numbers or node ids, which shift across rebuilds.
BINDING_KINDS = frozenset({"symbol", "file", "module"})
_REQUIRED_CONCEPT_KEYS = ("id", "term", "definition", "status")
SCOPE_PATHS_KEY = "path_prefixes"


class GlossaryError(ValueError):
    """The glossary file exists but is not usable as written."""


def _fold_vocabulary(term: str) -> str:
    return unicodedata.normalize("NFKC", term.strip()).casefold()


def _scope_from_raw(raw: object, where: str, errors: list[str]) -> tuple[str, ...] | None:
    """Validate and normalize one concept scope; ``None`` means repository-wide."""
    if raw is None:
        errors.append(f"{where}.scope must be an object; omit it for repository-wide")
        return None
    if not isinstance(raw, dict):
        errors.append(f"{where}.scope must be an object")
        return None
    unknown = sorted(set(raw) - {SCOPE_PATHS_KEY})
    if unknown:
        errors.append(f"{where}.scope has unknown field(s): {', '.join(unknown)}")
    prefixes = raw.get(SCOPE_PATHS_KEY)
    if not isinstance(prefixes, list) or not prefixes:
        errors.append(f"{where}.scope.{SCOPE_PATHS_KEY} must be a non-empty list")
        return None
    valid: list[str] = []
    for index, prefix in enumerate(prefixes):
        path_where = f"{where}.scope.{SCOPE_PATHS_KEY}[{index}]"
        if not isinstance(prefix, str) or not prefix:
            errors.append(f"{path_where} must be a non-empty string")
            continue
        parts = prefix.split("/")
        if (
            prefix != prefix.strip()
            or prefix.startswith("/")
            or "\\" in prefix
            or "\0" in prefix
            or any(part in ("", ".", "..") for part in parts)
            or any(char in prefix for char in "*?[]")
        ):
            errors.append(
                f"{path_where} must be a literal repository-relative path prefix"
            )
            continue
        valid.append(prefix)
    if len(set(valid)) != len(valid):
        errors.append(f"{where}.scope.{SCOPE_PATHS_KEY} contains duplicate paths")
    return tuple(sorted(set(valid))) if valid else None


def concept_scope(concept: dict) -> tuple[str, ...] | None:
    """Return a validated concept's normalized prefixes, or None for global."""
    raw = concept.get("scope")
    if raw is None:
        return None
    prefixes = raw.get(SCOPE_PATHS_KEY, []) if isinstance(raw, dict) else []
    return tuple(sorted(prefixes)) if prefixes else None


def path_in_scope(path: str, scope: tuple[str, ...] | None) -> bool:
    """Whether a repository-relative file/module path falls inside scope."""
    return scope is None or any(
        path == prefix or path.startswith(prefix + "/") for prefix in scope
    )


def scopes_overlap(
    left: tuple[str, ...] | None, right: tuple[str, ...] | None
) -> bool:
    """Repository-wide overlaps everything; path scopes overlap by ancestry."""
    if left is None or right is None:
        return True
    return any(
        a == b or a.startswith(b + "/") or b.startswith(a + "/")
        for a in left
        for b in right
    )


def scope_evidence(scope: tuple[str, ...] | None) -> dict:
    """Stable serialized scope metadata used by drift and validation reports."""
    if scope is None:
        return {"kind": "repository"}
    return {"kind": "path-prefixes", SCOPE_PATHS_KEY: list(scope)}


def validate_glossary(glossary: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(glossary, dict):
        return ["top level must be an object"]
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
    vocabulary_owners: dict[
        str, list[tuple[int, str, str, tuple[str, ...] | None]]
    ] = defaultdict(list)
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
        scope = (
            _scope_from_raw(concept["scope"], where, errors)
            if "scope" in concept else None
        )
        cid = concept.get("id")
        if isinstance(cid, str):
            if cid in seen_ids:
                errors.append(f"{where} duplicate id {cid!r}")
            seen_ids.add(cid)
        term = concept.get("term")
        if isinstance(term, str):
            folded = _fold_vocabulary(term)
            for previous in vocabulary_owners[folded]:
                if previous[0] != i and scopes_overlap(previous[3], scope):
                    if previous[2] == "term":
                        errors.append(
                            f"{where} duplicate term {term!r} in overlapping "
                            f"scopes ({previous[1]!r} and {cid!r})"
                        )
                    else:
                        errors.append(
                            f"{where} term {term!r} maps to multiple concepts "
                            f"in overlapping scopes ({previous[1]!r} and {cid!r})"
                        )
            vocabulary_owners[folded].append((i, str(cid), "term", scope))
        aliases = concept.get("aliases", [])
        if not isinstance(aliases, list):
            errors.append(f"{where}.aliases must be a list")
            aliases = []
        for j, alias in enumerate(aliases):
            aw = f"{where}.aliases[{j}]"
            alias_term = alias.get("term") if isinstance(alias, dict) else None
            if (
                not isinstance(alias_term, str)
                or not alias_term.strip()
            ):
                errors.append(f"{aw} needs a 'term'")
                continue
            if alias.get("status") not in STATUSES:
                errors.append(
                    f"{aw} status {alias.get('status')!r} not one of "
                    f"{sorted(STATUSES)}"
                )
            folded_alias = _fold_vocabulary(alias_term)
            conflicting = [
                owner for owner in vocabulary_owners[folded_alias]
                if owner[0] == i or scopes_overlap(owner[3], scope)
            ]
            if conflicting:
                previous = conflicting[0]
                if previous[0] != i:
                    errors.append(
                        f"{aw} alias term {alias_term!r} maps to multiple "
                        f"concepts in overlapping scopes "
                        f"({previous[1]!r} and {cid!r})"
                    )
                else:
                    errors.append(
                        f"{aw} duplicate vocabulary term {alias_term!r} "
                        f"within concept {cid!r}"
                    )
            vocabulary_owners[folded_alias].append(
                (i, str(cid), "alias", scope)
            )
        bindings = concept.get("bindings", [])
        if not isinstance(bindings, list):
            errors.append(f"{where}.bindings must be a list")
            bindings = []
        for j, binding in enumerate(bindings):
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
    try:
        path = confined_artifact_path(root, f"{OUT_DIR}/{GLOSSARY_FILE}")
    except ArtifactError as exc:
        raise GlossaryError(str(exc)) from exc
    if not path.is_file():
        return None
    if oversized(path):
        raise GlossaryError(
            f"{path}: larger than {MAX_JSON_BYTES} bytes — refusing to load"
        )
    try:
        glossary = json.loads(path.read_text())
    except (OSError, ValueError, RecursionError) as exc:
        # RecursionError: deeply nested JSON, raised outside the ValueError
        # hierarchy — a hostile glossary must fail cleanly, not crash.
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
    glossary = dict(glossary)
    concepts = []
    for original in glossary["concepts"]:
        concept = dict(original)
        scope = concept.get("scope")
        if isinstance(scope, dict):
            concept["scope"] = {
                SCOPE_PATHS_KEY: sorted(scope[SCOPE_PATHS_KEY])
            }
        concepts.append(concept)
    glossary["concepts"] = sorted(concepts, key=lambda c: c["id"])
    return write_artifact(root, GLOSSARY_FILE, glossary)


def require_glossary(root: Path, missing: str) -> dict | None:
    """Loaded glossary, or None after reporting why there is nothing usable.

    `missing` is the leading clause for the no-glossary-yet message, e.g.
    "no glossary to validate".
    """
    try:
        glossary = load_glossary(root)
    except GlossaryError as exc:
        print(f"glossarize: {exc}", file=sys.stderr)
        return None
    if glossary is None:
        print(
            f"glossarize: {missing} — run /glossarize and settle terms "
            f"first ({OUT_DIR}/{GLOSSARY_FILE})",
            file=sys.stderr,
        )
        return None
    return glossary


def show_command(path_arg: str) -> int:
    root = repo_root(path_arg)
    if root is None:
        return 1
    try:
        glossary = load_glossary(root)
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
            scope = concept_scope(concept)
            if scope is not None:
                print(f"    scope: {', '.join(scope)}")
            for alias in concept.get("aliases", []):
                note = f" ({alias['note']})" if alias.get("note") else ""
                print(f"    alias: {alias['term']} [{alias['status']}]{note}")
            if concept.get("notes"):
                print(f"    note: {concept['notes']}")
    return 0
