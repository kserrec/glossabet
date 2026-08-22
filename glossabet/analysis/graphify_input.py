"""Graphify input adaptation: bounded reading and tolerant normalization.

``graphify-out/graph.json`` is not a schema Glossabet controls, so every
field read here is tolerant: the adapter extracts only the shapes it
recognizes and reports anything else as a warning for the caller to degrade
on (never an error). This module owns the untrusted side of the adapter —
the bounded read, the input-work budget judged before any materialization,
node normalization with label bounds, provenance classification (nodes that
trace to the glossary or Glossabet's own report are Glossabet's vocabulary
echoing back, never structure), edge summary, and Git freshness. It knows
nothing about groups, caps on output, or nominations.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TypedDict

from glossabet.analysis.evidence_types import FreshnessRecord
from glossabet.runtime.artifacts import (
    READ_ABSENT,
    READ_OVERSIZED,
    REPORT_FILE,
    ArtifactError,
    confined_artifact_path,
    read_bounded_json,
)

GRAPH_PATH = "graphify-out/graph.json"
# A node label longer than this is not a name. It is a stated bound with its
# own ledger entry — a repository-controlled 29 MB label must not become a
# 100 MB evidence artifact.
MAX_NODE_LABEL_CHARS = 512
# Input-work ceiling, judged from list lengths BEFORE any node, edge, or
# member is materialized: a repository-controlled graph under the 64 MB size
# cap could otherwise list a few thousand communities × a few thousand
# members and cost gigabytes and tens of seconds while the output caps only
# trim what is emitted afterwards. Real Graphify graphs are thousands of
# references, not millions; beyond this the graph is reported present but
# unusable and the run proceeds lexical-only.
GRAPH_WORK_BUDGET = 1_000_000
_GLOSSARY_TYPES = frozenset({"glossary"})
_DOCUMENT_TYPES = frozenset({"doc", "document", "paper", "markdown"})
_DOCUMENT_SUFFIXES = frozenset({".md", ".rst", ".txt", ".pdf"})
_GLOSSARY_OUTPUT_DIRS = frozenset({"glossabet-out", "glossarize-out"})
# The settled glossary and Glossabet's own derived report: a Graphify node
# built from either is Glossabet's vocabulary echoing back, never structure.
_GLOSSARY_FILES = frozenset({"glossary.md", REPORT_FILE.casefold()})


def _first_value(mapping: Mapping[str, object], keys: Sequence[str]) -> object:
    """The first present, *non-empty* value among ``keys``: an empty label
    falls through to the name/id — emptiness is absence for every field read
    here. ``_first_str`` / ``_first_list`` add the type requirement."""
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        if isinstance(value, (str, list, dict)) and not value:
            continue
        return value
    return None


def _first_str(mapping: Mapping[str, object], keys: Sequence[str]) -> str | None:
    """``_first_value`` restricted to non-empty strings."""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _first_list(
    mapping: Mapping[str, object], keys: Sequence[str]
) -> list[object] | None:
    """``_first_value`` restricted to non-empty lists (an empty ``links``
    list falls through to a legacy ``edges`` list)."""
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, list) and value:
            return value
    return None


class _NodeCache(TypedDict, total=False):
    """Per-node memo filled lazily by ``_node_tokens``."""

    tokens: list[str]


class _Node(_NodeCache):
    """One normalized graph node: a bounded label, its provenance class,
    and the raw community attributes the fallback grouping reads."""

    label: str
    label_truncated: bool
    prov: str
    community: object
    community_name: str | None


@dataclass(frozen=True)
class _LoadedGraph:
    """A bounded graph document whose non-empty node list was checked once
    at load time, so no later reader re-validates the top-level shape."""

    document: dict[str, object]
    nodes: list[object]


def _load_graph(root: Path) -> tuple[_LoadedGraph | None, bool, list[str]]:
    try:
        path = confined_artifact_path(root, GRAPH_PATH)
    except ArtifactError as exc:
        return None, True, [f"{exc} — proceeding lexical-only"]
    read = read_bounded_json(path)
    if read.status == READ_ABSENT:
        return None, False, []
    if read.status == READ_OVERSIZED:
        return None, True, [
            f"{GRAPH_PATH}: larger than {read.cap} bytes — "
            "proceeding lexical-only"
        ]
    if not read.ok:
        return None, True, [
            f"{GRAPH_PATH}: unreadable JSON — proceeding lexical-only"
        ]
    data = read.value
    raw_nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(raw_nodes, list) or not raw_nodes:
        return None, True, [
            f"{GRAPH_PATH}: no recognizable node list — proceeding lexical-only"
        ]
    graph = _LoadedGraph(document=data, nodes=raw_nodes)
    references = _graph_references(graph)
    if references > GRAPH_WORK_BUDGET:
        return None, True, [
            f"{GRAPH_PATH}: {references} node/edge/member references exceed "
            f"the adapter's work budget of {GRAPH_WORK_BUDGET} — proceeding "
            "lexical-only"
        ]
    return graph, True, []


def _graph_references(graph: _LoadedGraph) -> int:
    """Nodes + edges + community member references, counted from list
    lengths only — the input work a graph would cost, known before any of
    it is done."""
    data = graph.document
    total = len(graph.nodes)
    for key in ("links", "edges"):
        value = data.get(key)
        if isinstance(value, list):
            total += len(value)
    communities = data.get("communities")
    if isinstance(communities, list):
        total += len(communities)
        for community in communities:
            if isinstance(community, dict):
                members = community.get("nodes")
                if isinstance(members, list):
                    total += len(members)
    return total


def _normalized_source(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value.strip()).casefold()
    parts: list[str] = []
    for part in normalized.replace("\\", "/").split("/"):
        if part in {"", "."}:
            continue
        if part == ".." and parts and parts[-1] != "..":
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def _provenance(node: Mapping[str, object]) -> str:
    source = _first_str(
        node, ("source_file", "source", "file", "path", "origin")
    ) or ""
    normalized_source = _normalized_source(source)
    source_parts = PurePosixPath(normalized_source).parts
    ntype = unicodedata.normalize(
        "NFKC", _first_str(node, ("file_type", "type", "kind")) or ""
    ).strip().casefold()
    if (
        ntype in _GLOSSARY_TYPES
        or not _GLOSSARY_OUTPUT_DIRS.isdisjoint(source_parts)
        or (source_parts and source_parts[-1] in _GLOSSARY_FILES)
    ):
        return "glossary"
    if (
        ntype in _DOCUMENT_TYPES
        or PurePosixPath(normalized_source).suffix in _DOCUMENT_SUFFIXES
    ):
        return "doc"
    return "code"


def _same_commit(built: str, current: str) -> bool:
    return built == current or (
        len(built) >= 7 and len(built) < len(current) and current.startswith(built)
    )


class _FreshnessBase(TypedDict):
    built_at_commit: str | None
    current_commit: str | None
    worktree_dirty: bool | None


def _freshness(
    graph: Mapping[str, object], git_stamp: Mapping[str, object] | None
) -> FreshnessRecord:
    built_raw = graph.get("built_at_commit")
    built = built_raw.strip() if isinstance(built_raw, str) else None
    current_raw = git_stamp.get("head") if isinstance(git_stamp, dict) else None
    current = current_raw.strip() if isinstance(current_raw, str) else None
    dirty = git_stamp.get("dirty") if isinstance(git_stamp, dict) else None
    base: _FreshnessBase = {
        "built_at_commit": built,
        "current_commit": current,
        "worktree_dirty": dirty if isinstance(dirty, bool) else None,
    }
    if not built:
        return {
            **base,
            "status": "unverified",
            "detail": "Graphify graph has no built_at_commit stamp",
        }
    if not current:
        return {
            **base,
            "status": "unverified",
            "detail": "repository HEAD is unavailable; graph freshness cannot be verified",
        }
    if not _same_commit(built, current):
        return {
            **base,
            "status": "stale",
            "detail": (
                f"Graphify records built_at_commit {built[:12]}, but current "
                f"HEAD is {current[:12]}"
            ),
        }
    if dirty is True:
        return {
            **base,
            "status": "unverified",
            "detail": (
                "Graphify built_at_commit matches HEAD, but the worktree has "
                "uncommitted changes"
            ),
        }
    if dirty is not False:
        return {
            **base,
            "status": "unverified",
            "detail": (
                "Graphify built_at_commit matches HEAD, but worktree cleanliness "
                "is unavailable"
            ),
        }
    return {
        **base,
        "status": "current",
        "detail": (
            "Graphify built_at_commit matches current HEAD and the worktree "
            "is clean"
        ),
    }


def _normalize_nodes(graph: _LoadedGraph) -> dict[str, _Node]:
    nodes: dict[str, _Node] = {}
    for raw in graph.nodes:
        if not isinstance(raw, dict):
            continue
        node_id = _first_value(raw, ("id", "name"))
        if node_id is None:
            continue
        node_id = str(node_id)
        label = str(_first_value(raw, ("label", "name", "id")))
        nodes[node_id] = {
            "label": label[:MAX_NODE_LABEL_CHARS],
            "label_truncated": len(label) > MAX_NODE_LABEL_CHARS,
            "prov": _provenance(raw),
            "community": raw.get("community"),
            "community_name": _first_str(raw, ("community_name",)),
        }
    return nodes


def _edge_summary(
    graph: Mapping[str, object],
    nodes: Mapping[str, _Node],
    excluded_nodes: set[str],
) -> tuple[Counter[str], int]:
    degree: Counter[str] = Counter()
    edge_count = 0
    links = _first_list(graph, ("links", "edges")) or []
    for edge in links:
        if not isinstance(edge, dict):
            continue
        source = _first_value(edge, ("source", "from", "a"))
        target = _first_value(edge, ("target", "to", "b"))
        if source is None or target is None:
            continue
        source, target = str(source), str(target)
        if (
            source in nodes
            and target in nodes
            and source not in excluded_nodes
            and target not in excluded_nodes
        ):
            degree[source] += 1
            degree[target] += 1
            edge_count += 1
    return degree, edge_count
