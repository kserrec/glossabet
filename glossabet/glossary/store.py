"""The persistent glossary: glossabet-out/glossary.json.

Deliberately minimal schema (PLAN.md: the ontology grows only when a consumer
needs a field). The status lifecycle exists from day one because drift
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
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import cast

from glossabet.corpus.tokenize import term_words
from glossabet.glossary.model import (
    BINDING_KINDS,
    GLOSSARY_SCHEMA_VERSION,
    SCOPE_PATHS_KEY,
    STATUSES,
    ConceptRecord,
    ConceptScope,
    GlossaryDocument,
    PathPrefixScopeEvidence,
    RepositoryScopeEvidence,
    ScopeEvidence,
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
from glossabet.runtime.display import first_terminal_control

GLOSSARY_FILE = "glossary.json"

# The schema itself (statuses, binding kinds, scope key, record shapes) is
# owned by ``glossary.model``; the names above are re-exported here for the
# callers that address the glossary through its store.
__all__ = [
    "BINDING_KINDS", "GLOSSARY_FILE", "GLOSSARY_SCHEMA_VERSION",
    "SCOPE_PATHS_KEY", "STATUSES", "GlossaryError", "checked_glossary",
    "concept_scope", "glossary_sha256", "load_glossary", "path_in_scope",
    "save_glossary", "scope_evidence", "scopes_overlap", "validate_glossary",
]
_REQUIRED_CONCEPT_KEYS = ("id", "term", "definition", "status")

_TOP_LEVEL_KEYS = frozenset({"schema_version", "concepts"})
_CONCEPT_KEYS = frozenset(
    {
        "id", "term", "definition", "status", "scope", "aliases",
        "bindings", "notes",
    }
)
_ALIAS_KEYS = frozenset({"term", "status", "note"})
_BINDING_KEYS = frozenset({"ref"})

# JSON bytes are bounded before parsing, but validation also needs semantic
# limits: a compact hostile document can otherwise create quadratic owner
# comparisons or an enormous diagnostic. These are accepted-input ceilings,
# not targets for a useful human glossary.
MAX_GLOSSARY_CONCEPTS = 10_000
MAX_GLOSSARY_ALIASES = 50_000
MAX_GLOSSARY_BINDINGS = 50_000
MAX_GLOSSARY_SCOPE_PREFIXES = 50_000
MAX_GLOSSARY_SCOPE_CHARACTERS = 1_000_000
MAX_GLOSSARY_OWNERSHIP_SCOPE_CHARACTERS = 5_000_000
MAX_GLOSSARY_IDENTITY_CHARS = 1_024
MAX_GLOSSARY_PROSE_CHARS = 16_384
MAX_VALIDATION_ERRORS = 100


class GlossaryError(ValueError):
    """The glossary file exists but is not usable as written."""


def glossary_sha256(glossary: GlossaryDocument) -> str:
    """Return the semantic digest used to bind every vocabulary projection."""
    canonical = json.dumps(
        glossary,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _fold_vocabulary(term: str) -> str:
    """The identity a term or alias is owned by: its normalized word sequence
    (``Alpha Beta``, ``AlphaBeta``, and ``alpha_beta`` are one identity, since
    every consumer compares vocabulary by words), taken *before* the lexical
    keyword filter so ``Limit Function`` and ``Limit`` stay distinct terms.
    A term with no words falls back to its NFKC-casefolded string."""
    words = term_words(term)
    if words:
        return " ".join(words)
    return unicodedata.normalize("NFKC", term.strip()).casefold()


def _bounded_repr(value: object, limit: int = 160) -> str:
    if isinstance(value, str):
        if len(value) <= limit:
            return repr(value)
        return repr(value[:limit]) + "…"
    if isinstance(value, bytes):
        if len(value) <= limit:
            return repr(value)
        return repr(value[:limit]) + "…"
    if isinstance(value, (list, tuple, set, frozenset, dict)):
        return f"<{type(value).__name__} with {len(value)} item(s)>"
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    return f"<{type(value).__name__}>"


class _ValidationErrors:
    """Count every error while retaining a fixed-size useful prefix."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.total = 0

    def add(self, message: str) -> None:
        self.total += 1
        if len(self.messages) < MAX_VALIDATION_ERRORS - 1:
            self.messages.append(message)

    def finish(self) -> list[str]:
        omitted = self.total - len(self.messages)
        if omitted:
            self.messages.append(
                f"... {omitted} additional validation error(s) omitted"
            )
        return self.messages


