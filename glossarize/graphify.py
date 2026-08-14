"""Graphify evidence adapter: graphify-out/graph.json -> structural groups.

Graphify's graph.json is not a schema glossarize controls, so field mapping
is deliberately tolerant: the adapter extracts only shapes it recognizes and
degrades to lexical-only with a warning otherwise (never an error). Nodes
whose provenance traces to the glossary are discounted everywhere, so the
settled vocabulary cannot echo back through the graph as fake structural
support (PLAN principle 3). Graphify's artifacts are read, never written.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from glossarize.artifacts import (
    ArtifactError,
    MAX_JSON_BYTES,
    confined_artifact_path,
    oversized,
)

GRAPH_PATH = "graphify-out/graph.json"
GROUP_CAP = 50
GOD_NODE_CAP = 8
MEMBER_SAMPLE = 6


def _first(d: dict, keys, types=None):
    for key in keys:
        value = d.get(key)
        if value is not None and (types is None or isinstance(value, types)):
            return value
    return None


def _unavailable(
    *, present: bool | None, warnings: list[str], disabled: bool = False
) -> dict:
    return {
        "adapter_enabled": not disabled,
        "present": present,
        "available": False,
        "warnings": warnings,
    }


def disabled_structural_groups() -> dict:
    """Evidence shape when the caller explicitly disables the adapter."""
    return _unavailable(present=None, warnings=[], disabled=True)


def _load_graph(root: Path) -> tuple[dict | None, bool, list[str]]:
    try:
        path = confined_artifact_path(root, GRAPH_PATH)
    except ArtifactError as exc:
        return None, True, [f"{exc} — proceeding lexical-only"]
    if not path.is_file():
        return None, False, []
    if oversized(path):
        return None, True, [
            f"{GRAPH_PATH}: larger than {MAX_JSON_BYTES} bytes — "
            "proceeding lexical-only"
        ]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        # RecursionError: deeply nested JSON. json raises it outside the
        # ValueError hierarchy, so it must be caught explicitly or a hostile
        # graph would crash the whole scan.
        return None, True, [
            f"{GRAPH_PATH}: unreadable JSON — proceeding lexical-only"
        ]
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("nodes"), list)
        or not data["nodes"]
    ):
        return None, True, [
            f"{GRAPH_PATH}: no recognizable node list — proceeding lexical-only"
        ]
    return data, True, []


def _provenance(node: dict) -> str:
    source = _first(
        node, ("source_file", "source", "file", "path", "origin"), str
    ) or ""
    if "glossarize-out" in source or source.endswith("GLOSSARY.md"):
        return "glossary"
    ntype = (_first(node, ("file_type", "type", "kind"), str) or "").lower()
    if ntype in ("doc", "document", "paper", "markdown") or source.lower().endswith(
        (".md", ".rst", ".txt", ".pdf")
    ):
        return "doc"
    return "code"


def _same_commit(built: str, current: str) -> bool:
    return built == current or (
        len(built) >= 7 and len(built) < len(current) and current.startswith(built)
    )


def _freshness(graph: dict, git_stamp: dict | None) -> dict:
    built_raw = graph.get("built_at_commit")
    built = built_raw.strip() if isinstance(built_raw, str) else None
    current_raw = git_stamp.get("head") if isinstance(git_stamp, dict) else None
    current = current_raw.strip() if isinstance(current_raw, str) else None
    dirty = git_stamp.get("dirty") if isinstance(git_stamp, dict) else None
    base = {
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


def _normalize_nodes(graph: dict) -> dict[str, dict]:
    nodes: dict[str, dict] = {}
    for raw in graph["nodes"]:
        if not isinstance(raw, dict):
            continue
        node_id = _first(raw, ("id", "name"))
        if node_id is None:
            continue
        node_id = str(node_id)
        nodes[node_id] = {
            "label": str(_first(raw, ("label", "name", "id"))),
            "prov": _provenance(raw),
            "community": raw.get("community"),
            "community_name": _first(raw, ("community_name",), str),
        }
    return nodes


def _edge_summary(
    graph: dict,
    nodes: dict[str, dict],
    excluded_nodes: set[str],
) -> tuple[Counter, int]:
    degree: Counter = Counter()
    edge_count = 0
    links = _first(graph, ("links", "edges"), list) or []
    for edge in links:
        if not isinstance(edge, dict):
            continue
        source = _first(edge, ("source", "from", "a"))
        target = _first(edge, ("target", "to", "b"))
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
    graph: dict,
    nodes: dict[str, dict],
    warnings: list[str],
) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    communities = graph.get("communities")
    if isinstance(communities, list) and communities:
        for index, community in enumerate(communities):
            if not isinstance(community, dict):
                continue
            group_id_value = _first(community, ("id", "label", "name"))
            # Zero is a valid Graphify community id, so only None falls back.
            group_id = str(
                index if group_id_value is None else group_id_value
            )
            raw_members = community.get("nodes")
            if not isinstance(raw_members, list):
                # Tolerate unknown community shapes; the caller reports when
                # no usable structure remains after normalization.
                continue
            members = [
                str(member)
                for member in raw_members
                if str(member) in nodes
            ]
            cohesion = community.get("cohesion")
            groups[group_id] = {
                "label": str(
                    _first(community, ("label", "name"))
                    or f"community {group_id}"
                ),
                "cohesion": (
                    cohesion if isinstance(cohesion, (int, float)) else None
                ),
                "members": members,
            }
        return groups

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
                "label_counts": Counter(),
            },
        )
        group["members"].append(node_id)
        if node["community_name"]:
            group["label_counts"][node["community_name"]] += 1
    for group_id, group in groups.items():
        labels = group.pop("label_counts")
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


def _group_items(
    groups: dict[str, dict],
    nodes: dict[str, dict],
    degree: Counter,
    glossary_nodes: set[str],
) -> list[dict]:
    items = []
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
        items.append({
            "id": group_id,
            "label": group["label"],
            "cohesion": group["cohesion"],
            "size": len(visible),
            "members_sample": [
                nodes[member]["label"] for member in sample[:MEMBER_SAMPLE]
            ],
            "provenance": {
                "code": provenance.get("code", 0),
                "doc": provenance.get("doc", 0),
                "glossary": provenance.get("glossary", 0),
            },
        })
    items.sort(key=lambda group: (-group["size"], group["id"]))
    return items


def _god_nodes(
    nodes: dict[str, dict], degree: Counter, glossary_nodes: set[str]
) -> list[dict]:
    return [
        {"label": nodes[node_id]["label"], "degree": count}
        for node_id, count in sorted(
            degree.items(), key=lambda item: (-item[1], item[0])
        )
        if node_id not in glossary_nodes
    ][:GOD_NODE_CAP]


def build_structural_groups(
    root: Path, git_stamp: dict | None = None
) -> dict:
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

    glossary_nodes = {
        node_id for node_id, node in nodes.items()
        if node["prov"] == "glossary"
    }
    degree, edge_count = _edge_summary(graph, nodes, glossary_nodes)
    groups = _extract_groups(graph, nodes, warnings)
    if not groups:
        warnings.append(
            f"{GRAPH_PATH}: no community structure found — groups unavailable"
        )

    group_items = _group_items(groups, nodes, degree, glossary_nodes)

    if not group_items and not any("no community structure" in w for w in warnings):
        warnings.append(
            f"{GRAPH_PATH}: no usable community members — groups unavailable"
        )

    retained_groups = group_items[:GROUP_CAP]
    dropped_groups = group_items[GROUP_CAP:]
    return {
        "adapter_enabled": True,
        "present": True,
        "available": bool(group_items),
        "source": GRAPH_PATH,
        "freshness": _freshness(graph, git_stamp),
        "source_nodes": len(nodes),
        "nodes": len(nodes) - len(glossary_nodes),
        "edges": edge_count,
        "groups": retained_groups,
        "groups_dropped": len(dropped_groups),
        "groups_complete": not dropped_groups,
        "naming_groups_dropped": sum(
            group["size"] >= 2 for group in dropped_groups
        ),
        "god_nodes": _god_nodes(nodes, degree, glossary_nodes),
        "discounted_glossary_nodes": len(glossary_nodes),
        "warnings": warnings,
    }


def structure_candidates(structural: dict) -> dict:
    """Group-based naming nominations for the importance section."""
    source_groups_dropped = structural.get("naming_groups_dropped", 0)
    if not structural.get("available"):
        return {
            "structures": [],
            "structures_dropped": 0,
            "structures_source_groups_dropped": source_groups_dropped,
            "structures_complete": source_groups_dropped == 0,
        }
    candidates = []
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
    cap = 10
    return {
        "structures": candidates[:cap],
        "structures_dropped": (
            max(0, len(candidates) - cap) + source_groups_dropped
        ),
        "structures_source_groups_dropped": source_groups_dropped,
        "structures_complete": source_groups_dropped == 0,
    }
