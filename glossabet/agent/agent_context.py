"""Fresh, bounded JSON context for the installed agent skill.

The skill must not parse repository-owned machine artifacts itself.  This
module keeps path confinement, glossary validation, scanning, and output
bounding behind one CLI command while leaving the full RepositoryEvidence
artifact available to deterministic engine consumers.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal, TypedDict, TypeVar, cast

from glossabet.analysis.evidence import persist_evidence
from glossabet.analysis.evidence_types import (
    ContextDispersionSection,
    EvidenceDocument,
    FilesSection,
    GeneratorRecord,
    IdentifierEntry,
    IdentifierTable,
    LayersSection,
    ModuleCandidate,
    ModuleRecord,
    NamingCandidates,
    NamingCoverage,
    OverloadCandidatesSection,
    RegisterSection,
    RepositoryRecord,
    SkippedSection,
    StructuralGroups,
    StructureCandidate,
    SynonymCandidatesSection,
    TermCandidate,
    TerminologyCoverage,
    TerminologyScope,
    TerminologySection,
    TotalsRecord,
    TruncationMarker,
    VocabularySection,
    VocabularyTable,
)
from glossabet.analysis.evidence_view import EvidenceView
from glossabet.corpus.config import ConfigurationEvidence
from glossabet.corpus.imports import module_of
from glossabet.corpus.scanner import CorpusBudgetEvidence, MonorepoEvidence
from glossabet.corpus.tokenize import (
    STRUCTURED_IDENTIFIER_STYLES,
    TokenizationContract,
    identifier_style,
)
from glossabet.glossary.model import ConceptRecord, GlossaryDocument
from glossabet.glossary.repository_glossary import (
    RepositoryGlossarySection,
    repository_glossary_section,
)
from glossabet.runtime.artifacts import ArtifactError
from glossabet.runtime.coverage import (
    CoverageLedger,
    LocationSample,
    capped_collection,
    coverage_reasons,
)
from glossabet.runtime.engine_run import GLOSSARY_OPTIONAL, open_run

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


# -- the AgentContext v3 document -------------------------------------------

Projection = Literal["lean", "full"]


class ContextOmission(TypedDict):
    """One bounded-projection omission: a key pattern (list indexes folded
    to ``*``), what was left out, and how much."""

    path: str
    kind: str
    amount: int


class ContextLimits(TypedDict):
    serialized_bytes: int
    routine_target_bytes: int
    string_characters: int
    default_list_items: int
    list_items: dict[str, int]
    omission_records: int
    register_exemplars: int


class ContextCoverage(TypedDict):
    """``coverage.context``: whether the projection is complete and every
    reason it is not."""

    complete: bool
    projection: Projection
    omissions: list[ContextOmission]
    affected_sections: list[str]
    omission_counts: dict[str, int]
    omitted_amounts: dict[str, int]
    limits: ContextLimits


class AgentContextCoverage(TypedDict):
    corpus: CorpusBudgetEvidence
    context: ContextCoverage


class ContextFreshness(TypedDict):
    status: str
    basis: str


class _ContextGlossaryRequired(TypedDict):
    present: bool


class ContextGlossarySection(_ContextGlossaryRequired, total=False):
    """The managed glossary as the skill sees it; the optional keys are
    present exactly when the glossary is."""

    schema_version: int
    concepts: list[ConceptRecord]


# A vocabulary entry with its file locations rolled up into per-module
# counts. The rollup keeps every other key of the table's own entry type
# (token, identifier, or doc-term), so the three shapes share one mapping.
ModuleRollupEntry = dict[str, object]


class ModuleRollupTable(TypedDict):
    items: list[ModuleRollupEntry]
    truncated: TruncationMarker | None
    coverage: CoverageLedger


class LeanVocabularySection(TypedDict):
    normalization: TokenizationContract
    tokens: ModuleRollupTable
    identifiers: ModuleRollupTable
    doc_terms: ModuleRollupTable


class RegisterExemplar(IdentifierEntry):
    style: str


class RegisterExemplars(TypedDict):
    items: list[RegisterExemplar]
    coverage: CoverageLedger


class ContextRegisterSection(RegisterSection, total=False):
    exemplars: RegisterExemplars


class ContextTerminology(TypedDict):
    """The evidence terminology section whose register may carry the lean
    projection's exemplars."""

    considered_tokens: int
    vocabulary_size: int
    domain_vocabulary_size: int
    language_vocabulary_size: int
    coverage: TerminologyCoverage
    register: ContextRegisterSection
    layers: LayersSection
    synonym_candidates: SynonymCandidatesSection
    context_dispersion: ContextDispersionSection
    overload_candidates: OverloadCandidatesSection
    scope: TerminologyScope


class ContextTermCandidate(TermCandidate):
    locations: list[LocationSample]
    locations_truncated: bool


class ContextNamingCandidates(TypedDict):
    """``naming_candidates`` with each term's source locations attached."""

    modules: list[ModuleCandidate]
    modules_dropped: int
    terms: list[ContextTermCandidate]
    terms_dropped: int
    structures: list[StructureCandidate]
    structures_dropped: int
    structures_source_groups_dropped: int
    structures_complete: bool
    coverage: NamingCoverage