def _unknown_fields(
    value: dict[object, object], allowed: frozenset[str], where: str,
    errors: _ValidationErrors,
) -> None:
    unknown_count = 0
    samples: list[object] = []
    for key in value:
        if isinstance(key, str) and key in allowed:
            continue
        unknown_count += 1
        if len(samples) < 10:
            samples.append(key)
    if unknown_count:
        rendered = ", ".join(
            sorted(_bounded_repr(key) for key in samples)
        )
        if unknown_count > len(samples):
            rendered += f", ... and {unknown_count - len(samples)} more"
        errors.add(f"{where} has unknown field(s): {rendered}")


def _string_field(
    value: object,
    where: str,
    errors: _ValidationErrors,
    *,
    required: bool,
    prose: bool = False,
) -> str | None:
    if not isinstance(value, str) or (required and not value.strip()):
        qualifier = "non-empty " if required else ""
        errors.add(f"{where} must be a {qualifier}string")
        return None
    limit = MAX_GLOSSARY_PROSE_CHARS if prose else MAX_GLOSSARY_IDENTITY_CHARS
    if len(value) > limit:
        errors.add(f"{where} exceeds {limit} characters")
        return None
    unsafe = first_terminal_control(value, allow_layout=prose)
    if unsafe is not None:
        # Terminal controls, bidirectional overrides, lone surrogates, and
        # invisible (default-ignorable) characters — named by code point so
        # the author can find it.
        errors.add(
            f"{where} contains a terminal control, bidirectional-format, or "
            f"invisible character (U+{ord(unsafe):04X})"
        )
        return None
    return value


def _scope_from_raw(
    raw: object, where: str, errors: _ValidationErrors,
) -> tuple[ConceptScope, bool]:
    """Validate and normalize one concept scope; ``None`` means repository-wide."""
    if raw is None:
        errors.add(f"{where}.scope must be an object; omit it for repository-wide")
        return None, False
    if not isinstance(raw, dict):
        errors.add(f"{where}.scope must be an object")
        return None, False
    _unknown_fields(raw, frozenset({SCOPE_PATHS_KEY}), f"{where}.scope", errors)
    prefixes = raw.get(SCOPE_PATHS_KEY)
    if not isinstance(prefixes, list) or not prefixes:
        errors.add(f"{where}.scope.{SCOPE_PATHS_KEY} must be a non-empty list")
        return None, False
    valid: list[str] = []
    for index, prefix in enumerate(prefixes):
        path_where = f"{where}.scope.{SCOPE_PATHS_KEY}[{index}]"
        prefix = _string_field(prefix, path_where, errors, required=True)
        if prefix is None:
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
            errors.add(
                f"{path_where} must be a literal repository-relative path prefix"
            )
            continue
        valid.append(prefix)
    if len(set(valid)) != len(valid):
        errors.add(f"{where}.scope.{SCOPE_PATHS_KEY} contains duplicate paths")
    unique = set(valid)
    overlapping = False
    ancestry: list[str] = []
    # Component-wise order keeps every descendant directly after its
    # ancestor; plain string order would let ``src-old`` (``-`` sorts before
    # ``/``) sit between ``src`` and ``src/payments`` and hide the overlap.
    for prefix in sorted(unique, key=lambda path: path.split("/")):
        while ancestry and not prefix.startswith(ancestry[-1] + "/"):
            ancestry.pop()
        if ancestry:
            overlapping = True
            break
        ancestry.append(prefix)
    if overlapping:
        errors.add(
            f"{where}.scope.{SCOPE_PATHS_KEY} contains overlapping paths"
        )
    usable = bool(valid) and len(unique) == len(valid) and not overlapping
    return (tuple(sorted(unique)) if usable else None), usable


class _ScopeNode:
    __slots__ = ("children", "owner_here", "subtree_owner")

    def __init__(self) -> None:
        self.children: dict[str, _ScopeNode] = {}
        self.owner_here: tuple[int, str, str] | None = None
        self.subtree_owner: tuple[int, str, str] | None = None


