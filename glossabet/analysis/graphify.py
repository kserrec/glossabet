"""Graphify evidence adapter: graphify-out/graph.json -> structural groups.

Graphify's graph.json is not a schema glossabet controls, so field mapping
is deliberately tolerant: the adapter extracts only shapes it recognizes and
degrades to lexical-only with a warning otherwise (never an error). Nodes
whose provenance traces to the glossary are discounted everywhere, so the
settled vocabulary cannot echo back through the graph as fake structural
support (PLAN principle 3). Graphify's artifacts are read, never written.
"""

from __future__ import annotations

import math
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TypedDict, TypeGuard

from glossabet.analysis.evidence_types import (
    FreshnessRecord,
    GodNode,
    StructuralGroup,
    StructuralGroups,
    StructureCandidate,
    StructureNaming,
)
from glossabet.corpus.tokenize import tokenize_term
from glossabet.runtime.artifacts import (
    READ_ABSENT,
    READ_OVERSIZED,
    REPORT_FILE,
    ArtifactError,
    confined_artifact_path,
    read_bounded_json,
)
from glossabet.runtime.coverage import (
    CoverageLedger,
    capped_collection,
    coverage_ledger,
)

GRAPH_PATH = "graphify-out/graph.json"
GROUP_CAP = 50
GOD_NODE_CAP = 8
# A node label longer than this is not a name; a group's member-token set
# larger than this is not a matchable context. Both are stated bounds with
# their own ledger entries — a repository-controlled 29 MB label must not
# become a 100 MB evidence artifact.
MAX_NODE_LABEL_CHARS = 512
MEMBER_TOKEN_CAP = 2_000
# Graphify's cohesion is a fraction; anything beyond this magnitude is not a
# usable score (an astronomically large JSON number would overflow float
# math and poison every derived score).
MAX_USABLE_COHESION = 1_000_000.0
# Input-work ceiling, judged from list lengths BEFORE any node, edge, or
# member is materialized: a repository-controlled graph under the 64 MB size
# cap could otherwise list a few thousand communities × a few thousand
# members and cost gigabytes and tens of seconds while the output caps only
# trim what is emitted afterwards. Real Graphify graphs are thousands of
# references, not millions; beyond this the graph is reported present but
# unusable and the run proceeds lexical-only.
GRAPH_WORK_BUDGET = 1_000_000
# Label characters tokenized across all nodes. Each node's label is tokenized
# once (memoized per node id) — a member listed in a thousand communities is
# not tokenized a thousand times — and the total is bounded, because
# tokenizing is ~0.3 ms per 512-char label: a million such labels under the
# reference budget would still cost minutes. Judged after label truncation,
# before any tokenizing.
GRAPH_LABEL_CHAR_BUDGET = 5_000_000
MEMBER_SAMPLE = 6
STRUCTURE_CANDIDATE_CAP = 10

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


class _Group(TypedDict):
    """One normalized community before it becomes a ``StructuralGroup``."""

    label: str
    cohesion: float | None
    members: list[str]


@dataclass(frozen=True)
class _LoadedGraph:
    """A bounded graph document whose non-empty node list was checked once
    at load time, so no later reader re-validates the top-level shape."""

    document: dict[str, object]
    nodes: list[object]


def _unavailable(
    *, present: bool | None, warnings: list[str], disabled: bool = False
) -> StructuralGroups:
    return {
        "adapter_enabled": not disabled,
        "present": present,
        "available": False,
        "coverage": {
            "groups": coverage_ledger(
                0,
                0,
                total_items_exact=present is not True,
                reasons=(
                    ["Graphify input was present but could not be normalized"]
                    if present is True else []
                ),
            ),
        },
        "warnings": warnings,
    }


def disabled_structural_groups() -> StructuralGroups:
    """Evidence shape when the caller explicitly disables the adapter."""
    return _unavailable(present=None, warnings=[], disabled=True)


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


