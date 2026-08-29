"""Project and serialize fresh, bounded JSON for the installed agent skill.

The versioned shapes live in :mod:`glossabet.agent.agent_context_protocol`.
The skill must not parse repository-owned machine artifacts itself. This
module keeps path confinement, glossary validation, scanning, projection, and
output bounding behind one CLI command while leaving the full
RepositoryEvidence artifact available to deterministic engine consumers.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TypeVar, cast

from glossabet.agent.agent_context_protocol import (
    AGENT_CONTEXT_SCHEMA_VERSION,
    AgentContextCoverage,
    AgentContextDocument,
    ContextCoverage,
    ContextCoverageRecord,
    ContextFreshness,
    ContextGlossarySection,
    ContextLimits,
    ContextNamingCandidates,
    ContextRegisterSection,
    ContextTermCandidate,
    ContextTerminology,
    LeanVocabularySection,
    ModuleRollupEntry,
    ModuleRollupTable,
    Projection,
    RegisterExemplar,
    RegisterExemplars,
    _ContextSource,
)
from glossabet.analysis.evidence import persist_evidence
from glossabet.analysis.evidence_types import (
    EvidenceDocument,
    IdentifierTable,
    NamingCandidates,
    TerminologySection,
    VocabularySection,
    VocabularyTable,
)
from glossabet.command_run import GLOSSARY_OPTIONAL, open_run
from glossabet.corpus.imports import module_of
from glossabet.corpus.tokenize import (
    STRUCTURED_IDENTIFIER_STYLES,
    identifier_style,
)
from glossabet.glossary.model import GlossaryDocument
from glossabet.glossary.repository_glossary import (
    RepositoryGlossarySection,
    repository_glossary_section,
)
from glossabet.runtime.artifacts import ArtifactError
from glossabet.runtime.coverage import (
    capped_collection,
    coverage_reasons,
)

# Compatibility boundary: these protocol types remain importable from this
# module; their definitions and new imports belong to agent_context_protocol.
_PROTOCOL_COMPATIBILITY_TYPES = (
    AgentContextCoverage,
    ContextFreshness,
    ContextLimits,
)

MAX_AGENT_CONTEXT_BYTES = 1_000_000
ROUTINE_AGENT_CONTEXT_TARGET_BYTES = 110_000
MAX_AGENT_CONTEXT_STRING_CHARS = 512
MAX_AGENT_CONTEXT_COVERAGE_RECORDS = 100
DEFAULT_AGENT_LIST_LIMIT = 50
REGISTER_EXEMPLAR_LIMIT = 24

# Routine context favors the evidence the skill actually consumes. The full
# bounded engine evidence remains in evidence.json for deterministic commands;
# every designed exclusion or lost detail is explicit in coverage.context.
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

# ``inspect --full`` keeps the detailed per-item collection shape (every
# location list in place) that the routine rollup projection replaced.
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
class _ProjectionCoverage:
    intentional_exclusions: list[ContextCoverageRecord] = field(
        default_factory=list
    )
    source_omissions: list[ContextCoverageRecord] = field(default_factory=list)
    truncations: list[ContextCoverageRecord] = field(default_factory=list)

    def _record(
        self,
        records: list[ContextCoverageRecord],
        path: tuple[str, ...],
        kind: str,
        amount: int,
    ) -> None:
        # One record per (pattern, kind): every list index folds to ``*``,
        # so 500 long glossary definitions are one
        # ``glossary.concepts.*.definition`` record whose amount is the sum,
        # not 500 records that exhaust the ceiling and fail the command for
        # a glossary the engine itself accepted.
        pattern = ".".join("*" if part.isdigit() else part for part in path)
        for record in records:
            if record["path"] == pattern and record["kind"] == kind:
                record["amount"] += amount
                break
        else:
            record_count = (
                len(self.intentional_exclusions)
                + len(self.source_omissions)
                + len(self.truncations)
            )
            if record_count >= MAX_AGENT_CONTEXT_COVERAGE_RECORDS:
                raise AgentContextError(
                    "agent context requires more than "
                    f"{MAX_AGENT_CONTEXT_COVERAGE_RECORDS} coverage records"
                )
            records.append(
                {"path": pattern, "kind": kind, "amount": amount}
            )

    def exclude(self, path: tuple[str, ...], kind: str, amount: int) -> None:
        self._record(self.intentional_exclusions, path, kind, amount)

    def omit_source(self, path: tuple[str, ...], kind: str, amount: int) -> None:
        self._record(self.source_omissions, path, kind, amount)

    def truncate(self, path: tuple[str, ...], kind: str, amount: int) -> None:
        self._record(self.truncations, path, kind, amount)

    def as_dict(
        self,
        *,
        projection: Projection,
        list_limits: Mapping[tuple[str, ...], int],
        source_complete: bool,
    ) -> ContextCoverage:
        applied_list_limits = dict(list_limits)
        if projection == "lean":
            applied_list_limits[
                ("terminology", "register", "exemplars", "items")
            ] = REGISTER_EXEMPLAR_LIMIT
        return {
            "projection": projection,
            "projection_complete": not self.truncations,
            "source_complete": source_complete and not self.source_omissions,
            "intentional_exclusions": self.intentional_exclusions,
            "source_omissions": self.source_omissions,
            "truncations": self.truncations,
            "applied_limits": {
                "serialized_bytes": MAX_AGENT_CONTEXT_BYTES,
                "string_characters": MAX_AGENT_CONTEXT_STRING_CHARS,
                "default_list_items": DEFAULT_AGENT_LIST_LIMIT,
                "list_items": {
                    ".".join(path): limit
                    for path, limit in sorted(applied_list_limits.items())
                },
                "coverage_records": MAX_AGENT_CONTEXT_COVERAGE_RECORDS,
            },
        }


_Section = TypeVar("_Section")


def _bounded_copy(
    value: object,
    path: tuple[str, ...],
    coverage: _ProjectionCoverage,
    list_limits: Mapping[tuple[str, ...], int],
) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= MAX_AGENT_CONTEXT_STRING_CHARS:
            return value
        coverage.truncate(
            path, "string_characters",
            len(value) - MAX_AGENT_CONTEXT_STRING_CHARS,
        )
        return value[:MAX_AGENT_CONTEXT_STRING_CHARS] + "…"
    if isinstance(value, list):
        limit = list_limits.get(path, DEFAULT_AGENT_LIST_LIMIT)
        if len(value) > limit:
            coverage.truncate(path, "list_items", len(value) - limit)
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


def _bounded(
    section: _Section,
    coverage: _ProjectionCoverage,
    list_limits: Mapping[tuple[str, ...], int],
) -> _Section:
    """Bound a whole document. Bounding preserves shape — every key, scalar
    type, and list element type survives; only string lengths and list
    lengths shrink — so the bounded value has the document's own type. The
    cast states that invariant of ``_bounded_copy`` for the type checker."""
    return cast(_Section, _bounded_copy(section, (), coverage, list_limits))


def _module_rollup_section(
    section: VocabularyTable,
    section_name: str,
    coverage: _ProjectionCoverage,
) -> ModuleRollupTable:
    """Replace repeated file paths with compact per-module occurrence counts."""
    projected_items: list[ModuleRollupEntry] = []
    location_records = 0
    for item in section["items"]:
        locations = item.get("locations", [])
        location_records += len(locations)
        module_counts: Counter[str] = Counter()
        for location in locations:
            module_counts[module_of(location["path"])] += location["count"]
        projected_item: ModuleRollupEntry = {
            key: deepcopy(value)
            for key, value in item.items()
            if key not in {"locations", "locations_truncated"}
        }
        projected_item["module_counts"] = dict(sorted(module_counts.items()))
        projected_item["module_counts_truncated"] = bool(
            item.get("locations_truncated", False)
        )
        projected_items.append(projected_item)
    if location_records:
        coverage.exclude(
            ("vocabulary", section_name, "items", "*", "locations"),
            "file_locations_rolled_up",
            location_records,
        )
    return {
        "items": projected_items,
        "truncated": deepcopy(section["truncated"]),
        "coverage": deepcopy(section["coverage"]),
    }


def _register_exemplars(
    identifier_section: IdentifierTable,
    projection_coverage: _ProjectionCoverage,
) -> RegisterExemplars:
    eligible: list[RegisterExemplar] = []
    for item in identifier_section["items"]:
        style = identifier_style(item["name"])
        if len(item["tokens"]) < 2 or style not in STRUCTURED_IDENTIFIER_STYLES:
            continue
        exemplar: RegisterExemplar = {**deepcopy(item), "style": style}
        eligible.append(exemplar)
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
        projection_coverage.truncate(
            ("terminology", "register", "exemplars", "items"),
            "list_items",
            len(eligible) - len(kept),
        )
    return {"items": kept, "coverage": coverage}


def _naming_with_locations(
    evidence: EvidenceDocument,
    projection_coverage: _ProjectionCoverage,
) -> ContextNamingCandidates:
    naming = deepcopy(evidence["naming_candidates"])
    token_entries = {
        item["term"]: item for item in evidence["vocabulary"]["tokens"]["items"]
    }
    unavailable = 0
    terms: list[ContextTermCandidate] = []
    for item in naming["terms"]:
        source = token_entries.get(item["term"])
        projected: ContextTermCandidate
        if source is None:
            unavailable += 1
            projected = {
                **deepcopy(item),
                "locations": [],
                "locations_truncated": True,
            }
        else:
            projected = {
                **deepcopy(item),
                "locations": deepcopy(source["locations"]),
                "locations_truncated": source["locations_truncated"],
            }
        terms.append(projected)
    if unavailable:
        projection_coverage.omit_source(
            ("naming_candidates", "terms", "*", "locations"),
            "source_items_unavailable",
            unavailable,
        )
    return {
        "modules": naming["modules"],
        "modules_dropped": naming["modules_dropped"],
        "terms": terms,
        "terms_dropped": naming["terms_dropped"],
        "structures": naming["structures"],
        "structures_dropped": naming["structures_dropped"],
        "structures_source_groups_dropped": naming["structures_source_groups_dropped"],
        "structures_complete": naming["structures_complete"],
        "coverage": naming["coverage"],
    }


def _context_terminology(section: TerminologySection) -> ContextTerminology:
    """A deep copy of the terminology section whose register can take the
    lean projection's exemplars."""
    copied = deepcopy(section)
    register: ContextRegisterSection = {**copied["register"]}
    return {
        "considered_tokens": copied["considered_tokens"],
        "vocabulary_size": copied["vocabulary_size"],
        "domain_vocabulary_size": copied["domain_vocabulary_size"],
        "language_vocabulary_size": copied["language_vocabulary_size"],
        "coverage": copied["coverage"],
        "register": register,
        "layers": copied["layers"],
        "synonym_candidates": copied["synonym_candidates"],
        "context_dispersion": copied["context_dispersion"],
        "overload_candidates": copied["overload_candidates"],
        "scope": copied["scope"],
    }