class _ScopeOwnerIndex:
    """Find one overlapping vocabulary owner in path-prefix time.

    A repository-wide owner overlaps every path. Scoped owners live in a trie:
    overlap is either an owner on an ancestor node or any owner in the queried
    node's subtree. Validation therefore avoids comparing every concept with
    every earlier concept that uses the same word.
    """

    def __init__(self) -> None:
        self.global_owner: tuple[int, str, str] | None = None
        self.root = _ScopeNode()

    def conflict(self, scope: ConceptScope) -> tuple[int, str, str] | None:
        if self.global_owner is not None:
            return self.global_owner
        if scope is None:
            return self.root.subtree_owner
        for prefix in scope:
            node = self.root
            for part in prefix.split("/"):
                if node.owner_here is not None:
                    return node.owner_here
                child = node.children.get(part)
                if child is None:
                    break
                node = child
            else:
                if node.owner_here is not None:
                    return node.owner_here
                if node.subtree_owner is not None:
                    return node.subtree_owner
        return None

    def add(self, scope: ConceptScope, owner: tuple[int, str, str]) -> None:
        if scope is None:
            if self.global_owner is None:
                self.global_owner = owner
            return
        for prefix in scope:
            node = self.root
            if node.subtree_owner is None:
                node.subtree_owner = owner
            for part in prefix.split("/"):
                node = node.children.setdefault(part, _ScopeNode())
                if node.subtree_owner is None:
                    node.subtree_owner = owner
            if node.owner_here is None:
                node.owner_here = owner


def _within_aggregate_limits(
    concepts: list[object], errors: _ValidationErrors
) -> bool:
    starting_errors = errors.total
    if len(concepts) > MAX_GLOSSARY_CONCEPTS:
        errors.add(
            f"concepts exceeds the {MAX_GLOSSARY_CONCEPTS}-concept limit"
        )
        return False
    aliases = bindings = scope_prefixes = scope_characters = 0
    ownership_scope_characters = 0
    for concept in concepts:
        if not isinstance(concept, dict):
            continue
        raw_aliases = concept.get("aliases")
        raw_bindings = concept.get("bindings")
        raw_scope = concept.get("scope")
        if isinstance(raw_aliases, list):
            aliases += len(raw_aliases)
        if isinstance(raw_bindings, list):
            bindings += len(raw_bindings)
        if isinstance(raw_scope, dict):
            raw_prefixes = raw_scope.get(SCOPE_PATHS_KEY)
            if isinstance(raw_prefixes, list):
                scope_prefixes += len(raw_prefixes)
                concept_scope_characters = sum(
                    len(prefix) for prefix in raw_prefixes
                    if isinstance(prefix, str)
                )
                scope_characters += concept_scope_characters
                vocabulary_entries = 1 + (
                    len(raw_aliases) if isinstance(raw_aliases, list) else 0
                )
                ownership_scope_characters += (
                    vocabulary_entries * max(1, concept_scope_characters)
                )
    if aliases > MAX_GLOSSARY_ALIASES:
        errors.add(f"aliases exceeds the {MAX_GLOSSARY_ALIASES}-entry limit")
    if bindings > MAX_GLOSSARY_BINDINGS:
        errors.add(f"bindings exceeds the {MAX_GLOSSARY_BINDINGS}-entry limit")
    if scope_prefixes > MAX_GLOSSARY_SCOPE_PREFIXES:
        errors.add(
            "scope path prefixes exceeds the "
            f"{MAX_GLOSSARY_SCOPE_PREFIXES}-entry limit"
        )
    if scope_characters > MAX_GLOSSARY_SCOPE_CHARACTERS:
        errors.add(
            "scope path prefixes exceed the "
            f"{MAX_GLOSSARY_SCOPE_CHARACTERS}-character aggregate limit"
        )
    if ownership_scope_characters > MAX_GLOSSARY_OWNERSHIP_SCOPE_CHARACTERS:
        errors.add(
            "vocabulary ownership scope work exceeds the "
            f"{MAX_GLOSSARY_OWNERSHIP_SCOPE_CHARACTERS}-character limit"
        )
    return errors.total == starting_errors


def concept_scope(concept: ConceptRecord) -> ConceptScope:
    """Return a validated concept's normalized prefixes, or None for global."""
    raw = concept.get("scope")
    if raw is None:
        return None
    prefixes = raw.get(SCOPE_PATHS_KEY, [])
    return tuple(sorted(prefixes)) if prefixes else None


