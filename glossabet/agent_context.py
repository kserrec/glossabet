"""Fresh, bounded JSON context for the installed agent skill.

The skill must not parse repository-owned machine artifacts itself.  This
module keeps path confinement, glossary validation, scanning, and output
bounding behind one CLI command while leaving the full RepositoryEvidence
artifact available to deterministic engine consumers.
"""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field

from glossabet.artifacts import ArtifactError, repo_root
from glossabet.coverage import coverage_ledger, coverage_reasons
from glossabet.evidence import build_evidence, write_evidence
from glossabet.glossary import GlossaryError, load_glossary
from glossabet.imports import module_of


AGENT_CONTEXT_SCHEMA_VERSION = 2
MAX_AGENT_CONTEXT_BYTES = 1_000_000
ROUTINE_AGENT_CONTEXT_TARGET_BYTES = 80_000
MAX_AGENT_CONTEXT_STRING_CHARS = 512
MAX_AGENT_CONTEXT_OMISSION_RECORDS = 100
DEFAULT_AGENT_LIST_LIMIT = 50
REGISTER_EXEMPLAR_LIMIT = 24

# Routine context favors the evidence the skill actually consumes. The full
# bounded engine evidence remains in evidence.json for deterministic commands;
# every projection omission is explicit in coverage.context.
_LIST_LIMITS: dict[tuple[str, ...], int] = {
    ("modules",): 150,
    ("files", "code"): 250,
    ("files", "docs"): 150,
    ("vocabulary", "tokens", "items"): 100,
    ("vocabulary", "identifiers", "items"): 50,
    ("vocabulary", "doc_terms", "items"): 50,
    ("structural_groups", "groups"): 100,
    ("glossary", "concepts"): 200,
}

