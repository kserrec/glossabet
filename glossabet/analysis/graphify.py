"""Graphify evidence adapter: graphify-out/graph.json -> structural groups.

Graphify's graph.json is not a schema glossabet controls, so field mapping
is deliberately tolerant: the adapter extracts only shapes it recognizes and
degrades to lexical-only with a warning otherwise (never an error). Nodes
whose provenance traces to the glossary are discounted everywhere, so the
settled vocabulary cannot echo back through the graph as fake structural
support. Graphify's artifacts are read, never written.

This module is the stable facade: input adaptation lives in
``graphify_input`` and group analysis in ``graphify_groups``. Tests that
patch a cap or a helper must patch the owning module, not this re-export.
"""

from __future__ import annotations

from glossabet.analysis.graphify_groups import (
    GOD_NODE_CAP,
    GROUP_CAP,
    MAX_USABLE_COHESION,
    MEMBER_SAMPLE,
    MEMBER_TOKEN_CAP,
    STRUCTURE_CANDIDATE_CAP,
    build_structural_groups,
    disabled_structural_groups,
    structure_candidates,
)
from glossabet.analysis.graphify_input import (
    GRAPH_LABEL_CHAR_BUDGET,
    GRAPH_PATH,
    GRAPH_WORK_BUDGET,
    MAX_NODE_LABEL_CHARS,
)

__all__ = [
    "GOD_NODE_CAP",
    "GRAPH_LABEL_CHAR_BUDGET",
    "GRAPH_PATH",
    "GRAPH_WORK_BUDGET",
    "GROUP_CAP",
    "MAX_NODE_LABEL_CHARS",
    "MAX_USABLE_COHESION",
    "MEMBER_SAMPLE",
    "MEMBER_TOKEN_CAP",
    "STRUCTURE_CANDIDATE_CAP",
    "build_structural_groups",
    "disabled_structural_groups",
    "structure_candidates",
]