def path_in_scope(path: str, scope: ConceptScope) -> bool:
    """Whether a repository-relative file/module path falls inside scope.

    Compared in NFC: macOS reports decomposed (NFD) names for a directory a
    glossary author typed composed (``café``), and a scope that silently
    matched nothing would turn into confident false drift."""
    if scope is None:
        return True
    path = unicodedata.normalize("NFC", path)
    return any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in (unicodedata.normalize("NFC", p) for p in scope)
    )


def scopes_overlap(left: ConceptScope, right: ConceptScope) -> bool:
    """Repository-wide overlaps everything; path scopes overlap by ancestry."""
    if left is None or right is None:
        return True
    return any(
        a == b or a.startswith(b + "/") or b.startswith(a + "/")
        for a in left
        for b in right
    )


def scope_evidence(scope: ConceptScope) -> ScopeEvidence:
    """Stable serialized scope metadata used by drift and validation reports."""
    if scope is None:
        repository: RepositoryScopeEvidence = {"kind": "repository"}
        return repository
    scoped: PathPrefixScopeEvidence = {
        "kind": "path-prefixes", SCOPE_PATHS_KEY: list(scope),
    }
    return scoped


_VocabularyClaim = Callable[
    [str, tuple[int, str, str], ConceptScope], "tuple[int, str, str] | None"
]


def _validate_aliases(
    concept: dict[object, object], i: int, where: str, owner_id: str,
    scope: ConceptScope, scope_valid: bool,
    claim_vocabulary: _VocabularyClaim, errors: _ValidationErrors,
) -> None:
    aliases = concept.get("aliases", [])
    if not isinstance(aliases, list):
        errors.add(f"{where}.aliases must be a list")
        aliases = []
    for j, alias in enumerate(aliases):
        aw = f"{where}.aliases[{j}]"
        if not isinstance(alias, dict):
            errors.add(f"{aw} must be an object")
            continue
        _unknown_fields(alias, _ALIAS_KEYS, aw, errors)
        alias_term = _string_field(
            alias.get("term"), f"{aw}.term", errors, required=True
        )
        alias_status = _string_field(
            alias.get("status"), f"{aw}.status", errors, required=True
        )
        if "note" in alias:
            _string_field(
                alias["note"], f"{aw}.note", errors,
                required=False, prose=True,
            )
        if alias_status is not None and alias_status not in STATUSES:
            errors.add(
                f"{aw} status {alias_status!r} not one of "
                f"{sorted(STATUSES)}"
            )
        if alias_term is None or not scope_valid:
            continue
        folded_alias = _fold_vocabulary(alias_term)
        previous = claim_vocabulary(
            folded_alias, (i, owner_id, "alias"), scope
        )
        if previous is not None:
            if previous[0] != i:
                errors.add(
                    f"{aw} alias term {alias_term!r} maps to multiple "
                    f"concepts in overlapping scopes "
                    f"({previous[1]!r} and {owner_id!r})"
                )
            else:
                errors.add(
                    f"{aw} duplicate vocabulary term {alias_term!r} "
                    f"within concept {owner_id!r}"
                )


def _validate_bindings(
    concept: dict[object, object], where: str, errors: _ValidationErrors
) -> None:
    bindings = concept.get("bindings", [])
    if not isinstance(bindings, list):
        errors.add(f"{where}.bindings must be a list")
        bindings = []
    for j, binding in enumerate(bindings):
        bw = f"{where}.bindings[{j}]"
        if not isinstance(binding, dict):
            errors.add(f"{bw} must be an object")
            continue
        _unknown_fields(binding, _BINDING_KEYS, bw, errors)
        ref = _string_field(
            binding.get("ref"), f"{bw}.ref", errors, required=True
        )
        if ref is None:
            continue
        if ":" not in ref:
            errors.add(f"{bw} needs a 'ref' like 'symbol:Name'")
            continue
        kind, _, target = ref.partition(":")
        if not target.strip():
            errors.add(f"{bw} needs a 'ref' like 'symbol:Name'")
            continue
        if kind not in BINDING_KINDS:
            errors.add(
                f"{bw} unsupported ref kind {kind!r} — bindings target "
                f"stable identities only ({sorted(BINDING_KINDS)}); "
                "community/node ids are not stable across graph rebuilds"
            )


