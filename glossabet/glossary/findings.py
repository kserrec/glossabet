"""The findings document: the shape drift and validation reports share.

Both checks emit *sections* of *findings*, each section carrying the common
coverage ledger, and both must translate RepositoryEvidence's own omissions
into "why this section may be incomplete" reasons before printing. This
module owns those three things once — the finding record (an *observed*
finding carries ``certainty``, a *heuristic* one ``signal_strength``; the
two are distinct types with distinct constructors, and the renderer keys on
which one it is given), the capped section with its ledger, and the
evidence-limitation derivation that reaches into evidence's truncation
markers — plus the terminal rendering of sections and the persisted shape of
both documents. ``drift`` and ``reconcile`` decide *what* is a finding;
nothing here decides that.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Protocol, TypedDict, TypeGuard, Union

from glossabet.agent.managed_context import ManagedContextReport
from glossabet.analysis.evidence_facts import VocabularyName, vocabulary_truncation
from glossabet.analysis.evidence_types import EvidenceDocument, FreshnessRecord
from glossabet.glossary.model import GlossaryDocument, ScopeEvidence
from glossabet.glossary.repository_glossary import RepositoryGlossarySection
from glossabet.runtime import coverage
from glossabet.runtime.coverage import CoverageLedger, coverage_ledger, coverage_reasons
from glossabet.runtime.display import escape_terminal_text, join_escaped

# Per-section detail cap for every findings document. Totals stay exact;
# only the listed detail is bounded, and the cap is reported.
FINDINGS_CAP = 10

VOCABULARY_MATCHING_OMISSION = (
    "vocabulary.{name} omitted entries needed for exact matching"
)

# The producer-specific detail attached to one finding: an occurrence
# record, a similarity, a module sample. Its keys are the producer's.
FindingEvidence = Mapping[str, object]


class _FindingRequired(TypedDict):
    kind: str
    summary: str


class _FindingFields(_FindingRequired, total=False):
    """Every field a producer may attach. The persisted record is one flat
    object, so each producer-specific field is enumerated here once."""

    scope: ScopeEvidence
    evidence: FindingEvidence
    term: str
    status: str
    new_term: str
    canonical_term: str
    concept_id: str
    ref: str
    binding_status: str
    group: str
    concepts: list[str]


class ObservedFinding(_FindingFields):
    """A fact the evidence shows directly; ``certainty`` names how."""

    certainty: str


class HeuristicFinding(_FindingFields):
    """A calibrated nomination; ``signal_strength`` is a label on a
    threshold, not a measured probability."""

    signal_strength: str


FindingRecord = Union[ObservedFinding, HeuristicFinding]


class _SectionRequired(TypedDict):
    items: list[FindingRecord]
    dropped_items: int
    coverage: CoverageLedger


class FindingSection(_SectionRequired, total=False):
    """One findings section; the flags exist only on validation's
    structural sections (``skipped`` when the graph cannot support the
    check, ``partial`` when it could only partly)."""

    skipped: bool
    skip_reason: str | None
    partial: bool
    partial_reason: str | None


MatchingCoverage = Mapping[str, CoverageLedger]


class DriftWork(TypedDict):
    matching: MatchingCoverage


class DriftCoverage(TypedDict):
    production_corpus_complete: bool
    collections: dict[str, CoverageLedger]
    work: DriftWork


class DriftScopeSummary(TypedDict):
    repository: int
    path_scoped: int


class DriftDocument(TypedDict):
    schema_version: int
    checked_concepts: int
    coverage: DriftCoverage
    total_findings_complete: bool
    scope_summary: DriftScopeSummary
    total_findings: int
    managed_context: ManagedContextReport
    parallel_terms: FindingSection
    watched_terms_in_use: FindingSection
    canonical_fading: FindingSection
    canonical_overloaded: FindingSection


class ValidationWork(TypedDict):
    matching: MatchingCoverage
    structural_matches: CoverageLedger


class ValidationCoverage(TypedDict):
    production_corpus_complete: bool
    repository_corpus_complete: bool
    collections: dict[str, CoverageLedger]
    work: ValidationWork


class ValidationScopeSummary(TypedDict):
    repository: int
    path_scoped: int
    structural_scope_complete: bool


class SkippedValidationCheck(TypedDict):
    name: str
    reason: str


class ValidationFindingChecks(TypedDict):
    """Whether every finding-producing check ran, with skips named."""

    all_executed: bool
    skipped: list[SkippedValidationCheck]


class GraphState(TypedDict):
    """The Graphify adapter state a validation embeds: presence, usability,
    freshness, warnings, and the group cap."""

    present: bool | None
    usable: bool
    freshness: FreshnessRecord | None
    warnings: list[str]
    groups_dropped: int
    groups_complete: bool | None
    coverage: CoverageLedger


class ValidationDocument(TypedDict):
    schema_version: int
    canonical_concepts: int
    scope_summary: ValidationScopeSummary
    coverage: ValidationCoverage
    finding_checks: ValidationFindingChecks
    graph: GraphState
    total_findings: int
    total_findings_exact: bool
    managed_context: ManagedContextReport
    repository_glossary: RepositoryGlossarySection
    unnamed_structure: FindingSection
    boundary_mismatch: FindingSection
    overloaded_structural_region: FindingSection
    orphaned_concepts: FindingSection
    unresolved_bindings: FindingSection
    fragmentation: FindingSection
    vocabulary_drift: FindingSection
    concept_collision: FindingSection


FindingsDocument = Union[DriftDocument, ValidationDocument]


def glossary_terms(glossary: GlossaryDocument) -> list[str]:
    """Every concept term and alias term, in document order — the term set
    the evidence matcher indexes for drift and validation."""
    return [
        term
        for concept in glossary["concepts"]
        for term in (
            concept["term"],
            *(alias["term"] for alias in concept.get("aliases", [])),
        )
    ]


def suppressed_reason(suppressed: int, name: str) -> list[str]:
    if not suppressed:
        return []
    return [
        f"{suppressed} {name} check(s) suppressed because required occurrence "
        "evidence was inexact"
    ]


def production_corpus_reasons(production_complete: bool) -> list[str]:
    return [] if production_complete else [
        "production corpus budget omitted accepted source evidence"
    ]


def observed_finding(
    kind: str,
    summary: str,
    evidence: FindingEvidence | None = None,
    *,
    certainty: str,
    scope: ScopeEvidence | None = None,
    term: str | None = None,
    status: str | None = None,
    concept_id: str | None = None,
    ref: str | None = None,
    binding_status: str | None = None,
) -> ObservedFinding:
    """One observed finding: a fact the evidence shows directly. Evidence is
    optional (binding findings carry none); scope and the producer fields
    are written only when given."""
    record: ObservedFinding = {
        "kind": kind, "certainty": certainty, "summary": summary,
    }
    if term is not None:
        record["term"] = term
    if status is not None:
        record["status"] = status
    if concept_id is not None:
        record["concept_id"] = concept_id
    if ref is not None:
        record["ref"] = ref
    if binding_status is not None:
        record["binding_status"] = binding_status
    if scope is not None:
        record["scope"] = scope
    if evidence is not None:
        record["evidence"] = evidence
    return record


def heuristic_finding(
    kind: str,
    summary: str,
    evidence: FindingEvidence | None = None,
    *,
    signal_strength: str,
    scope: ScopeEvidence | None = None,
    term: str | None = None,
    new_term: str | None = None,
    canonical_term: str | None = None,
    concept_id: str | None = None,
    group: str | None = None,
    concepts: list[str] | None = None,
) -> HeuristicFinding:
    """One heuristic finding: a nomination at a stated signal strength.
    Evidence is optional; scope and the producer fields are written only
    when given."""
    record: HeuristicFinding = {
        "kind": kind, "signal_strength": signal_strength, "summary": summary,
    }
    if term is not None:
        record["term"] = term
    if new_term is not None:
        record["new_term"] = new_term
    if canonical_term is not None:
        record["canonical_term"] = canonical_term
    if concept_id is not None:
        record["concept_id"] = concept_id
    if group is not None:
        record["group"] = group
    if concepts is not None:
        record["concepts"] = concepts
    if scope is not None:
        record["scope"] = scope
    if evidence is not None:
        record["evidence"] = evidence
    return record


def capped_section(
    items: Sequence[FindingRecord],
    name: str,
    *,
    incomplete_reasons: Iterable[str],
    total_items: int | None = None,
    total_items_exact: bool | None = None,
    cap: int | None = None,
) -> FindingSection:
    """``{items, dropped_items, coverage}`` for one findings section: the
    first ``cap`` findings in detail, the ledger honest about the rest.

    ``total_items`` defaults to the number of findings given; pass a larger
    known total when the producer stopped collecting detail early.
    ``total_items_exact`` defaults to "no incomplete reasons".
    """
    reasons = list(incomplete_reasons)
    if cap is None:
        cap = FINDINGS_CAP  # resolved at call time so tests can lower it
    if total_items_exact is None:
        total_items_exact = not reasons
    kept, ledger = coverage.capped_collection(
        items,
        cap,
        cap_reason=f"{name} finding detail cap is {cap} items",
        total_items=total_items,
        total_items_exact=total_items_exact,
        incomplete_reasons=reasons,
    )
    return {
        "items": kept,
        "dropped_items": ledger["dropped_items"],
        "coverage": ledger,
    }


def empty_section(reason: str, *, total_items_exact: bool = True) -> FindingSection:
    """A section holding no findings *for a stated reason*.

    A skipped check contributes zero to the evaluated-finding total because it
    evaluated no work; validation records that skip separately and ignores the
    section when deciding whether the evaluated total is exact. Pass false when
    the check ran over incomplete inputs and zero is only a lower bound.
    """
    return {
        "items": [],
        "dropped_items": 0,
        "coverage": coverage_ledger(
            0, 0, total_items_exact=total_items_exact, reasons=[reason]
        ),
    }


def mark_incomplete(section: FindingSection, reason: str) -> FindingSection:
    """The same section with its total declared inexact for ``reason``."""
    ledger = section["coverage"]
    updated = coverage_ledger(
        ledger["total_items"],
        ledger["included_items"],
        total_items_exact=False,
        reasons=[*ledger["reasons"], reason],
    )
    return {
        **section,
        "dropped_items": updated["dropped_items"],
        "coverage": updated,
    }


def vocabulary_omission_reasons(
    evidence: EvidenceDocument,
    names: Iterable[VocabularyName],
    template: str = VOCABULARY_MATCHING_OMISSION,
) -> list[str]:
    """One reason per named evidence vocabulary table whose detail was
    truncated at scan time — the only place a findings producer learns
    that RepositoryEvidence records such a thing."""
    return [
        template.format(name=name)
        for name in names
        if vocabulary_truncation(evidence, name) is not None
    ]


class _BoundedIndex(Protocol):
    """What ``matching_reasons`` needs from an evidence index: its per-index
    work ledgers."""

    @property
    def coverage(self) -> Mapping[str, CoverageLedger]: ...


def matching_reasons(matcher: _BoundedIndex) -> list[str]:
    """The evidence index's own bounded-work reasons, prefixed per index."""
    return [
        reason
        for name, ledger in matcher.coverage.items()
        for reason in coverage_reasons(ledger, f"matching.{name}")
    ]


