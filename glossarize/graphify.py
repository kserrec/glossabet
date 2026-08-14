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

GRAPH_PATH = "graphify-out/graph.json"
GROUP_CAP = 50
GOD_NODE_CAP = 8
MEMBER_SAMPLE = 6

UNAVAILABLE = {"available": False, "warnings": []}


def _first(d: dict, keys, types=None):
    for key in keys:
        value = d.get(key)
        if value is not None and (types is None or isinstance(value, types)):
            return value
    return None


def _load_graph(root: Path) -> tuple[dict | None, list[str]]:
    path = root / GRAPH_PATH
    if not path.is_file():
        return None, []
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None, [f"{GRAPH_PATH}: unreadable JSON — proceeding lexical-only"]
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("nodes"), list)
        or not data["nodes"]
    ):
        return None, [
            f"{GRAPH_PATH}: no recognizable node list — proceeding lexical-only"
        ]
    return data, []


def _provenance(node: dict) -> str:
    source = _first(node, ("source", "file", "path", "origin"), str) or ""
    if "glossarize-out" in source or source.endswith("GLOSSARY.md"):
        return "glossary"
    ntype = (_first(node, ("type", "kind"), str) or "").lower()
    if ntype in ("doc", "document", "paper", "markdown") or source.lower().endswith(
        (".md", ".rst", ".txt", ".pdf")
    ):
        return "doc"
    return "code"


def build_structural_groups(root: Path) -> dict:
    graph, warnings = _load_graph(root)
    if graph is None:
        return {"available": False, "warnings": warnings}

    nodes: dict[str, dict] = {}
    for raw in graph["nodes"]:
        if not isinstance(raw, dict):
            continue
        nid = _first(raw, ("id", "name"))
        if nid is None:
            continue
        nid = str(nid)
        nodes[nid] = {
            "label": str(_first(raw, ("label", "name", "id"))),
            "prov": _provenance(raw),
            "community": raw.get("community"),
        }
    if not nodes:
        return {
            "available": False,
            "warnings": warnings
            + [f"{GRAPH_PATH}: nodes carry no usable ids — proceeding lexical-only"],
        }

    degree: Counter = Counter()
    edges = graph.get("edges")
    if isinstance(edges, list):
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            a = _first(edge, ("source", "from", "a"))
            b = _first(edge, ("target", "to", "b"))
            if a is None or b is None:
                continue
            a, b = str(a), str(b)
            if a in nodes and b in nodes:
                degree[a] += 1
                degree[b] += 1

    glossary_nodes = {n for n, d in nodes.items() if d["prov"] == "glossary"}

    groups: dict[str, dict] = {}
    communities = graph.get("communities")
    if isinstance(communities, list) and communities:
        for i, comm in enumerate(communities):
            if not isinstance(comm, dict):
                continue
            gid = str(_first(comm, ("id", "label", "name")) or i)
            members = [str(m) for m in comm.get("nodes", []) if str(m) in nodes]
            cohesion = comm.get("cohesion")
            groups[gid] = {
                "label": str(_first(comm, ("label", "name")) or f"community {gid}"),
                "cohesion": cohesion if isinstance(cohesion, (int, float)) else None,
                "members": members,
            }
    else:
        for nid, node in sorted(nodes.items()):
            community = node["community"]
            if community is None:
                continue
            gid = str(community)
            groups.setdefault(
                gid, {"label": f"community {gid}", "cohesion": None, "members": []}
            )["members"].append(nid)
    if not groups:
        warnings.append(
            f"{GRAPH_PATH}: no community structure found — groups unavailable"
        )

    group_items = []
    for gid, group in groups.items():
        members = group["members"]
        visible = [m for m in members if m not in glossary_nodes]
        provenance = Counter(nodes[m]["prov"] for m in members)
        sample = sorted(visible, key=lambda m: (-degree[m], nodes[m]["label"]))
        group_items.append({
            "id": gid,
            "label": group["label"],
            "cohesion": group["cohesion"],
            "size": len(members),
            "members_sample": [nodes[m]["label"] for m in sample[:MEMBER_SAMPLE]],
            "provenance": {
                "code": provenance.get("code", 0),
                "doc": provenance.get("doc", 0),
                "glossary": provenance.get("glossary", 0),
            },
        })
    group_items.sort(key=lambda g: (-g["size"], g["id"]))

    god_nodes = [
        {"label": nodes[nid]["label"], "degree": count}
        for nid, count in sorted(degree.items(), key=lambda kv: (-kv[1], kv[0]))
        if nid not in glossary_nodes
    ][:GOD_NODE_CAP]

    return {
        "available": True,
        "source": GRAPH_PATH,
        "freshness_unverified": True,  # graphify stamps no git state we can check
        "nodes": len(nodes),
        "groups": group_items[:GROUP_CAP],
        "groups_dropped": max(0, len(group_items) - GROUP_CAP),
        "god_nodes": god_nodes,
        "discounted_glossary_nodes": len(glossary_nodes),
        "warnings": warnings,
    }


def structure_candidates(structural: dict) -> dict:
    """Group-based naming nominations for the importance section."""
    if not structural.get("available"):
        return {"structures": [], "structures_dropped": 0}
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
        "structures_dropped": max(0, len(candidates) - cap),
    }
