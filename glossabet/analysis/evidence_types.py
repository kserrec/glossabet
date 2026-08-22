"""The RepositoryEvidence contract: the persisted shape of
``glossabet-out/evidence.json`` as named types.

Every section is a ``TypedDict`` so the artifact stays plain JSON-shaped
dictionaries (no runtime object, no serialization layer) while each key
spelling and value type is checked statically. Sections whose meaning is
owned by a lower layer reuse that layer's type (coverage ledgers, the Git
stamp, corpus budget and monorepo records, imports, configuration, the
tokenization contract) rather than redeclaring its keys. Sections produced
by this layer's analyses (vocabulary tables, terminology, naming candidates,
structural groups) are declared here and returned by their producers.

``evidence.py`` assembles an ``EvidenceDocument``; ``evidence_view.py`` is
the read boundary every other module goes through.
"""

from __future__ import annotations

from typing import TypedDict

from glossabet.corpus.config import ConfigurationEvidence
from glossabet.corpus.imports import ImportsSection
from glossabet.corpus.scanner import (
    CorpusBudgetEvidence,
    MonorepoEvidence,
    SkippedPaths,
)
from glossabet.corpus.tokenize import TokenizationContract
from glossabet.runtime.coverage import CoverageLedger, LocationSample
from glossabet.runtime.git_state import GitStamp

# -- identity and inventory -------------------------------------------------

class GeneratorRecord(TypedDict):
    name: str
    version: str


class RepositoryRecord(TypedDict):
    git: GitStamp


class TotalsRecord(TypedDict):
    source_files: int
    source_bytes: int
    code_files: int
    doc_files: int
    code_files_by_role: dict[str, int]
    doc_files_by_role: dict[str, int]
    other_files: int
    code_bytes: int
    doc_words: int


class ModuleRecord(TypedDict):
    """One directory-level module of the inventory."""

    path: str
    code_files: int
    code_files_by_role: dict[str, int]
    languages: list[str]


class ProductionModuleRecord(TypedDict):
    """The production-scoped module projection naming ranks over (not
    persisted as such; it feeds ``naming_candidates``)."""

    path: str
    code_files: int
    languages: list[str]


class CodeFileEntry(TypedDict):
    path: str
    language: str
    role: str


class DocFileEntry(TypedDict):
    path: str
    role: str
    words: int


class FilesSection(TypedDict):
    code: list[CodeFileEntry]
    docs: list[DocFileEntry]


# -- vocabulary tables -------------------------------------------------------

class TruncationMarker(TypedDict):
    """What a capped vocabulary table left out; ``None`` in the table when
    nothing was."""

    dropped_terms: int
    dropped_occurrences: int


class TokenEntry(TypedDict):
    term: str
    origin: str
    count: int
    files: int
    modules: int
    locations: list[LocationSample]
    locations_truncated: bool


class IdentifierEntry(TypedDict):
    name: str
    tokens: list[str]
    count: int
    files: int
    locations: list[LocationSample]
    locations_truncated: bool


class DocTermEntry(TypedDict):
    term: str
    count: int
    files: int
    locations: list[LocationSample]
    locations_truncated: bool


class TokenTable(TypedDict):
    items: list[TokenEntry]
    truncated: TruncationMarker | None
    coverage: CoverageLedger


class IdentifierTable(TypedDict):
    items: list[IdentifierEntry]
    truncated: TruncationMarker | None
    coverage: CoverageLedger


class DocTermTable(TypedDict):
    items: list[DocTermEntry]
    truncated: TruncationMarker | None
    coverage: CoverageLedger


VocabularyEntry = TokenEntry | IdentifierEntry | DocTermEntry
VocabularyTable = TokenTable | IdentifierTable | DocTermTable


class VocabularySection(TypedDict):
    normalization: TokenizationContract
    tokens: TokenTable
    identifiers: IdentifierTable
    doc_terms: DocTermTable


# -- terminology -------------------------------------------------------------

class AffixRecord(TypedDict):
    token: str
    identifiers: int


class RegisterComposition(TypedDict):
    total_spellings: int
    used_spellings: int
    excluded_spellings: int
    used_by_reason: dict[str, int]
    excluded_by_reason: dict[str, int]


class RegisterCoverage(TypedDict):
    common_suffix_tokens: CoverageLedger
    common_prefix_tokens: CoverageLedger


class RegisterSection(TypedDict):
    unique_identifiers: int
    composition: RegisterComposition
    identifier_styles_pct: dict[str, float]
    token_count_distribution_pct: dict[str, float]
    common_suffix_tokens: list[AffixRecord]
    common_prefix_tokens: list[AffixRecord]
    coverage: RegisterCoverage


class LayerCoverage(TypedDict):
    shared_top: CoverageLedger
    code_only_top: CoverageLedger
    doc_only_top: CoverageLedger


class LayersSection(TypedDict):
    shared_top: list[str]
    code_only_top: list[str]
    doc_only_top: list[str]
    coverage: LayerCoverage


class SynonymCandidateCoverage(TypedDict):
    shared_contexts: CoverageLedger
    shared_patterns: CoverageLedger


class SynonymCandidate(TypedDict):
    a: str
    b: str
    similarity: float
    file_overlap_rate: float
    shared_contexts: list[str]
    shared_patterns: list[str]
    coverage: SynonymCandidateCoverage


class SynonymCandidatesSection(TypedDict):
    items: list[SynonymCandidate]
    considered_pairs: int
    dropped_items: int
    coverage: CoverageLedger


class DispersionRecord(TypedDict):
    term: str
    dispersion: float
    modules: int
    divergent: bool


