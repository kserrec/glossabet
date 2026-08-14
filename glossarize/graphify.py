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
        data = json.loads(path.read_text())
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


def build_structural_groups(
    root: Path, git_stamp: dict | None = None
) -> dict:
    graph, present, warnings = _load_graph(root)
    if graph is None:
        return _unavailable(present=present, warnings=warnings)

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
            "community_name": _first(raw, ("community_name",), str),
        }
    if not nodes:
        return _unavailable(
            present=True,
            warnings=warnings + [
                f"{GRAPH_PATH}: nodes carry no usable ids — proceeding lexical-only"
            ],
        )

    degree: Counter = Counter()
    edge_count = 0
    links = _first(graph, ("links", "edges"), list) or []
    for edge in links:
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
            edge_count += 1

    glossary_nodes = {n for n, d in nodes.items() if d["prov"] == "glossary"}

    groups: dict[str, dict] = {}
    communities = graph.get("communities")
    if isinstance(communities, list) and communities:
        for i, comm in enumerate(communities):
            if not isinstance(comm, dict):
                continue
            gid_val = _first(comm, ("id", "label", "name"))
            gid = str(i if gid_val is None else gid_val)  # id 0 is a real id
            raw_members = comm.get("nodes")
            if not isinstance(raw_members, list):
                continue  # unrecognized shape: tolerate, don't crash
            members = [str(m) for m in raw_members if str(m) in nodes]
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
            group = groups.setdefault(
                gid,
                {
                    "label": f"community {gid}",
                    "cohesion": None,
                    "members": [],
                    "label_counts": Counter(),
                },
            )
            group["members"].append(nid)
            if node["community_name"]:
                group["label_counts"][node["community_name"]] += 1
        for gid, group in groups.items():
            labels = group.pop("label_counts")
            if labels:
                group["label"] = sorted(
                    labels.items(), key=lambda item: (-item[1], item[0])
                )[0][0]
                if len(labels) > 1:
                    warnings.append(
                        f"{GRAPH_PATH}: community {gid} has conflicting names; "
                        f"using {group['label']!r}"
                    )
    if not groups:
        warnings.append(
            f"{GRAPH_PATH}: no community structure found — groups unavailable"
        )

    group_items = []
    for gid, group in groups.items():
        members = group["members"]
        if not members:
            continue
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

    if not group_items and not any("no community structure" in w for w in warnings):
        warnings.append(
            f"{GRAPH_PATH}: no usable community members — groups unavailable"
        )

    god_nodes = [
        {"label": nodes[nid]["label"], "degree": count}
        for nid, count in sorted(degree.items(), key=lambda kv: (-kv[1], kv[0]))
        if nid not in glossary_nodes
    ][:GOD_NODE_CAP]

    return {
        "adapter_enabled": True,
        "present": True,
        "available": bool(group_items),
        "source": GRAPH_PATH,
        "freshness": _freshness(graph, git_stamp),
        "nodes": len(nodes),
        "edges": edge_count,
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
