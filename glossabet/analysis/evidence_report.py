"""The `scan` and `analyze` commands: build and persist evidence, then
report it on the terminal — the walk/graph summary for both, plus the
terminology report for `analyze`. Rendering only; every number printed
here is read back out of the evidence dict, never recomputed."""

from __future__ import annotations

import sys
from collections.abc import Iterable

from glossabet.analysis.evidence import build_evidence, write_evidence
from glossabet.analysis.evidence_types import EvidenceDocument, StructuralGroups
from glossabet.command_run import open_run
from glossabet.corpus.config import CONFIG_FILE, PATH_ROLES, ConfigurationEvidence
from glossabet.corpus.scanner import (
    CorpusBudgetEvidence,
    MonorepoEvidence,
    exclusion_sentences,
)
from glossabet.runtime.display import escape_terminal_text, join_escaped


def configuration_hint(configuration: ConfigurationEvidence) -> str:
    """One line telling the user where the roles came from and that a root
    ``glossabet.json`` adjusts them — printed exactly where the exclusions
    and role totals are on screen, so the option is met at the point of
    need rather than only in the README."""
    source = (
        f"roles and exclusions from {CONFIG_FILE}"
        if configuration["present"]
        else "roles and exclusions from built-in defaults"
    )
    return (
        f"{source}; adjust with a root {CONFIG_FILE} "
        "(ignore_paths, path_roles: " + "/".join(PATH_ROLES) + ")"
    )


def _print_candidates(
    kind: str, candidates: Iterable[tuple[str, str | None, list[str]]],
) -> None:
    """``candidates`` are ``(name, tag or None, reasons)`` rows."""
    for candidate_name, candidate_tag, candidate_reasons in candidates:
        name = escape_terminal_text(candidate_name)
        tag = (
            f" [{escape_terminal_text(candidate_tag)}]" if candidate_tag else ""
        )
        reasons = join_escaped(candidate_reasons, "; ")
        print(f"{kind} {name}{tag} — {reasons}")


def _print_terminology_report(evidence: EvidenceDocument) -> None:
    terminology = evidence["terminology"]
    reg = terminology["register"]
    print(
        f"\n== house register ({reg['unique_identifiers']} unique identifiers, "
        f"top {terminology['considered_tokens']} of "
        f"{terminology.get('domain_vocabulary_size', terminology['vocabulary_size'])} "
        f"domain tokens analyzed from {terminology['scope']['code_files']} "
        f"production code file(s)) =="
    )
    token_coverage = terminology.get("coverage", {}).get("eligible_tokens")
    if isinstance(token_coverage, dict) and not token_coverage.get("complete", True):
        print(
            "terminology coverage: partial — "
            f"{token_coverage['included_items']} of "
            f"{token_coverage['total_items']} eligible token(s) analyzed; "
            + join_escaped(token_coverage.get("reasons", []), "; ")
        )
    composition = reg.get("composition", {})
    used_by_reason = composition.get("used_by_reason", {})
    excluded_by_reason = composition.get("excluded_by_reason", {})
    print(
        "register composition: "
        f"{composition.get('used_spellings', reg['unique_identifiers'])} of "
        f"{composition.get('total_spellings', reg['unique_identifiers'])} "
        "spelling(s) used — "
        f"{used_by_reason.get('structurally_styled', 0)} structurally styled "
        "for headline statistics, "
        f"{used_by_reason.get('corroborated_flat', 0)} corroborated flat; "
        f"{composition.get('excluded_spellings', 0)} excluded — "
        f"{excluded_by_reason.get('language_tagged_flat', 0)} "
        "language-tagged flat, "
        f"{excluded_by_reason.get('prose_dominated_flat', 0)} "
        "prose-dominated flat, "
        f"{excluded_by_reason.get('no_lexical_tokens', 0)} without lexical tokens"
    )
    styles = ", ".join(f"{k} {v}%" for k, v in reg["identifier_styles_pct"].items())
    print(f"styles (structurally styled spellings): {styles or 'n/a'}")
    dist = ", ".join(
        f"{k} words {v}%" for k, v in reg["token_count_distribution_pct"].items()
    )
    print(f"identifier length (structurally styled spellings): {dist or 'n/a'}")
    for label, affix_records in (("suffixes", reg["common_suffix_tokens"]),
                                 ("prefixes", reg["common_prefix_tokens"])):
        affixes = ", ".join(
            f"{escape_terminal_text(a['token'])} ({a['identifiers']})"
            for a in affix_records
        )
        print(f"common {label}: {affixes or 'none'}")

    layers = terminology["layers"]
    print("\n== code vs docs vocabulary ==")
    for label, layer_terms in (("shared", layers["shared_top"]),
                               ("code-only", layers["code_only_top"]),
                               ("doc-only", layers["doc_only_top"])):
        values = join_escaped(layer_terms)
        print(f"{label}: {values or 'none'}")

    syn = terminology["synonym_candidates"]
    print(f"\n== possible vocabulary overlaps "
          f"({syn['considered_pairs']} pairs considered) ==")
    if not syn["items"]:
        print("none nominated")
    for item in syn["items"]:
        left = escape_terminal_text(item["a"])
        right = escape_terminal_text(item["b"])
        contexts = join_escaped(item["shared_contexts"])
        print(
            f"{left} ~ {right} (similarity {item['similarity']}; "
            f"shared contexts: {contexts})"
        )
    if syn["dropped_items"]:
        print(f"... and {syn['dropped_items']} more not shown")

    over = terminology["overload_candidates"]
    print("\n== possibly overloaded terms ==")
    if not over["items"]:
        print("none nominated")
    for overload in over["items"]:
        mods = join_escaped(module["path"] for module in overload["modules"])
        term_name = escape_terminal_text(overload["term"])
        print(f"{term_name} across {mods} (dispersion {overload['dispersion']})")
    if over["dropped_items"]:
        print(f"... and {over['dropped_items']} more not shown")

    naming = evidence["naming_candidates"]
    print("\n== naming candidates (import graph is best-effort) ==")
    _print_candidates(
        "module", ((c["path"], None, c["reasons"]) for c in naming["modules"])
    )
    _print_candidates(
        "term",
        ((c["term"], c["nomination_kind"], c["reasons"]) for c in naming["terms"]),
    )
    _print_candidates(
        "structure",
        ((c["label"], None, c["reasons"]) for c in naming["structures"]),
    )
    dropped = (naming["modules_dropped"] + naming["terms_dropped"]
               + naming["structures_dropped"])
    if dropped:
        print(f"... and {dropped} more not shown")
    source_groups_dropped = naming.get(
        "structures_source_groups_dropped", 0
    )
    if source_groups_dropped:
        print(
            f"Graphify's group cap omitted {source_groups_dropped} "
            "additional naming-eligible structure(s); structure nominations "
            "are partial"
        )
    print(
        "\nThese are nominations with evidence, not verdicts — "
        "judge each against the code."
    )