class _ContextSource(TypedDict):
    """The projection before bounding; ``AgentContextDocument`` adds the
    coverage computed while bounding it."""

    context_schema_version: int
    evidence_schema_version: int
    generator: GeneratorRecord
    freshness: ContextFreshness
    repository: RepositoryRecord
    configuration: ConfigurationEvidence
    totals: TotalsRecord
    languages: dict[str, int]
    modules: list[ModuleRecord]
    files: FilesSection
    vocabulary: VocabularySection | LeanVocabularySection
    terminology: ContextTerminology
    naming_candidates: NamingCandidates | ContextNamingCandidates
    structural_groups: StructuralGroups
    monorepo: MonorepoEvidence
    skipped: SkippedSection
    glossary: ContextGlossarySection
    repository_glossary: RepositoryGlossarySection


class AgentContextDocument(_ContextSource):
    """AgentContext v3: what ``inspect`` prints."""

    coverage: AgentContextCoverage


@dataclass
class _ProjectionOmissions:
    omissions: list[ContextOmission] = field(default_factory=list)
    affected_sections: set[str] = field(default_factory=set)
    omission_counts: dict[str, int] = field(default_factory=dict)
    omitted_amounts: dict[str, int] = field(default_factory=dict)

    def record(self, path: tuple[str, ...], kind: str, amount: int) -> None:
        # One record per (pattern, kind): every list index folds to ``*``,
        # so 500 long glossary definitions are one
        # ``glossary.concepts.*.definition`` record whose amount is the sum,
        # not 500 records that exhaust the ceiling and fail the command for
        # a glossary the engine itself accepted.
        pattern = ".".join("*" if part.isdigit() else part for part in path)
        for record in self.omissions:
            if record["path"] == pattern and record["kind"] == kind:
                record["amount"] += amount
                break
        else:
            if len(self.omissions) >= MAX_AGENT_CONTEXT_OMISSION_RECORDS:
                raise AgentContextError(
                    "agent context requires more than "
                    f"{MAX_AGENT_CONTEXT_OMISSION_RECORDS} omission records"
                )
            self.omissions.append(
                {"path": pattern, "kind": kind, "amount": amount}
            )
        self.affected_sections.add(path[0] if path else "<root>")
        self.omission_counts[kind] = self.omission_counts.get(kind, 0) + 1
        self.omitted_amounts[kind] = self.omitted_amounts.get(kind, 0) + amount

    def as_dict(
        self,
        *,
        projection: Projection,
        list_limits: Mapping[tuple[str, ...], int],
    ) -> ContextCoverage:
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


_Section = TypeVar("_Section")


def _bounded_copy(
    value: object,
    path: tuple[str, ...],
    omissions: _ProjectionOmissions,
    list_limits: Mapping[tuple[str, ...], int],
) -> object:
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


def _bounded(
    section: _Section,
    omissions: _ProjectionOmissions,
    list_limits: Mapping[tuple[str, ...], int],
) -> _Section:
    """Bound a whole document. Bounding preserves shape — every key, scalar
    type, and list element type survives; only string lengths and list
    lengths shrink — so the bounded value has the document's own type. The
    cast states that invariant of ``_bounded_copy`` for the type checker."""
    return cast(_Section, _bounded_copy(section, (), omissions, list_limits))


def _module_rollup_section(
    section: VocabularyTable,
    section_name: str,
    omissions: _ProjectionOmissions,
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
        omissions.record(
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
    omissions: _ProjectionOmissions,
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
        omissions.record(
            ("terminology", "register", "exemplars", "items"),
            "list_items",
            len(eligible) - len(kept),
        )
    return {"items": kept, "coverage": coverage}


def _naming_with_locations(
    view: EvidenceView,
    omissions: _ProjectionOmissions,
) -> ContextNamingCandidates:
    naming = deepcopy(view.naming_candidates())
    token_entries = {
        item["term"]: item for item in view.vocabulary_table("tokens")["items"]
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
        omissions.record(
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

    omissions = _ProjectionOmissions()
    projection: Projection = "full" if full else "lean"
    list_limits = _FULL_LIST_LIMITS if full else _LIST_LIMITS

    # Imports are engine plumbing rather than a skill protocol field. Naming
    # candidates already carry the import-derived importance signal the agent
    # needs, without exposing an additional potentially large graph. Record the
    # section exclusion so context completeness is always literal.
    omissions.record(("imports",), "section_excluded", 1)

    view = EvidenceView(evidence)
    terminology = _context_terminology(view.terminology())
    vocabulary: VocabularySection | LeanVocabularySection
    naming_candidates: NamingCandidates | ContextNamingCandidates
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

    source: _ContextSource = {
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
    bounded = _bounded(source, omissions, list_limits)
    context: AgentContextDocument = {
        **bounded,
        "coverage": {
            "corpus": bounded["skipped"]["corpus_budget"],
            "context": omissions.as_dict(
                projection=projection,
                list_limits=list_limits,
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