def _never(key: str) -> bool:
    return False


def collection_limitations(
    collections: Mapping[str, CoverageLedger],
    *,
    skip: Callable[[str], bool] = _never,
) -> list[str]:
    """De-duplicated reasons from every listed section whose total is
    inexact (skipped sections excluded), in first-seen order."""
    return list(dict.fromkeys(
        reason
        for key, ledger in collections.items()
        if (
            isinstance(ledger, dict)
            and not ledger.get("total_items_exact", True)
            and not skip(key)
        )
        for reason in ledger.get("reasons", [])
    ))


def _print_finding_line(finding_record: FindingRecord) -> None:
    # Rendering keys on which epistemic field the record carries; it reads
    # the record as a plain mapping because the two finding types are open
    # (a key's absence is a fact about the value, not its declared type).
    raw: Mapping[str, object] = finding_record
    if "certainty" in raw:
        annotation = f"certainty {raw['certainty']}"
    else:
        annotation = f"signal {raw['signal_strength']}"
    summary = escape_terminal_text(finding_record["summary"])
    safe_annotation = escape_terminal_text(annotation)
    print(f"{summary} [{safe_annotation}]")


def _paths(records: Iterable[object]) -> Iterable[str]:
    """The ``path`` of each location/module record, for one terminal line."""
    return (
        str(record["path"])
        for record in records
        if isinstance(record, Mapping)
    )


