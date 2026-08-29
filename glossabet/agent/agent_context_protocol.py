"""Versioned data model for the agent-context protocol.

Projection mechanics live in :mod:`glossabet.agent.agent_context`. Keeping the
shape here lets protocol consumers inspect the contract without depending on
repository scanning, command dispatch, bounding, or serialization behavior.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from glossabet.analysis.evidence_types import (
    ContextDispersionSection,
    FilesSection,
    GeneratorRecord,
    IdentifierEntry,
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
    TotalsRecord,
    TruncationMarker,
    VocabularySection,
)
from glossabet.corpus.config import ConfigurationEvidence
from glossabet.corpus.scanner import CorpusBudgetEvidence, MonorepoEvidence
from glossabet.corpus.tokenize import TokenizationContract
from glossabet.glossary.model import ConceptRecord
from glossabet.glossary.repository_glossary import RepositoryGlossarySection
from glossabet.runtime.coverage import CoverageLedger, LocationSample

AGENT_CONTEXT_SCHEMA_VERSION = 6

Projection = Literal["lean", "full"]


class ContextCoverageRecord(TypedDict):
    """One exclusion, source omission, or truncation.

    List indexes fold to ``*`` so repeated losses with the same meaning can be
    coalesced without hiding their total amount.
    """

    path: str
    kind: str
    amount: int


class ContextLimits(TypedDict):
    serialized_bytes: int
    string_characters: int
    default_list_items: int
    list_items: dict[str, int]
    coverage_records: int


class ContextCoverage(TypedDict):
    """The selected projection, its source/projection truth, and why."""

    projection: Projection
    projection_complete: bool
    source_complete: bool
    intentional_exclusions: list[ContextCoverageRecord]
    source_omissions: list[ContextCoverageRecord]
    truncations: list[ContextCoverageRecord]
    applied_limits: ContextLimits


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
    """AgentContext v6: what ``inspect`` prints."""

    coverage: AgentContextCoverage