def _usable_cohesion(value: object) -> TypeGuard[float]:
    """A finite, bounded, non-bool number. ``json.loads`` accepts bare NaN/
    Infinity, bool passes ``isinstance(int)``, and an integer beyond float
    range makes ``math.isfinite`` itself raise — none is a usable cohesion."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        number = float(value)
    except OverflowError:
        return False
    return math.isfinite(number) and abs(number) <= MAX_USABLE_COHESION


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


def _extract_groups(
    graph: Mapping[str, object],
    nodes: Mapping[str, _Node],
    warnings: list[str],
) -> dict[str, _Group]:
    communities = graph.get("communities")
    if isinstance(communities, list) and communities:
        return _groups_from_communities(communities, nodes)
    return _groups_from_node_attributes(nodes, warnings)


def _groups_from_communities(
    communities: list[object], nodes: Mapping[str, _Node]
) -> dict[str, _Group]:
    """Explicit communities list: each entry names its own members."""
    groups: dict[str, _Group] = {}
    for index, community in enumerate(communities):
        if not isinstance(community, dict):
            continue
        group_id_value = _first_value(community, ("id", "label", "name"))
        # Zero is a valid Graphify community id, so only None falls back.
        group_id = str(
            index if group_id_value is None else group_id_value
        )
        raw_members = community.get("nodes")
        if not isinstance(raw_members, list):
            # Tolerate unknown community shapes; the caller reports when
            # no usable structure remains after normalization.
            continue
        members = list(dict.fromkeys(  # a member list is a set: dedupe, keep order
            str(member)
            for member in raw_members
            if str(member) in nodes
        ))
        cohesion = community.get("cohesion")
        if group_id in groups:
            # Two entries claiming one id are one community written twice:
            # merge the members rather than letting the later entry silently
            # replace the earlier one.
            existing = groups[group_id]
            existing["members"] = list(
                dict.fromkeys(existing["members"] + members)
            )
            continue
        groups[group_id] = {
            "label": str(
                _first_value(community, ("label", "name"))
                or f"community {group_id}"
            ),
            # json.loads accepts bare NaN/Infinity and bool passes isinstance
            # (int); neither is a usable cohesion and NaN would poison scores
            # and emit non-conformant JSON downstream.
            "cohesion": cohesion if _usable_cohesion(cohesion) else None,
            "members": members,
        }
    return groups


def _groups_from_node_attributes(
    nodes: Mapping[str, _Node], warnings: list[str]
) -> dict[str, _Group]:
    """Fallback: fold per-node community attributes into groups."""
    groups: dict[str, _Group] = {}
    label_counts: dict[str, Counter[str]] = {}
    for node_id, node in sorted(nodes.items()):
        community = node["community"]
        if community is None:
            continue
        group_id = str(community)
        group = groups.setdefault(
            group_id,
            {
                "label": f"community {group_id}",
                "cohesion": None,
                "members": [],
            },
        )
        group["members"].append(node_id)
        if node["community_name"]:
            label_counts.setdefault(group_id, Counter())[
                node["community_name"]
            ] += 1
    for group_id, group in groups.items():
        labels = label_counts.get(group_id)
        if not labels:
            continue
        group["label"] = sorted(
            labels.items(), key=lambda item: (-item[1], item[0])
        )[0][0]
        if len(labels) > 1:
            warnings.append(
                f"{GRAPH_PATH}: community {group_id} has conflicting names; "
                f"using {group['label']!r}"
            )
    return groups


def _node_tokens(node: _Node) -> list[str]:
    """A node label's tokens, computed once per node however many
    communities list it."""
    tokens = node.get("tokens")
    if tokens is None:
        tokens = node["tokens"] = tokenize_term(node["label"])
    return tokens


def _group_items(
    groups: Mapping[str, _Group],
    nodes: Mapping[str, _Node],
    degree: Counter[str],
    glossary_nodes: set[str],
) -> list[StructuralGroup]:
    items: list[StructuralGroup] = []
    for group_id, group in groups.items():
        members = group["members"]
        if not members:
            continue
        visible = [member for member in members if member not in glossary_nodes]
        if not visible:
            continue
        provenance = Counter(nodes[member]["prov"] for member in members)
        sample = sorted(
            visible,
            key=lambda member: (-degree[member], nodes[member]["label"]),
        )
        member_labels = [nodes[member]["label"] for member in sample]
        members_sample, sample_coverage = capped_collection(
            member_labels,
            MEMBER_SAMPLE,
            cap_reason=(
                f"structural member display cap is {MEMBER_SAMPLE} items"
            ),
        )
        all_member_tokens = sorted({
            token
            for member in visible
            for token in _node_tokens(nodes[member])
        })
        member_tokens, member_token_coverage = capped_collection(
            all_member_tokens,
            MEMBER_TOKEN_CAP,
            cap_reason=f"structural member-token cap is {MEMBER_TOKEN_CAP} items",
        )
        items.append({
            "id": group_id,
            "label": group["label"][:MAX_NODE_LABEL_CHARS],
            "label_truncated": len(group["label"]) > MAX_NODE_LABEL_CHARS,
            "cohesion": group["cohesion"],
            "size": len(visible),
            "members_sample": members_sample,
            # Reconciliation matches against every normalized token in the
            # bounded Graphify input.  The six labels above remain display
            # evidence only and can no longer hide a seventh matching member.
            "member_tokens": member_tokens,
            "coverage": {
                "members_sample": sample_coverage,
                "member_tokens": member_token_coverage,
            },
            "provenance": {
                "code": provenance.get("code", 0),
                "doc": provenance.get("doc", 0),
                "glossary": provenance.get("glossary", 0),
            },
        })
    items.sort(key=lambda group: (-group["size"], group["id"]))
    return items


def _god_nodes(
    nodes: Mapping[str, _Node], degree: Counter[str], glossary_nodes: set[str]
) -> tuple[list[GodNode], CoverageLedger]:
    ranked: list[GodNode] = [
        {"label": nodes[node_id]["label"], "degree": count}
        for node_id, count in sorted(
            degree.items(), key=lambda item: (-item[1], item[0])
        )
        if node_id not in glossary_nodes
    ]
    return capped_collection(
        ranked,
        GOD_NODE_CAP,
        cap_reason=f"god-node display cap is {GOD_NODE_CAP} items",
    )


def build_structural_groups(
    root: Path, git_stamp: Mapping[str, object] | None = None
) -> StructuralGroups:
    graph, present, warnings = _load_graph(root)
    if graph is None:
        return _unavailable(present=present, warnings=warnings)

    nodes = _normalize_nodes(graph)
    if not nodes:
        return _unavailable(
            present=True,
            warnings=warnings + [
                f"{GRAPH_PATH}: nodes carry no usable ids — proceeding lexical-only"
            ],
        )
    label_chars = sum(len(node["label"]) for node in nodes.values())
    if label_chars > GRAPH_LABEL_CHAR_BUDGET:
        return _unavailable(
            present=True,
            warnings=warnings + [
                f"{GRAPH_PATH}: {label_chars} node-label characters exceed the "
                f"adapter's tokenizing budget of {GRAPH_LABEL_CHAR_BUDGET} — "
                "proceeding lexical-only"
            ],
        )

    glossary_nodes = {
        node_id for node_id, node in nodes.items()
        if node["prov"] == "glossary"
    }
    degree, edge_count = _edge_summary(graph.document, nodes, glossary_nodes)
    groups = _extract_groups(graph.document, nodes, warnings)
    if not groups:
        warnings.append(
            f"{GRAPH_PATH}: no community structure found — groups unavailable"
        )

    group_items = _group_items(groups, nodes, degree, glossary_nodes)

    if not group_items and not any("no community structure" in w for w in warnings):
        warnings.append(
            f"{GRAPH_PATH}: no usable community members — groups unavailable"
        )

    retained_groups, group_coverage = capped_collection(
        group_items,
        GROUP_CAP,
        cap_reason=f"structural group detail cap is {GROUP_CAP} items",
    )
    dropped_groups = group_items[GROUP_CAP:]
    god_nodes, god_coverage = _god_nodes(nodes, degree, glossary_nodes)
    return {
        "adapter_enabled": True,
        "present": True,
        "available": bool(group_items),
        "source": GRAPH_PATH,
        "freshness": _freshness(graph.document, git_stamp),
        "source_nodes": len(nodes),
        "nodes": len(nodes) - len(glossary_nodes),
        "edges": edge_count,
        "groups": retained_groups,
        "groups_dropped": group_coverage["dropped_items"],
        "groups_complete": group_coverage["complete"],
        "naming_groups_dropped": sum(
            group["size"] >= 2 for group in dropped_groups
        ),
        "god_nodes": god_nodes,
        "coverage": {
            "groups": group_coverage,
            "god_nodes": god_coverage,
        },
        "discounted_glossary_nodes": len(glossary_nodes),
        "warnings": warnings,
    }


def structure_candidates(structural: StructuralGroups) -> StructureNaming:
    """Group-based naming nominations for the importance section."""
    source_groups_dropped = structural.get("naming_groups_dropped", 0)
    if not structural["available"]:
        group_coverage = structural["coverage"]["groups"]
        total_exact = group_coverage["total_items_exact"] is not False
        reasons = [] if total_exact else [
            "structural groups could not be normalized completely"
        ]
        coverage = coverage_ledger(
            0, 0, total_items_exact=total_exact, reasons=reasons
        )
        return {
            "structures": [],
            "structures_dropped": 0,
            "structures_source_groups_dropped": source_groups_dropped,
            "structures_complete": coverage["complete"],
            "coverage": {"structures": coverage},
        }
    candidates: list[StructureCandidate] = []
    for group in structural["groups"]:
        if group["size"] < 2:
            continue
        reasons = [f"community of {group['size']} node(s)"]
        if group["cohesion"] is not None:
            reasons.append(f"cohesion {group['cohesion']}")
        if group["members_sample"]:
            reasons.append(
                "members include " + ", ".join(group["members_sample"][:3])
            )
        score = group["size"] + (
            group["cohesion"] * 10 if group["cohesion"] else 0
        )
        candidates.append({
            "kind": "structure",
            "label": group["label"],
            "group_id": group["id"],
            "score": round(score, 2),
            "reasons": reasons,
        })
    candidates.sort(key=lambda c: (-c["score"], c["label"]))
    # Not `capped_collection`: two mechanisms drop structures here — this
    # module's candidate cap and Graphify's upstream group cap — and the
    # ledger reports them separately, in that order.
    known_total = len(candidates) + source_groups_dropped
    included = min(len(candidates), STRUCTURE_CANDIDATE_CAP)
    reasons = []
    if len(candidates) > STRUCTURE_CANDIDATE_CAP:
        reasons.append(
            f"structure candidate detail cap is {STRUCTURE_CANDIDATE_CAP} items"
        )
    if source_groups_dropped:
        reasons.append(
            f"Graphify group cap omitted {source_groups_dropped} "
            "naming-eligible structure(s)"
        )
    coverage = coverage_ledger(
        known_total, included, reasons=reasons
    )
    return {
        "structures": candidates[:STRUCTURE_CANDIDATE_CAP],
        "structures_dropped": coverage["dropped_items"],
        "structures_source_groups_dropped": source_groups_dropped,
        "structures_complete": coverage["complete"],
        "coverage": {"structures": coverage},
    }
