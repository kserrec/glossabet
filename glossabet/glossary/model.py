"""The persisted glossary schema (``glossabet-out/glossary.json``, schema 1).

These are the shapes ``validate_glossary`` accepts, written as ``TypedDict``
so the persisted document stays an ordinary dictionary with no runtime cost.
A value only carries one of these types after complete validation; raw JSON
is ``object`` until then. This module owns meaning only and imports nothing
from persistence or commands.
"""

from __future__ import annotations

from typing import Final, Literal, TypedDict, Union, get_args

GLOSSARY_SCHEMA_VERSION: Final = 1

VocabularyStatus = Literal[
    "canonical", "proposed", "alias", "discouraged", "deprecated", "unknown"
]
STATUSES: frozenset[str] = frozenset(get_args(VocabularyStatus))

# Bindings target stable identities only: never graph community numbers or
# node ids, which shift across rebuilds.
BindingKind = Literal["symbol", "file", "module"]
BINDING_KINDS: frozenset[str] = frozenset(get_args(BindingKind))

SCOPE_PATHS_KEY: Final = "path_prefixes"


class PathPrefixScope(TypedDict):
    """A concept's literal repository-relative subsystem boundary."""

    path_prefixes: list[str]


class _AliasRequired(TypedDict):
    term: str
    status: VocabularyStatus


class AliasRecord(_AliasRequired, total=False):
    note: str


class BindingRecord(TypedDict):
    """``ref`` is ``<kind>:<target>`` with ``kind`` a ``BindingKind``."""

    ref: str


class _ConceptRequired(TypedDict):
    id: str
    term: str
    definition: str
    status: VocabularyStatus


class ConceptRecord(_ConceptRequired, total=False):
    scope: PathPrefixScope  # omitted: repository-wide
    aliases: list[AliasRecord]
    bindings: list[BindingRecord]
    notes: str


class GlossaryDocument(TypedDict):
    schema_version: int
    concepts: list[ConceptRecord]


# A validated concept's scope in its internal form: the NFC-normalized,
# sorted, unique prefixes, or ``None`` for repository-wide.
ConceptScope = Union[tuple[str, ...], None]


class RepositoryScopeEvidence(TypedDict):
    kind: Literal["repository"]


class PathPrefixScopeEvidence(TypedDict):
    kind: Literal["path-prefixes"]
    path_prefixes: list[str]


# How drift and validation reports serialize a concept's scope.
ScopeEvidence = Union[RepositoryScopeEvidence, PathPrefixScopeEvidence]
