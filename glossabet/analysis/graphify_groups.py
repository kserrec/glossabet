"""Graphify structural groups: normalized communities, caps, and nominations.

Works only on the normalized nodes and edge summary that
``graphify_input`` produced: community extraction (explicit list or per-node
attributes), member tokens memoized per node, cohesion checks, god nodes,
every output cap with its coverage ledger, the unavailable/disabled evidence
shapes, and the structure nominations the importance section consumes.
Graphify's artifacts are read, never written.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import TypedDict, TypeGuard

from glossabet.analysis.evidence_types import (
    GodNode,
    StructuralGroup,
    StructuralGroups,
    StructureCandidate,
    StructureNaming,
)
from glossabet.analysis.graphify_input import (
    GRAPH_PATH,
    MAX_NODE_LABEL_CHARS,
    GraphNode,
    first_value,
    load_graph_input,
)
from glossabet.corpus.tokenize import tokenize_bounded_term
from glossabet.runtime.coverage import (
    CoverageLedger,
    capped_collection,
    coverage_ledger,
)

GROUP_CAP = 50
GOD_NODE_CAP = 8
# A group's member-token set larger than this is not a matchable context; a
# stated bound with its own ledger entry.
MEMBER_TOKEN_CAP = 2_000
# Graphify's cohesion is a fraction; anything beyond this magnitude is not a
# usable score (an astronomically large JSON number would overflow float
# math and poison every derived score).
MAX_USABLE_COHESION = 1_000_000.0
MEMBER_SAMPLE = 6
STRUCTURE_CANDIDATE_CAP = 10


class _Group(TypedDict):
    """One normalized community before it becomes a ``StructuralGroup``."""

    label: str
    cohesion: float | None
    members: list[str]


def _unavailable(
    *, present: bool | None, warnings: list[str], disabled: bool = False
) -> StructuralGroups:
    return {
        "adapter_enabled": not disabled,
        "present": present,
        "usable": False,
        "freshness": None,
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


def _extract_groups(
    communities: list[object] | None,
    nodes: Mapping[str, GraphNode],
    warnings: list[str],
) -> dict[str, _Group]:
    if communities:
        return _groups_from_communities(communities, nodes)
    return _groups_from_node_attributes(nodes, warnings)


def _groups_from_communities(
    communities: list[object], nodes: Mapping[str, GraphNode]
) -> dict[str, _Group]:
    """Explicit communities list: each entry names its own members."""
    groups: dict[str, _Group] = {}
    for index, community in enumerate(communities):
        if not isinstance(community, dict):
            continue
        group_id_value = first_value(community, ("id", "label", "name"))
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
                first_value(community, ("label", "name"))
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
    nodes: Mapping[str, GraphNode], warnings: list[str]
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


def _node_tokens(node: GraphNode) -> list[str]:
    """A node label's tokens, computed once per node however many
    communities list it."""
    tokens = node.get("tokens")
    if tokens is None:
        tokens = node["tokens"] = tokenize_bounded_term(
            node["label"], truncated=node["label_truncated"]
        )
    return tokens


def _group_items(
    groups: Mapping[str, _Group],
    nodes: Mapping[str, GraphNode],
    degree: Counter[str],
    glossary_nodes: Collection[str],
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
        truncated_member_labels = sum(
            nodes[member]["label_truncated"] for member in visible
        )
        member_label_reasons = (
            [
                f"{truncated_member_labels} structural member label(s) were "
                "truncated before tokenization"
            ]
            if truncated_member_labels else []
        )
        members_sample, sample_coverage = capped_collection(
            member_labels,
            MEMBER_SAMPLE,
            cap_reason=(
                f"structural member display cap is {MEMBER_SAMPLE} items"
            ),
            incomplete_reasons=member_label_reasons,
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
            total_items_exact=not truncated_member_labels,
            incomplete_reasons=member_label_reasons,
        )
        items.append({
            "id": group_id,
            "label": group["label"][:MAX_NODE_LABEL_CHARS],
            "label_truncated": len(group["label"]) > MAX_NODE_LABEL_CHARS,
            "cohesion": group["cohesion"],
            "size": len(visible),
            "members_sample": members_sample,
            # Reconciliation matches the retained normalized tokens, and reads
            # this collection's ledger before making a negative conclusion.
            # The six labels above remain display evidence only.
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
    nodes: Mapping[str, GraphNode],
    degree: Counter[str],
    glossary_nodes: Collection[str],
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
    graph = load_graph_input(root, git_stamp)
    warnings = list(graph.warnings)
    if not graph.nodes or graph.freshness is None:
        return _unavailable(present=graph.present, warnings=warnings)

    groups = _extract_groups(graph.communities, graph.nodes, warnings)
    if not groups:
        warnings.append(
            f"{GRAPH_PATH}: no community structure found — groups unavailable"
        )

    group_items = _group_items(
        groups, graph.nodes, graph.degree, graph.glossary_nodes
    )

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
    god_nodes, god_coverage = _god_nodes(
        graph.nodes, graph.degree, graph.glossary_nodes
    )
    return {
        "adapter_enabled": True,
        "present": True,
        "usable": bool(group_items),
        "source": GRAPH_PATH,
        "freshness": graph.freshness,
        "source_nodes": len(graph.nodes),
        "nodes": len(graph.nodes) - len(graph.glossary_nodes),
        "edges": graph.edge_count,
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
        "discounted_glossary_nodes": len(graph.glossary_nodes),
        "warnings": warnings,
    }


def structure_candidates(structural: StructuralGroups) -> StructureNaming:
    """Group-based naming nominations for the importance section."""
    source_groups_dropped = structural.get("naming_groups_dropped", 0)
    if not structural["usable"]:
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