def validate_glossary(glossary: object) -> list[str]:
    errors = _ValidationErrors()
    if not isinstance(glossary, dict):
        return ["top level must be an object"]
    _unknown_fields(glossary, _TOP_LEVEL_KEYS, "top level", errors)
    version = glossary.get("schema_version")
    if type(version) is not int or version != GLOSSARY_SCHEMA_VERSION:  # not bool/float
        errors.add(
            f"schema_version must be {GLOSSARY_SCHEMA_VERSION}, "
            f"got {_bounded_repr(glossary.get('schema_version'))}"
        )
    concepts = glossary.get("concepts")
    if not isinstance(concepts, list):
        errors.add("concepts must be a list")
        return errors.finish()
    if not _within_aggregate_limits(concepts, errors):
        return errors.finish()
    seen_ids: set[str] = set()
    vocabulary_owners: dict[str, _ScopeOwnerIndex] = {}

    def claim_vocabulary(
        folded: str, owner: tuple[int, str, str], scope: ConceptScope,
    ) -> tuple[int, str, str] | None:
        index = vocabulary_owners.setdefault(folded, _ScopeOwnerIndex())
        previous = index.conflict(scope)
        index.add(scope, owner)
        return previous

    for i, concept in enumerate(concepts):
        where = f"concepts[{i}]"
        if not isinstance(concept, dict):
            errors.add(f"{where} must be an object")
            continue
        _unknown_fields(concept, _CONCEPT_KEYS, where, errors)
        strings: dict[str, str | None] = {}
        for key in _REQUIRED_CONCEPT_KEYS:
            strings[key] = _string_field(
                concept.get(key), f"{where} field {key!r}", errors,
                required=True, prose=key == "definition",
            )
        for key in ("notes",):
            if key in concept:
                _string_field(
                    concept[key], f"{where}.{key}", errors,
                    required=False, prose=True,
                )
        status = strings["status"]
        if status is not None and status not in STATUSES:
            errors.add(
                f"{where} status {status!r} not one of {sorted(STATUSES)}"
            )
        scope, scope_valid = (
            _scope_from_raw(concept["scope"], where, errors)
            if "scope" in concept else (None, True)
        )
        cid = strings["id"]
        if cid is not None:
            if cid in seen_ids:
                errors.add(f"{where} duplicate id {cid!r}")
            seen_ids.add(cid)
        term = strings["term"]
        owner_id = cid if cid is not None else "<invalid>"
        if term is not None and scope_valid:
            folded = _fold_vocabulary(term)
            previous = claim_vocabulary(
                folded, (i, owner_id, "term"), scope
            )
            if previous is not None:
                if previous[2] == "term":
                    errors.add(
                        f"{where} duplicate term {term!r} in overlapping "
                        f"scopes ({previous[1]!r} and {owner_id!r})"
                    )
                else:
                    errors.add(
                        f"{where} term {term!r} maps to multiple concepts "
                        f"in overlapping scopes ({previous[1]!r} and "
                        f"{owner_id!r})"
                    )
        _validate_aliases(
            concept, i, where, owner_id, scope, scope_valid,
            claim_vocabulary, errors,
        )
        _validate_bindings(concept, where, errors)
    return errors.finish()


def checked_glossary(value: object) -> tuple[GlossaryDocument | None, list[str]]:
    """The one place untrusted JSON becomes a ``GlossaryDocument``: the
    document after ``validate_glossary`` accepted every field, status, scope,
    and ownership rule, or ``None`` with the diagnostics in their order."""
    errors = validate_glossary(value)
    if errors or not isinstance(value, dict):
        return None, errors
    return cast(GlossaryDocument, value), []


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
    return glossary


def save_glossary(root: Path, document: object) -> Path:
    """Validate an untrusted JSON document and write it as the glossary."""
    glossary, errors = checked_glossary(document)
    if glossary is None:
        raise GlossaryError("refusing to save invalid glossary: "
                            + "; ".join(errors))
    concepts: list[ConceptRecord] = []
    for original in glossary["concepts"]:
        concept = original.copy()
        scope = concept.get("scope")
        if scope is not None:
            concept["scope"] = {SCOPE_PATHS_KEY: sorted(scope[SCOPE_PATHS_KEY])}
        concepts.append(concept)
    normalized: GlossaryDocument = {
        "schema_version": glossary["schema_version"],
        "concepts": sorted(concepts, key=lambda c: c["id"]),
    }
    return write_artifact(root, GLOSSARY_FILE, normalized)