def _print_finding_details(finding_record: FindingRecord) -> None:
    scope = finding_record.get("scope")
    if scope is not None and scope["kind"] == "path-prefixes":
        print("    scope: " + join_escaped(scope["path_prefixes"]))
    detail = finding_record.get("evidence", {})
    shared_contexts = detail.get("shared_contexts")
    if isinstance(shared_contexts, list):
        print("    shared contexts: " + join_escaped(map(str, shared_contexts)))
    locations = detail.get("locations")
    if isinstance(locations, list) and locations:
        print(f"    e.g. {join_escaped(_paths(locations[:3]))}")
    modules = detail.get("modules")
    if isinstance(modules, list):
        print("    modules: " + join_escaped(_paths(modules)))


def _is_finding_section(value: object) -> TypeGuard[FindingSection]:
    """A section is a mapping with an ``items`` list; the renderer reads a
    skipped section's flag before anything else."""
    return isinstance(value, dict) and isinstance(value.get("items"), list)


class FindingsDocumentView:
    """Validate and narrow finding sections selected by a dynamic key."""

    def __init__(self, document: FindingsDocument) -> None:
        # Sections are addressed by name (the caller's titles decide which),
        # so they are read through the document's plain mapping and
        # narrowed, rather than through a fixed key.
        self._raw: Mapping[str, object] = document

    def section(self, key: str) -> FindingSection:
        """One finding section ``{items, dropped_items, coverage[, skipped]}``."""
        value = self._raw[key]
        if not _is_finding_section(value):
            raise TypeError(f"{key!r} is not a findings section")
        return value

    def section_skipped(self, key: str) -> bool:
        value = self._raw.get(key)
        return _is_finding_section(value) and bool(value.get("skipped"))

    def items(self, key: str) -> list[FindingRecord]:
        """The finding records one section lists in detail."""
        return self.section(key)["items"]


def print_sections(
    document: FindingsDocumentView, titles: Mapping[str, str], *, detail: bool
) -> None:
    """Print every non-empty, non-skipped section under its title: one
    annotated line per finding (plus scope/context/location/module detail
    when ``detail`` is set) and the not-shown count."""
    for key, title in titles.items():
        section = document.section(key)
        if section.get("skipped"):
            continue
        if not section["items"] and not section["dropped_items"]:
            continue
        print(f"\n== {title} ==")
        for finding_record in section["items"]:
            _print_finding_line(finding_record)
            if detail:
                _print_finding_details(finding_record)
        if section["dropped_items"]:
            print(f"... and {section['dropped_items']} more not shown")