def _print_graphify_summary(structural: StructuralGroups) -> None:
    for warning in structural.get("warnings", []):
        print(
            f"graphify adapter: {escape_terminal_text(warning)}",
            file=sys.stderr,
        )
    if structural["usable"]:
        freshness = structural["freshness"]
        if freshness is None:
            raise ValueError("usable structural groups require freshness state")
        groups_summary = f"{len(structural['groups'])} structural group(s)"
        if structural.get("groups_dropped"):
            groups_summary += (
                f" retained, {structural['groups_dropped']} omitted by cap"
            )
        print(
            f"graphify graph: {structural['nodes']} nodes, "
            f"{structural['edges']} edges, "
            f"{groups_summary}; "
            f"freshness {escape_terminal_text(freshness['status'])} — "
            f"{escape_terminal_text(freshness['detail'])}"
        )
    elif structural.get("present"):
        print("graphify graph present, but no usable structural groups loaded")


def _print_corpus_budget_warning(budget: CorpusBudgetEvidence) -> None:
    if budget["complete"]:
        return
    omitted = budget["skipped"]["source_files"]
    details = []
    if omitted:
        details.append(f"excluded {omitted} source file(s)")
    if budget["walk_remainder"]["truncated"]:
        details.append("directory walk omitted an inexact remainder")
    # Skips cover budget caps and read failures alike; the sample
    # entries name each file's reason.
    print(
        "corpus coverage incomplete: " + "; ".join(details)
        + "; evidence is partial",
        file=sys.stderr,
    )


def _print_monorepo_notice(mono: MonorepoEvidence) -> None:
    if not mono["detected"]:
        return
    print(
        "monorepo detected: " + join_escaped(mono["reasons"], "; ") + ".",
        file=sys.stderr,
    )
    print(
        "Vocabulary is usually healthier per sub-project — consider "
        "running glossabet at a lower level for each sub-project.",
        file=sys.stderr,
    )


def _scan(path_arg: str, report: bool, graphify: bool = True) -> int:
    run = open_run(path_arg)
    stats: dict[str, int] = {}
    evidence = build_evidence(
        run.root, cache=True, stats=stats, graphify=graphify
    )
    out_path = write_evidence(run.root, evidence)
    _print_graphify_summary(evidence["structural_groups"])
    if stats.get("reused"):
        print(
            f"cache: reused {stats['reused']} extraction(s), "
            f"re-extracted {stats['extracted']}"
        )
    totals = evidence["totals"]
    print(
        f"scanned {totals['code_files']} code files, "
        f"{totals['doc_files']} doc files "
        f"({len(evidence['languages'])} languages); terminology scope: "
        f"{evidence['terminology']['scope']['code_files']} production code "
        f"file(s) -> {escape_terminal_text(str(out_path))}"
    )
    for sentence in exclusion_sentences(evidence["skipped"]):
        print(sentence, file=sys.stderr)
    print(configuration_hint(evidence["configuration"]))
    _print_corpus_budget_warning(evidence["skipped"]["corpus_budget"])
    _print_monorepo_notice(evidence["monorepo"])
    if report:
        _print_terminology_report(evidence)
    return 0


def scan_command(path_arg: str, graphify: bool = True) -> int:
    return _scan(path_arg, report=False, graphify=graphify)


def analyze_command(path_arg: str, graphify: bool = True) -> int:
    return _scan(path_arg, report=True, graphify=graphify)