def build_agent_context(
    evidence: EvidenceDocument,
    glossary: GlossaryDocument | None,
    *,
    repository_glossary: RepositoryGlossarySection | None = None,
    full: bool = False,
) -> AgentContextDocument:
    """Project full engine evidence into the versioned agent-facing shape.

    ``glossary`` is Glossabet-managed structured state (glossary.json);
    ``repository_glossary`` is the discovery record for the repository's own
    root GLOSSARY.md (metadata only, never content). They are two distinct
    channels and are never merged or overloaded.
    """
    glossary_section: ContextGlossarySection = {"present": glossary is not None}
    if glossary is not None:
        glossary_section["schema_version"] = glossary["schema_version"]
        glossary_section["concepts"] = glossary["concepts"]

    projection_coverage = _ProjectionCoverage()
    projection: Projection = "full" if full else "lean"
    list_limits = _FULL_LIST_LIMITS if full else _LIST_LIMITS

    # Imports are engine plumbing rather than a skill protocol field. Naming
    # candidates already carry the import-derived importance signal the agent
    # needs, without exposing an additional potentially large graph. Record the
    # section exclusion so the selected protocol shape stays explicit.
    projection_coverage.exclude(("imports",), "section_excluded", 1)

    terminology = _context_terminology(evidence["terminology"])
    vocabulary: VocabularySection | LeanVocabularySection
    naming_candidates: NamingCandidates | ContextNamingCandidates
    if full:
        vocabulary = deepcopy(evidence["vocabulary"])
        naming_candidates = deepcopy(evidence["naming_candidates"])
    else:
        vocabulary = {
            "normalization": deepcopy(evidence["vocabulary"]["normalization"]),
            "tokens": _module_rollup_section(
                evidence["vocabulary"]["tokens"], "tokens", projection_coverage
            ),
            "identifiers": _module_rollup_section(
                evidence["vocabulary"]["identifiers"],
                "identifiers",
                projection_coverage,
            ),
            "doc_terms": _module_rollup_section(
                evidence["vocabulary"]["doc_terms"],
                "doc_terms",
                projection_coverage,
            ),
        }
        terminology["register"]["exemplars"] = _register_exemplars(
            evidence["vocabulary"]["identifiers"], projection_coverage
        )
        naming_candidates = _naming_with_locations(evidence, projection_coverage)

    source: _ContextSource = {
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
        "repository_glossary": (
            {"present": False, "nested_ignored": []}
            if repository_glossary is None
            else repository_glossary
        ),
    }
    bounded = _bounded(source, projection_coverage, list_limits)
    context: AgentContextDocument = {
        **bounded,
        "coverage": {
            "corpus": bounded["skipped"]["corpus_budget"],
            "context": projection_coverage.as_dict(
                projection=projection,
                list_limits=list_limits,
                source_complete=bounded["skipped"]["corpus_budget"]["complete"],
            ),
        },
    }
    return context


def serialize_agent_context(context: AgentContextDocument) -> str:
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
