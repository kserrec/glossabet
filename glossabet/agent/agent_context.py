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

from glossabet.runtime.artifacts import ArtifactError
from glossabet.runtime.coverage import capped_collection, coverage_reasons
from glossabet.runtime.engine_run import GLOSSARY_OPTIONAL, open_run
from glossabet.analysis.evidence import persist_evidence
from glossabet.analysis.evidence_view import EvidenceView
from glossabet.glossary.repository_glossary import repository_glossary_section
from glossabet.corpus.imports import module_of
from glossabet.corpus.tokenize import STRUCTURED_IDENTIFIER_STYLES, identifier_style


AGENT_CONTEXT_SCHEMA_VERSION = 3
MAX_AGENT_CONTEXT_BYTES = 1_000_000
ROUTINE_AGENT_CONTEXT_TARGET_BYTES = 100_000
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
    ("repository_glossary", "nested_ignored"): 50,
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
    ("repository_glossary", "nested_ignored"): 50,
}


class AgentContextError(ArtifactError):
    """A safe agent context could not be produced within its contract."""


@dataclass
class _ProjectionOmissions:
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
    omissions: _ProjectionOmissions,
    list_limits: dict[tuple[str, ...], int],
):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= MAX_AGENT_CONTEXT_STRING_CHARS:
            return value
        omissions.record(
            path, "string_characters",
            len(value) - MAX_AGENT_CONTEXT_STRING_CHARS,
        )
        return value[:MAX_AGENT_CONTEXT_STRING_CHARS] + "…"
    if isinstance(value, list):
        limit = list_limits.get(path, DEFAULT_AGENT_LIST_LIMIT)
        if len(value) > limit:
            omissions.record(path, "list_items", len(value) - limit)
        return [
            _bounded_copy(item, (*path, str(index)), omissions, list_limits)
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
            key: _bounded_copy(item, (*path, key), omissions, list_limits)
            for key, item in value.items()
        }
    raise AgentContextError(
        f"agent context field {'.'.join(path) or '<root>'} has unsupported "
        f"type {type(value).__name__}"
    )


def _module_rollup_section(
    section: dict,
    section_name: str,
    omissions: _ProjectionOmissions,
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
        omissions.record(
            ("vocabulary", section_name, "items", "*", "locations"),
            "file_locations_rolled_up",
            location_records,
        )
    return projected


def _register_exemplars(
    identifier_section: dict,
    omissions: _ProjectionOmissions,
) -> dict:
    eligible = []
    for item in identifier_section["items"]:
        style = identifier_style(item["name"])
        if len(item["tokens"]) < 2 or style not in STRUCTURED_IDENTIFIER_STYLES:
            continue
        eligible.append({**deepcopy(item), "style": style})
    source_ledger = identifier_section["coverage"]
    kept, coverage = capped_collection(
        eligible,
        REGISTER_EXEMPLAR_LIMIT,
        cap_reason=(
            f"register exemplar display cap is {REGISTER_EXEMPLAR_LIMIT} items"
        ),
        total_items_exact=source_ledger["complete"],
        incomplete_reasons=coverage_reasons(source_ledger, "identifier input"),
    )
    if len(eligible) > len(kept):
        omissions.record(
            ("terminology", "register", "exemplars", "items"),
            "list_items",
            len(eligible) - len(kept),
        )
    return {"items": kept, "coverage": coverage}


def _naming_with_locations(
    view: EvidenceView,
    omissions: _ProjectionOmissions,
) -> dict:
    naming = deepcopy(view.naming_candidates())
    token_entries = {
        item["term"]: item for item in view.vocabulary_table("tokens")["items"]
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
        omissions.record(
            ("naming_candidates", "terms", "*", "locations"),
            "source_items_unavailable",
            unavailable,
        )
    return naming


def build_agent_context(
    evidence: dict,
    glossary: dict | None,
    *,
    repository_glossary: dict | None = None,
    full: bool = False,
) -> dict:
    """Project full engine evidence into the versioned agent-facing shape.

    ``glossary`` is Glossabet-managed structured state (glossary.json);
    ``repository_glossary`` is the discovery record for the repository's own
    root GLOSSARY.md (metadata only, never content). They are two distinct
    channels and are never merged or overloaded.
    """
    glossary_section: dict = {"present": glossary is not None}
    if glossary is not None:
        glossary_section.update(
            {
                "schema_version": glossary["schema_version"],
                "concepts": glossary["concepts"],
            }
        )

    omissions = _ProjectionOmissions()
    projection = "full" if full else "lean"
    list_limits = _FULL_LIST_LIMITS if full else _LIST_LIMITS

    # Imports are engine plumbing rather than a skill protocol field. Naming
    # candidates already carry the import-derived importance signal the agent
    # needs, without exposing an additional potentially large graph. Record the
    # section exclusion so context completeness is always literal.
    omissions.record(("imports",), "section_excluded", 1)

    view = EvidenceView(evidence)
    terminology = deepcopy(view.terminology())
    if full:
        vocabulary = deepcopy(view.vocabulary())
        naming_candidates = deepcopy(view.naming_candidates())
    else:
        vocabulary = {
            "normalization": deepcopy(view.normalization()),
            "tokens": _module_rollup_section(
                view.vocabulary_table("tokens"), "tokens", omissions
            ),
            "identifiers": _module_rollup_section(
                view.vocabulary_table("identifiers"), "identifiers", omissions
            ),
            "doc_terms": _module_rollup_section(
                view.vocabulary_table("doc_terms"), "doc_terms", omissions
            ),
        }
        terminology["register"]["exemplars"] = _register_exemplars(
            view.vocabulary_table("identifiers"), omissions
        )
        naming_candidates = _naming_with_locations(view, omissions)

    source = {
        "context_schema_version": AGENT_CONTEXT_SCHEMA_VERSION,
        "evidence_schema_version": view.schema_version(),
        "generator": view.generator(),
        "freshness": {
            "status": "current",
            "basis": "built from repository inputs during this CLI invocation",
        },
        "repository": view.repository(),
        "configuration": view.configuration(),
        "totals": view.totals(),
        "languages": view.languages(),
        "modules": view.modules(),
        "files": view.files(),
        "vocabulary": vocabulary,
        "terminology": terminology,
        "naming_candidates": naming_candidates,
        "structural_groups": view.structural_groups(),
        "monorepo": view.monorepo(),
        "skipped": view.skipped(),
        "glossary": glossary_section,
        "repository_glossary": (
            {"present": False, "nested_ignored": []}
            if repository_glossary is None
            else repository_glossary
        ),
    }
    context = _bounded_copy(source, (), omissions, list_limits)
    context["coverage"] = {
        "corpus": context["skipped"]["corpus_budget"],
        "context": omissions.as_dict(
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
        allow_nan=False,
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
    run = open_run(path_arg, glossary=GLOSSARY_OPTIONAL)
    evidence = persist_evidence(run.root, graphify=graphify)
    context = build_agent_context(
        evidence,
        run.glossary,
        repository_glossary=repository_glossary_section(
            run.root, evidence, run.glossary
        ),
        full=full,
    )
    print(serialize_agent_context(context), end="")
    return 0
