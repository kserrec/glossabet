"""The persistent glossary: glossabet-out/glossary.json.

Deliberately minimal schema: every field has a current consumer. The status
lifecycle exists because drift
detection is defined against it. A term is meant to be "canonical" only after
human approval — the engine validates and persists; it never promotes on its
own. That is the skill's instruction, not a mechanical guarantee: `save`
cannot verify that the agent piping to it really obtained approval. An
optional path-prefix scope lets a term have different owners in disjoint
subsystems; an omitted scope retains the original repository-wide meaning.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from glossabet.glossary.model import (
    BINDING_KINDS,
    GLOSSARY_SCHEMA_VERSION,
    SCOPE_PATHS_KEY,
    STATUSES,
    ConceptRecord,
    GlossaryDocument,
)
from glossabet.glossary.schema import checked_glossary, validate_glossary
from glossabet.glossary.scope import (
    canonical_scope_path,
    concept_scope,
    path_in_scope,
    scope_evidence,
    scopes_overlap,
)
from glossabet.runtime.artifacts import (
    OUT_DIR,
    READ_ABSENT,
    READ_OVERSIZED,
    ArtifactError,
    confined_artifact_path,
    read_bounded_json,
    write_artifact,
)

GLOSSARY_FILE = "glossary.json"

# Compatibility boundary: callers may import these exact aliases from the
# store facade. Internal code and new non-persistence concepts import their
# owners in ``model``, ``schema``, and ``scope`` instead of extending this list.
__all__ = [
    "BINDING_KINDS", "GLOSSARY_FILE", "GLOSSARY_SCHEMA_VERSION",
    "SCOPE_PATHS_KEY", "STATUSES", "GlossaryError", "checked_glossary",
    "concept_scope", "glossary_sha256", "load_glossary", "path_in_scope",
    "save_glossary", "scope_evidence", "scopes_overlap", "validate_glossary",
]


class GlossaryError(ValueError):
    """The glossary file exists but is not usable as written."""


def _canonicalize_scope_paths(
    glossary: GlossaryDocument, *, sort_concepts: bool,
) -> GlossaryDocument:
    """Copy persisted scope paths into their deterministic NFC form."""
    concepts: list[ConceptRecord] = []
    for original in glossary["concepts"]:
        concept = original.copy()
        scope = concept.get("scope")
        if scope is not None:
            concept["scope"] = {
                SCOPE_PATHS_KEY: sorted(
                    canonical_scope_path(prefix)
                    for prefix in scope[SCOPE_PATHS_KEY]
                )
            }
        concepts.append(concept)
    if sort_concepts:
        concepts.sort(key=lambda concept: concept["id"])
    return {
        "schema_version": glossary["schema_version"],
        "concepts": concepts,
    }


def glossary_sha256(glossary: GlossaryDocument) -> str:
    """Return the semantic digest used to bind every vocabulary projection."""
    canonical = json.dumps(
        _canonicalize_scope_paths(glossary, sort_concepts=False),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_glossary(root: Path) -> GlossaryDocument | None:
    """Return the validated glossary, None if absent, GlossaryError if bad."""
    try:
        path = confined_artifact_path(root, f"{OUT_DIR}/{GLOSSARY_FILE}")
    except ArtifactError as exc:
        raise GlossaryError(str(exc)) from exc
    read = read_bounded_json(path)
    if read.status == READ_ABSENT:
        return None
    if read.status == READ_OVERSIZED:
        raise GlossaryError(
            f"{path}: larger than {read.cap} bytes — refusing to load"
        )
    if not read.ok:
        raise GlossaryError(f"{path}: unreadable JSON ({read.error})")
    glossary, errors = checked_glossary(read.value)
    if glossary is None:
        raise GlossaryError(f"{path}: " + "; ".join(errors))
    return _canonicalize_scope_paths(glossary, sort_concepts=False)


def save_glossary(root: Path, document: object) -> Path:
    """Validate an untrusted JSON document and write it as the glossary."""
    glossary, errors = checked_glossary(document)
    if glossary is None:
        raise GlossaryError("refusing to save invalid glossary: "
                            + "; ".join(errors))
    normalized = _canonicalize_scope_paths(glossary, sort_concepts=True)
    return write_artifact(root, GLOSSARY_FILE, normalized)