class ContextDispersionSection(TypedDict):
    items: list[DispersionRecord]
    dropped_items: int
    coverage: CoverageLedger


class OverloadModuleCoverage(TypedDict):
    contexts: CoverageLedger


class OverloadModuleRecord(TypedDict):
    path: str
    contexts: list[str]
    coverage: OverloadModuleCoverage


class OverloadCandidateCoverage(TypedDict):
    modules: CoverageLedger


class OverloadCandidate(TypedDict):
    term: str
    dispersion: float
    modules: list[OverloadModuleRecord]
    coverage: OverloadCandidateCoverage


class OverloadCandidatesSection(TypedDict):
    items: list[OverloadCandidate]
    dropped_items: int
    coverage: CoverageLedger


class TerminologyCoverage(TypedDict):
    eligible_tokens: CoverageLedger


class TerminologyScope(TypedDict):
    roles: list[str]
    code_files: int
    doc_files: int


class TerminologyAnalysis(TypedDict):
    """What ``build_terminology`` computes; the persisted section adds the
    scan scope it was computed over."""

    considered_tokens: int
    vocabulary_size: int
    domain_vocabulary_size: int
    language_vocabulary_size: int
    coverage: TerminologyCoverage
    register: RegisterSection
    layers: LayersSection
    synonym_candidates: SynonymCandidatesSection
    context_dispersion: ContextDispersionSection
    overload_candidates: OverloadCandidatesSection


class TerminologySection(TerminologyAnalysis):
    scope: TerminologyScope


# -- naming candidates -------------------------------------------------------

class ModuleCandidate(TypedDict):
    kind: str
    path: str
    score: float
    reasons: list[str]


class TermCandidate(TypedDict):
    kind: str
    nomination_kind: str
    term: str
    score: float
    reasons: list[str]


class StructureCandidate(TypedDict):
    kind: str
    label: str
    group_id: str
    score: float
    reasons: list[str]


class LexicalNamingCoverage(TypedDict):
    modules: CoverageLedger
    terms: CoverageLedger


class LexicalNaming(TypedDict):
    """Module and term nominations from imports and vocabulary
    (``build_naming_candidates``)."""

    modules: list[ModuleCandidate]
    modules_dropped: int
    terms: list[TermCandidate]
    terms_dropped: int
    coverage: LexicalNamingCoverage


class StructureNamingCoverage(TypedDict):
    structures: CoverageLedger


class StructureNaming(TypedDict):
    """Structure nominations from Graphify groups (``structure_candidates``)."""

    structures: list[StructureCandidate]
    structures_dropped: int
    structures_source_groups_dropped: int
    structures_complete: bool
    coverage: StructureNamingCoverage


class NamingCoverage(TypedDict):
    modules: CoverageLedger
    terms: CoverageLedger
    structures: CoverageLedger


class NamingCandidates(TypedDict):
    modules: list[ModuleCandidate]
    modules_dropped: int
    terms: list[TermCandidate]
    terms_dropped: int
    structures: list[StructureCandidate]
    structures_dropped: int
    structures_source_groups_dropped: int
    structures_complete: bool
    coverage: NamingCoverage


# -- structural groups (Graphify adapter) -------------------------------------

class FreshnessRecord(TypedDict):
    built_at_commit: str | None
    current_commit: str | None
    worktree_dirty: bool | None
    status: str
    detail: str


class GroupCoverage(TypedDict):
    members_sample: CoverageLedger
    member_tokens: CoverageLedger


class GroupProvenance(TypedDict):
    code: int
    doc: int
    glossary: int


class StructuralGroup(TypedDict):
    id: str
    label: str
    label_truncated: bool
    cohesion: float | None
    size: int
    members_sample: list[str]
    member_tokens: list[str]
    coverage: GroupCoverage
    provenance: GroupProvenance


class GodNode(TypedDict):
    label: str
    degree: int


class _StructuralCoverageRequired(TypedDict):
    groups: CoverageLedger


class StructuralCoverage(_StructuralCoverageRequired, total=False):
    god_nodes: CoverageLedger


class _StructuralGroupsRequired(TypedDict):
    adapter_enabled: bool
    present: bool | None
    available: bool
    coverage: StructuralCoverage
    warnings: list[str]


class StructuralGroups(_StructuralGroupsRequired, total=False):
    """The adapter's section: the required keys are always present; the
    rest exist only when a graph was loaded (``present`` true) and carry
    its normalized content."""

    source: str
    freshness: FreshnessRecord
    source_nodes: int
    nodes: int
    edges: int
    groups: list[StructuralGroup]
    groups_dropped: int
    groups_complete: bool
    naming_groups_dropped: int
    god_nodes: list[GodNode]
    discounted_glossary_nodes: int


# -- omissions ---------------------------------------------------------------

class SkippedSection(SkippedPaths):
    """The walk's path exclusions plus the non-walk omissions."""

    oversized_identifiers: int
    corpus_budget: CorpusBudgetEvidence


# -- the document ------------------------------------------------------------

class EvidenceDocument(TypedDict):
    schema_version: int
    generator: GeneratorRecord
    repository: RepositoryRecord
    configuration: ConfigurationEvidence
    totals: TotalsRecord
    languages: dict[str, int]
    modules: list[ModuleRecord]
    imports: ImportsSection
    naming_candidates: NamingCandidates
    structural_groups: StructuralGroups
    files: FilesSection
    vocabulary: VocabularySection
    terminology: TerminologySection
    monorepo: MonorepoEvidence
    skipped: SkippedSection
