"""Fresh, bounded JSON context for the installed agent skill.

The skill must not parse repository-owned machine artifacts itself.  This
module keeps path confinement, glossary validation, scanning, and output
bounding behind one CLI command while leaving the full RepositoryEvidence
artifact available to deterministic engine consumers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from glossabet.artifacts import ArtifactError, repo_root
from glossabet.evidence import build_evidence, write_evidence
from glossabet.glossary import GlossaryError, load_glossary


AGENT_CONTEXT_SCHEMA_VERSION = 1
MAX_AGENT_CONTEXT_BYTES = 1_000_000
MAX_AGENT_CONTEXT_STRING_CHARS = 512
MAX_AGENT_CONTEXT_OMISSION_RECORDS = 100
DEFAULT_AGENT_LIST_LIMIT = 50

# Large evidence collections have deliberate agent-facing samples.  The full
# bounded engine evidence remains in evidence.json for deterministic commands;
# omissions here are explicit in coverage.context.
_LIST_LIMITS: dict[tuple[str, ...], int] = {
    ("modules",): 150,
    ("files", "code"): 250,
    ("files", "docs"): 150,
    ("vocabulary", "tokens", "items"): 300,
    ("vocabulary", "identifiers", "items"): 250,
    ("vocabulary", "doc_terms", "items"): 200,
    ("structural_groups", "groups"): 100,
    ("glossary", "concepts"): 200,
}


class AgentContextError(ArtifactError):
    """A safe agent context could not be produced within its contract."""


@dataclass
class _Coverage:
    omissions: list[dict] = field(default_factory=list)
    affected_sections: set[str] = field(default_factory=set)
    omission_counts: dict[str, int] = field(default_factory=dict)
    omitted_amounts: dict[str, int] = field(default_factory=dict)

    def record(self, path: tuple[str, ...], kind: str, amount: int) -> None:
        if len(self.omissions) >= MAX_AGENT_CONTEXT_OMISSION_RECORDS:
            raise AgentContextError(
                "agent context requires more than "
                f"{MAX_AGENT_CONTEXT_OMISSION_RECORDS} omission records"
            )
        record = {"path": ".".join(path), "kind": kind, "amount": amount}
        self.omissions.append(record)
        self.affected_sections.add(path[0] if path else "<root>")
        self.omission_counts[kind] = self.omission_counts.get(kind, 0) + 1
        self.omitted_amounts[kind] = self.omitted_amounts.get(kind, 0) + amount

    def as_dict(self) -> dict:
        return {
            "complete": not self.omissions,
            "omissions": self.omissions,
            "affected_sections": sorted(self.affected_sections),
            "omission_counts": dict(sorted(self.omission_counts.items())),
            "omitted_amounts": dict(sorted(self.omitted_amounts.items())),
            "limits": {
                "serialized_bytes": MAX_AGENT_CONTEXT_BYTES,
                "string_characters": MAX_AGENT_CONTEXT_STRING_CHARS,
                "default_list_items": DEFAULT_AGENT_LIST_LIMIT,
                "list_items": {
                    ".".join(path): limit
                    for path, limit in sorted(_LIST_LIMITS.items())
                },
                "omission_records": MAX_AGENT_CONTEXT_OMISSION_RECORDS,
            },
        }


def _bounded_copy(value: object, path: tuple[str, ...], coverage: _Coverage):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= MAX_AGENT_CONTEXT_STRING_CHARS:
            return value
        coverage.record(
            path, "string_characters",
            len(value) - MAX_AGENT_CONTEXT_STRING_CHARS,
        )
        return value[:MAX_AGENT_CONTEXT_STRING_CHARS] + "…"
    if isinstance(value, list):
        limit = _LIST_LIMITS.get(path, DEFAULT_AGENT_LIST_LIMIT)
        if len(value) > limit:
            coverage.record(path, "list_items", len(value) - limit)
        return [
            _bounded_copy(item, (*path, str(index)), coverage)
            for index, item in enumerate(value[:limit])
        ]
    if isinstance(value, dict):
        # Evidence/glossary schemas have bounded, known string keys. Refuse an
        # unexpected in-memory shape instead of guessing how to serialize it.
        if not all(isinstance(key, str) for key in value):
            raise AgentContextError(
                f"agent context field {'.'.join(path) or '<root>'} has a "
                "non-string object key"
            )
        return {
            key: _bounded_copy(item, (*path, key), coverage)
            for key, item in value.items()
        }
    raise AgentContextError(
        f"agent context field {'.'.join(path) or '<root>'} has unsupported "
        f"type {type(value).__name__}"
    )


def build_agent_context(evidence: dict, glossary: dict | None) -> dict:
    """Project full engine evidence into the versioned agent-facing shape."""
    glossary_section: dict = {"present": glossary is not None}
    if glossary is not None:
        glossary_section.update(
            {
                "schema_version": glossary["schema_version"],
                "concepts": glossary["concepts"],
            }
        )

    # Imports are engine plumbing rather than a skill protocol field. Naming
    # candidates already carry the import-derived importance signal the agent
    # needs, without exposing an additional potentially large graph.
    source = {
        "context_schema_version": AGENT_CONTEXT_SCHEMA_VERSION,
        "generator": evidence["generator"],
        "freshness": {
            "status": "current",
            "basis": "built from repository inputs during this CLI invocation",
        },
        "repository": evidence["repository"],
        "configuration": evidence["configuration"],
        "totals": evidence["totals"],
        "languages": evidence["languages"],
        "modules": evidence["modules"],
        "files": evidence["files"],
        "vocabulary": evidence["vocabulary"],
        "terminology": evidence["terminology"],
        "naming_candidates": evidence["naming_candidates"],
        "structural_groups": evidence["structural_groups"],
        "monorepo": evidence["monorepo"],
        "skipped": evidence["skipped"],
        "glossary": glossary_section,
    }
    coverage = _Coverage()
    context = _bounded_copy(source, (), coverage)
    context["coverage"] = {
        "corpus": context["skipped"]["corpus_budget"],
        "context": coverage.as_dict(),
    }
    return context


def serialize_agent_context(context: dict) -> str:
    serialized = json.dumps(context, indent=2, sort_keys=True) + "\n"
    size = len(serialized.encode("utf-8"))
    if size > MAX_AGENT_CONTEXT_BYTES:
        raise AgentContextError(
            "agent context exceeds the "
            f"{MAX_AGENT_CONTEXT_BYTES}-byte output limit after bounded sampling"
        )
    return serialized


def inspect_command(path_arg: str, *, graphify: bool = True) -> int:
    """Build current evidence and emit only the bounded agent contract."""
    root = repo_root(path_arg)
    if root is None:
        return 1
    try:
        glossary = load_glossary(root)
    except GlossaryError as exc:
        raise AgentContextError(str(exc)) from exc
    evidence = build_evidence(root, cache=True, graphify=graphify)
    write_evidence(root, evidence)
    context = build_agent_context(evidence, glossary)
    print(serialize_agent_context(context), end="")
    return 0