# ``inspect --full`` preserves the detailed pre-Phase-27 collection shape.
_FULL_LIST_LIMITS: dict[tuple[str, ...], int] = {
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

    def as_dict(
        self,
        *,
        projection: str,
        list_limits: dict[tuple[str, ...], int],
    ) -> dict:
        return {
            "complete": not self.omissions,
            "projection": projection,
            "omissions": self.omissions,
            "affected_sections": sorted(self.affected_sections),
            "omission_counts": dict(sorted(self.omission_counts.items())),
            "omitted_amounts": dict(sorted(self.omitted_amounts.items())),
            "limits": {
                "serialized_bytes": MAX_AGENT_CONTEXT_BYTES,
                "routine_target_bytes": ROUTINE_AGENT_CONTEXT_TARGET_BYTES,
                "string_characters": MAX_AGENT_CONTEXT_STRING_CHARS,
                "default_list_items": DEFAULT_AGENT_LIST_LIMIT,
                "list_items": {
                    ".".join(path): limit
                    for path, limit in sorted(list_limits.items())
                },
                "omission_records": MAX_AGENT_CONTEXT_OMISSION_RECORDS,
                "register_exemplars": REGISTER_EXEMPLAR_LIMIT,
            },
        }


def _bounded_copy(
    value: object,
    path: tuple[str, ...],
    coverage: _Coverage,
    list_limits: dict[tuple[str, ...], int],
):
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
        limit = list_limits.get(path, DEFAULT_AGENT_LIST_LIMIT)
        if len(value) > limit:
            coverage.record(path, "list_items", len(value) - limit)
        return [
            _bounded_copy(item, (*path, str(index)), coverage, list_limits)
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
            key: _bounded_copy(item, (*path, key), coverage, list_limits)
            for key, item in value.items()
        }
    raise AgentContextError(
        f"agent context field {'.'.join(path) or '<root>'} has unsupported "
        f"type {type(value).__name__}"
    )


def _module_rollup_section(
    section: dict,
    section_name: str,
    coverage: _Coverage,
) -> dict:
    """Replace repeated file paths with compact per-module occurrence counts."""
    projected = {
        key: deepcopy(value)
        for key, value in section.items()
        if key != "items"
    }
    projected_items = []
    location_records = 0
    for item in section["items"]:
        locations = item.get("locations", [])
        location_records += len(locations)
        module_counts: Counter[str] = Counter()
        for location in locations:
            module_counts[module_of(location["path"])] += location["count"]
        projected_item = {
            key: deepcopy(value)
            for key, value in item.items()
            if key not in {"locations", "locations_truncated"}
        }
        projected_item["module_counts"] = dict(sorted(module_counts.items()))
        projected_item["module_counts_truncated"] = bool(
            item.get("locations_truncated", False)
        )
        projected_items.append(projected_item)
    projected["items"] = projected_items
    if location_records:
        coverage.record(
            ("vocabulary", section_name, "items", "*", "locations"),
            "file_locations_rolled_up",
            location_records,
        )
    return projected


def _identifier_style(name: str) -> str:
    core = name.strip("_")
    if "_" in core:
        return "UPPER_SNAKE" if core.isupper() else "snake_case"
    if core.isupper():
        return "upper"
    if core[:1].isupper():
        return (
            "PascalCase"
            if any(character.islower() for character in core)
            else "upper"
        )
    if any(character.isupper() for character in core):
        return "camelCase"
    return "flat"


def _register_exemplars(identifier_section: dict, coverage: _Coverage) -> dict:
    eligible = []
    for item in identifier_section["items"]:
        style = _identifier_style(item["name"])
        if len(item["tokens"]) < 2 or style not in {
            "snake_case", "camelCase", "PascalCase", "UPPER_SNAKE",
        }:
            continue
        eligible.append({**deepcopy(item), "style": style})
    kept = eligible[:REGISTER_EXEMPLAR_LIMIT]
    if len(eligible) > len(kept):
        coverage.record(
            ("terminology", "register", "exemplars", "items"),
            "list_items",
            len(eligible) - len(kept),
        )
    source_coverage = identifier_section["coverage"]
    reasons = coverage_reasons(source_coverage, "identifier input")
    if len(eligible) > REGISTER_EXEMPLAR_LIMIT:
        reasons.append(
            f"register exemplar display cap is {REGISTER_EXEMPLAR_LIMIT} items"
        )
    return {
        "items": kept,
        "coverage": coverage_ledger(
            len(eligible),
            len(kept),
            total_items_exact=source_coverage["complete"],
            reasons=reasons,
        ),
    }


def _naming_with_locations(evidence: dict, coverage: _Coverage) -> dict:
    naming = deepcopy(evidence["naming_candidates"])
    token_entries = {
        item["term"]: item for item in evidence["vocabulary"]["tokens"]["items"]
    }
    unavailable = 0
    terms = []
    for item in naming["terms"]:
        projected = deepcopy(item)
        source = token_entries.get(item["term"])
        if source is None:
            unavailable += 1
            projected["locations"] = []
            projected["locations_truncated"] = True
        else:
            projected["locations"] = deepcopy(source["locations"])
            projected["locations_truncated"] = source["locations_truncated"]
        terms.append(projected)
    naming["terms"] = terms
    if unavailable:
        coverage.record(
            ("naming_candidates", "terms", "*", "locations"),
            "source_items_unavailable",
            unavailable,
        )
    return naming


def build_agent_context(
    evidence: dict,
    glossary: dict | None,
    *,
    full: bool = False,
) -> dict:
    """Project full engine evidence into the versioned agent-facing shape."""
    glossary_section: dict = {"present": glossary is not None}
    if glossary is not None:
        glossary_section.update(
            {
                "schema_version": glossary["schema_version"],
                "concepts": glossary["concepts"],
            }
        )

    coverage = _Coverage()
    projection = "full" if full else "lean"
    list_limits = _FULL_LIST_LIMITS if full else _LIST_LIMITS

    # Imports are engine plumbing rather than a skill protocol field. Naming
    # candidates already carry the import-derived importance signal the agent
    # needs, without exposing an additional potentially large graph. Record the
    # section exclusion so context completeness is always literal.
    coverage.record(("imports",), "section_excluded", 1)

    vocabulary = deepcopy(evidence["vocabulary"])
    terminology = deepcopy(evidence["terminology"])
    naming_candidates = deepcopy(evidence["naming_candidates"])
    if not full:
        vocabulary = {
            "normalization": deepcopy(evidence["vocabulary"]["normalization"]),
            "tokens": _module_rollup_section(
                evidence["vocabulary"]["tokens"], "tokens", coverage
            ),
            "identifiers": _module_rollup_section(
                evidence["vocabulary"]["identifiers"], "identifiers", coverage
            ),
            "doc_terms": _module_rollup_section(
                evidence["vocabulary"]["doc_terms"], "doc_terms", coverage
            ),
        }
        terminology["register"]["exemplars"] = _register_exemplars(
            evidence["vocabulary"]["identifiers"], coverage
        )
        naming_candidates = _naming_with_locations(evidence, coverage)

    source = {
        "context_schema_version": AGENT_CONTEXT_SCHEMA_VERSION,
        "evidence_schema_version": evidence["schema_version"],
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
        "vocabulary": vocabulary,
        "terminology": terminology,
        "naming_candidates": naming_candidates,
        "structural_groups": evidence["structural_groups"],
        "monorepo": evidence["monorepo"],
        "skipped": evidence["skipped"],
        "glossary": glossary_section,
    }
    context = _bounded_copy(source, (), coverage, list_limits)
    context["coverage"] = {
        "corpus": context["skipped"]["corpus_budget"],
        "context": coverage.as_dict(
            projection=projection,
            list_limits=list_limits,
        ),
    }
    return context


def serialize_agent_context(context: dict) -> str:
    serialized = json.dumps(
        context,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"
    size = len(serialized.encode("utf-8"))
    if size > MAX_AGENT_CONTEXT_BYTES:
        raise AgentContextError(
            "agent context exceeds the "
            f"{MAX_AGENT_CONTEXT_BYTES}-byte output limit after bounded sampling"
        )
    return serialized


def inspect_command(
    path_arg: str,
    *,
    graphify: bool = True,
    full: bool = False,
) -> int:
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
    context = build_agent_context(evidence, glossary, full=full)
    print(serialize_agent_context(context), end="")
    return 0
