"""Direction A of reconciliation: structure -> glossary.

Judges the Graphify structural groups against the canonical vocabulary —
graph usability, bounded structural concept matching with its match-work
ledger, and the unnamed-structure, boundary-mismatch, and overloaded-region
findings with their skipped/partial flags. Normalized groups carry no
repository paths, so path-scoped concepts cannot be matched here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations, islice

from glossabet.analysis.evidence_types import (
    FreshnessRecord,
    StructuralGroup,
    StructuralGroups,
)
from glossabet.corpus.tokenize import tokenize_bounded_term
from glossabet.glossary import findings
from glossabet.glossary.binding_validation import (
    ConceptVocabulary,
    vocabulary_tokens,
)
from glossabet.glossary.findings import (
    FindingSection,
    HeuristicFinding,
    capped_section,
    empty_section,
    heuristic_finding,
    mark_incomplete,
)
from glossabet.glossary.model import ConceptRecord
from glossabet.glossary.policy import (
    DEFAULT_RECONCILIATION_POLICY,
    MATCH_NONE,
    MATCH_STRONG,
    ReconciliationPolicy,
    is_overloaded_region,
    structural_match_strength,
    unnamed_structure_signal,
)
from glossabet.runtime.coverage import CoverageLedger, coverage_ledger

STRUCTURAL_MATCH_BUDGET = 50_000

# Looked up by name at each call so a test can count or replace it.
_match_strength_from_tokens = structural_match_strength


def _group_match_contexts(
    structural: StructuralGroups,
    canonical: list[ConceptRecord],
    vocabulary: ConceptVocabulary,
) -> tuple[
    list[tuple[StructuralGroup, set[str], set[str], list[str], bool]],
    list[str],
]:
    """Per structural group: (group, label tokens, label+member tokens,
    candidate concept ids reached through an inverted token index, whether
    those tokens are complete), sorted by label then id; plus incompleteness
    reasons shared by the structural sections and match-work ledger."""
    token_index: dict[str, set[str]] = defaultdict(set)
    for concept in canonical:
        words = vocabulary[concept["id"]]
        for token in words.term_tokens | words.binding_tokens:
            token_index[token].add(concept["id"])

    contexts: list[
        tuple[StructuralGroup, set[str], set[str], list[str], bool]
    ] = []
    missing_member_tokens = 0
    incomplete_member_tokens = 0
    incomplete_group_labels = 0
    for group in structural["groups"]:
        label_tokens = set(tokenize_bounded_term(
            group["label"], truncated=group.get("label_truncated") is True
        ))
        raw_member_tokens = group.get("member_tokens")
        if isinstance(raw_member_tokens, list):
            member_tokens = {
                token for token in raw_member_tokens if isinstance(token, str)
            }
            group_coverage = group.get("coverage")
            member_coverage = (
                group_coverage.get("member_tokens")
                if isinstance(group_coverage, dict) else None
            )
            member_tokens_complete = (
                isinstance(member_coverage, dict)
                and member_coverage.get("complete") is True
            )
            incomplete_member_tokens += not member_tokens_complete
        else:
            missing_member_tokens += 1
            member_tokens_complete = False
            member_tokens = set()
            for member in group.get("members_sample", []):
                member_tokens |= vocabulary_tokens(member)
        label_complete = group.get("label_truncated") is False
        incomplete_group_labels += not label_complete
        combined = label_tokens | member_tokens
        candidate_ids = sorted({
            concept_id
            for token in combined
            for concept_id in token_index.get(token, ())
        })
        contexts.append((
            group,
            label_tokens,
            combined,
            candidate_ids,
            member_tokens_complete and label_complete,
        ))
    contexts.sort(key=lambda item: (item[0]["label"], item[0]["id"]))
    reasons: list[str] = []
    if missing_member_tokens:
        reasons.append(
            f"{missing_member_tokens} structural group(s) lack complete "
            "member_tokens and fell back to the display sample"
        )
    if incomplete_member_tokens:
        reasons.append(
            f"{incomplete_member_tokens} structural group(s) have incomplete "
            "member-token evidence"
        )
    if incomplete_group_labels:
        reasons.append(
            f"{incomplete_group_labels} structural group label(s) were "
            "truncated or lack exactness metadata"
        )
    return contexts, reasons


def _structural_incompleteness(
    upstream_reasons: list[str],
    group_evidence_reasons: list[str],
    partial_group_matches: bool,
    total_match_work: int,
    processed_match_work: int,
) -> tuple[list[str], bool, CoverageLedger]:
    """Section incompleteness reasons, whether totals are exact, and the
    match-work ledger."""
    evidence_reasons = [*upstream_reasons, *group_evidence_reasons]
    reasons = list(evidence_reasons)
    if partial_group_matches:
        reasons.append(
            "structural concept matching reached its "
            f"{STRUCTURAL_MATCH_BUDGET}-candidate evaluation budget"
        )
    exact = not reasons
    work_reasons = list(evidence_reasons)
    if processed_match_work < total_match_work:
        work_reasons.append(
            "structural concept matching reached its "
            f"{STRUCTURAL_MATCH_BUDGET}-candidate evaluation budget"
        )
    work_coverage = coverage_ledger(
        total_match_work,
        processed_match_work,
        total_items_exact=not evidence_reasons,
        reasons=work_reasons,
    )
    return reasons, exact, work_coverage


def _structure_findings(
    structural: StructuralGroups,
    canonical: list[ConceptRecord],
    vocabulary: ConceptVocabulary,
    upstream_reasons: list[str],
    policy: ReconciliationPolicy = DEFAULT_RECONCILIATION_POLICY,
) -> tuple[FindingSection, FindingSection, FindingSection, CoverageLedger]:
    """Direction A: structure -> glossary.

    Canonical concepts are reached through an inverted token index. Boundary
    totals use n*(n-1)/2 and only the report prefix is streamed, so a group
    matching many concepts never materializes every pair.
    """
    contexts, group_evidence_reasons = _group_match_contexts(
        structural, canonical, vocabulary
    )

    total_match_work = sum(len(item[3]) for item in contexts)
    processed_match_work = 0
    unnamed: list[tuple[int, str, HeuristicFinding]] = []  # (size, group, finding)
    boundary: list[HeuristicFinding] = []
    overloaded: list[HeuristicFinding] = []
    boundary_total = 0
    partial_group_matches = False

    for (
        group,
        label_tokens,
        combined,
        candidate_ids,
        group_evidence_complete,
    ) in contexts:
        remaining = max(0, STRUCTURAL_MATCH_BUDGET - processed_match_work)
        evaluated_ids = candidate_ids[:remaining]
        processed_match_work += len(evaluated_ids)
        group_match_complete = len(evaluated_ids) == len(candidate_ids)
        partial_group_matches |= not group_match_complete
        strengths = {
            concept_id: _match_strength_from_tokens(
                label_tokens,
                combined,
                vocabulary[concept_id].term_tokens,
                vocabulary[concept_id].binding_tokens,
            )
            for concept_id in evaluated_ids
        }
        strong = sorted(
            concept_id
            for concept_id, strength in strengths.items()
            if strength >= MATCH_STRONG
        )
        if (
            group_evidence_complete
            and group_match_complete
            and max(strengths.values(), default=MATCH_NONE) == MATCH_NONE
        ):
            unnamed.append((group["size"], group["label"], heuristic_finding(
                "unnamed-structure",
                f"structural group '{group['label']}' "
                f"({group['size']} nodes) matches no canonical concept",
                {"size": group["size"], "members_sample": group["members_sample"]},
                signal_strength=unnamed_structure_signal(group["size"], policy),
                group=group["label"],
            )))
        group_pair_total = len(strong) * (len(strong) - 1) // 2
        boundary_total += group_pair_total
        detail_slots = max(0, findings.FINDINGS_CAP - len(boundary))
        for a, b in islice(combinations(strong, 2), detail_slots):
            boundary.append(heuristic_finding(
                "boundary-mismatch",
                f"'{a}' and '{b}' are distinct in the glossary but "
                f"both strongly match group '{group['label']}'",
                {"members_sample": group["members_sample"]},
                signal_strength="moderate",
                concepts=[a, b],
                group=group["label"],
            ))
        if is_overloaded_region(len(strong), policy):
            overloaded.append(heuristic_finding(
                "overloaded-structural-region",
                f"group '{group['label']}' matches "
                f"{len(strong)} distinct canonical concepts",
                {"members_sample": group["members_sample"]},
                signal_strength="moderate",
                group=group["label"],
                concepts=strong,
            ))
    unnamed.sort(key=lambda row: (-row[0], row[1]))
    overloaded.sort(key=lambda f: f["group"])

    reasons, exact, work_coverage = _structural_incompleteness(
        upstream_reasons, group_evidence_reasons, partial_group_matches,
        total_match_work, processed_match_work,
    )
    return (
        capped_section(
            [row[2] for row in unnamed], "unnamed structure",
            total_items_exact=exact, incomplete_reasons=reasons,
        ),
        capped_section(
            boundary, "boundary mismatch", total_items=boundary_total,
            total_items_exact=exact, incomplete_reasons=reasons,
        ),
        capped_section(
            overloaded, "overloaded structural region",
            total_items_exact=exact, incomplete_reasons=reasons,
        ),
        work_coverage,
    )



@dataclass(frozen=True)
class GraphStatus:
    """The complete Graphify state validation consumes and serializes."""

    present: bool | None
    usable: bool
    freshness: FreshnessRecord | None
    warnings: tuple[str, ...]
    groups_dropped: int
    groups_complete: bool | None
    coverage: CoverageLedger
    skip_reason: str | None

    @property
    def unusable_reason(self) -> str:
        """Why structural checks are skipped; only an unusable graph has one."""
        if self.skip_reason is None:
            raise ValueError("a usable graph has no skip reason")
        return self.skip_reason


def _graph_status(structural: StructuralGroups) -> GraphStatus:
    usable = structural["usable"]
    groups_dropped = int(structural.get("groups_dropped", 0))
    if usable:
        skip_reason = None
    elif structural.get("present") is True:
        skip_reason = "Graphify graph present but no usable structural groups loaded"
    else:
        skip_reason = "Graphify graph absent; structural checks require it"
    return GraphStatus(
        present=structural["present"],
        usable=usable,
        freshness=structural["freshness"],
        warnings=tuple(structural["warnings"]),
        groups_dropped=groups_dropped,
        groups_complete=(
            structural.get("groups_complete", groups_dropped == 0)
            if usable else None
        ),
        coverage=structural["coverage"]["groups"],
        skip_reason=skip_reason,
    )


@dataclass(frozen=True)
class StructuralValidation:
    """Named structure-to-glossary sections, work, and graph state."""

    unnamed_structure: FindingSection
    boundary_mismatch: FindingSection
    overloaded_structural_region: FindingSection
    matching_coverage: CoverageLedger
    graph: GraphStatus


def build_structural_validation(
    structural: StructuralGroups,
    global_canonical: list[ConceptRecord],
    scoped_canonical: list[ConceptRecord],
    vocabulary: ConceptVocabulary,
    policy: ReconciliationPolicy,
) -> StructuralValidation:
    """The three structure -> glossary sections with their skipped/partial
    flags, plus the match-work ledger. Path-scoped concepts cannot be
    matched against normalized Graphify groups, which carry no paths."""
    graph = _graph_status(structural)
    scoped_structure_reason = (
        "path-scoped concepts omitted because normalized Graphify groups do "
        "not carry repository paths"
    )
    structural_source_reasons = (
        [
            f"{graph.groups_dropped} normalized Graphify group(s) omitted by "
            "the group cap"
        ]
        if graph.groups_dropped else []
    )
    if graph.usable:
        unnamed, boundary, overloaded, structural_work = _structure_findings(
            structural, global_canonical, vocabulary, structural_source_reasons,
            policy,
        )
    else:
        unnamed = boundary = overloaded = empty_section(graph.unusable_reason)
        structural_work = coverage_ledger(0, 0)  # no work budget was spent

    unnamed_scope_limited = bool(scoped_canonical) and graph.usable
    if unnamed_scope_limited:
        unnamed = empty_section(
            scoped_structure_reason, total_items_exact=False
        )
        boundary = mark_incomplete(boundary, scoped_structure_reason)
        overloaded = mark_incomplete(overloaded, scoped_structure_reason)

    def with_flags(
        section: FindingSection, *, skipped: bool, skip_reason: str | None
    ) -> FindingSection:
        ledger = section["coverage"]
        partial = not skipped and graph.usable and not ledger["total_items_exact"]
        return {
            **section,
            "skipped": skipped,
            "skip_reason": skip_reason,
            "partial": partial,
            "partial_reason": "; ".join(ledger["reasons"]) if partial else None,
        }

    return StructuralValidation(
        unnamed_structure=with_flags(
            unnamed,
            skipped=not graph.usable or unnamed_scope_limited,
            skip_reason=(
                scoped_structure_reason if unnamed_scope_limited
                else graph.skip_reason
            ),
        ),
        boundary_mismatch=with_flags(
            boundary, skipped=not graph.usable, skip_reason=graph.skip_reason
        ),
        overloaded_structural_region=with_flags(
            overloaded, skipped=not graph.usable, skip_reason=graph.skip_reason
        ),
        matching_coverage=structural_work,
        graph=graph,
    )
