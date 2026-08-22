"""Concept scope: where in the repository a vocabulary term has its meaning.

A concept either owns the whole repository (``None``) or a set of literal,
repository-relative path prefixes. This module owns normalization of those
prefixes, path membership, overlap between scopes, and the ownership index
that validation uses to find one conflicting owner in path-prefix time. It
imports neither persistence nor commands.
"""

from __future__ import annotations

import unicodedata

from glossabet.glossary.model import (
    SCOPE_PATHS_KEY,
    ConceptRecord,
    ConceptScope,
    PathPrefixScopeEvidence,
    RepositoryScopeEvidence,
    ScopeEvidence,
)

# ``(concept index, concept id, "term" | "alias")`` — which vocabulary entry
# claimed a word first, for the diagnostic that names both owners.
VocabularyOwner = tuple[int, str, str]


def is_literal_path_prefix(prefix: str) -> bool:
    """A repository-relative prefix with no leading slash, backslash, NUL,
    empty/dot component, surrounding whitespace, or glob character."""
    parts = prefix.split("/")
    return not (
        prefix != prefix.strip()
        or prefix.startswith("/")
        or "\\" in prefix
        or "\0" in prefix
        or any(part in ("", ".", "..") for part in parts)
        or any(char in prefix for char in "*?[]")
    )


def normalize_scope(prefixes: list[str]) -> tuple[ConceptScope, bool, bool]:
    """Sort and de-duplicate literal prefixes into a scope.

    Returns ``(scope, duplicated, overlapping)``: the scope is ``None`` when
    the list is empty, repeats a prefix, or one prefix is an ancestor of
    another — such a scope is reported, never silently narrowed."""
    unique = set(prefixes)
    duplicated = len(unique) != len(prefixes)
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
    usable = bool(prefixes) and not duplicated and not overlapping
    return (tuple(sorted(unique)) if usable else None), duplicated, overlapping


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


class _ScopeNode:
    __slots__ = ("children", "owner_here", "subtree_owner")

    def __init__(self) -> None:
        self.children: dict[str, _ScopeNode] = {}
        self.owner_here: VocabularyOwner | None = None
        self.subtree_owner: VocabularyOwner | None = None


class ScopeOwnerIndex:
    """Find one overlapping vocabulary owner in path-prefix time.

    A repository-wide owner overlaps every path. Scoped owners live in a trie:
    overlap is either an owner on an ancestor node or any owner in the queried
    node's subtree. Validation therefore avoids comparing every concept with
    every earlier concept that uses the same word.
    """


    def __init__(self) -> None:
        self.global_owner: VocabularyOwner | None = None
        self.root = _ScopeNode()

    def conflict(self, scope: ConceptScope) -> VocabularyOwner | None:
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

    def add(self, scope: ConceptScope, owner: VocabularyOwner) -> None:
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

