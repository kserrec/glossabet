"""The `scan` and `analyze` commands: build and persist evidence, then
report it on the terminal — the walk/graph summary for both, plus the
terminology report for `analyze`. Rendering only; every number printed
here is read back out of the evidence dict, never recomputed."""

from __future__ import annotations

import sys

from glossabet.artifacts import repo_root
from glossabet.display import escape_terminal_text
from glossabet.evidence import build_evidence, write_evidence
from glossabet.scanner import exclusion_sentences


def _print_terminology_report(evidence: dict) -> None:
    term = evidence["terminology"]
    reg = term["register"]
    print(
        f"\n== house register ({reg['unique_identifiers']} unique identifiers, "
        f"top {term['considered_tokens']} of "
        f"{term.get('domain_vocabulary_size', term['vocabulary_size'])} "
        f"domain tokens analyzed from {term['scope']['code_files']} production "
        f"code file(s)) =="
    )
    token_coverage = term.get("coverage", {}).get("eligible_tokens")
    if isinstance(token_coverage, dict) and not token_coverage.get("complete", True):
        print(
            "terminology coverage: partial — "
            f"{token_coverage['included_items']} of "
            f"{token_coverage['total_items']} eligible token(s) analyzed; "
            + "; ".join(
                escape_terminal_text(reason)
                for reason in token_coverage.get("reasons", [])
            )
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
    for label, key in (("suffixes", "common_suffix_tokens"),
                       ("prefixes", "common_prefix_tokens")):
        affixes = ", ".join(
            f"{escape_terminal_text(a['token'])} ({a['identifiers']})"
            for a in reg[key]
        )
        print(f"common {label}: {affixes or 'none'}")

    layers = term["layers"]
    print("\n== code vs docs vocabulary ==")
    for label, key in (("shared", "shared_top"), ("code-only", "code_only_top"),
                       ("doc-only", "doc_only_top")):
        values = ", ".join(escape_terminal_text(item) for item in layers[key])
        print(f"{label}: {values or 'none'}")

    syn = term["synonym_candidates"]
    print(f"\n== possible vocabulary overlaps "
          f"({syn['considered_pairs']} pairs considered) ==")
    if not syn["items"]:
        print("none nominated")
    for item in syn["items"]:
        left = escape_terminal_text(item["a"])
        right = escape_terminal_text(item["b"])
        contexts = ", ".join(
            escape_terminal_text(context) for context in item["shared_contexts"]
        )
        print(
            f"{left} ~ {right} (similarity {item['similarity']}; "
            f"shared contexts: {contexts})"
        )
    if syn["dropped_items"]:
        print(f"... and {syn['dropped_items']} more not shown")

    over = term["overload_candidates"]
    print("\n== possibly overloaded terms ==")
    if not over["items"]:
        print("none nominated")
    for item in over["items"]:
        mods = ", ".join(
            escape_terminal_text(module["path"])
            for module in item["modules"]
        )
        term_name = escape_terminal_text(item["term"])
        print(f"{term_name} across {mods} (dispersion {item['dispersion']})")
    if over["dropped_items"]:
        print(f"... and {over['dropped_items']} more not shown")

    naming = evidence["naming_candidates"]
    print("\n== naming candidates (import graph is best-effort) ==")
    for cand in naming["modules"]:
        path = escape_terminal_text(cand["path"])
        reasons = "; ".join(
            escape_terminal_text(reason) for reason in cand["reasons"]
        )
        print(f"module {path} — {reasons}")
    for cand in naming["terms"]:
        term_name = escape_terminal_text(cand["term"])
        nomination_kind = escape_terminal_text(cand["nomination_kind"])
        reasons = "; ".join(
            escape_terminal_text(reason) for reason in cand["reasons"]
        )
        print(f"term {term_name} [{nomination_kind}] — {reasons}")
    for cand in naming["structures"]:
        label = escape_terminal_text(cand["label"])
        reasons = "; ".join(
            escape_terminal_text(reason) for reason in cand["reasons"]
        )
        print(f"structure {label} — {reasons}")
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


def _scan(path_arg: str, report: bool, graphify: bool = True) -> int:
    root = repo_root(path_arg)
    if root is None:
        return 1
    stats: dict = {}
    evidence = build_evidence(root, cache=True, stats=stats, graphify=graphify)
    out_path = write_evidence(root, evidence)
    structural = evidence["structural_groups"]
    for warning in structural.get("warnings", []):
        print(
            f"graphify adapter: {escape_terminal_text(warning)}",
            file=sys.stderr,
        )
    if structural.get("available"):
        freshness = structural["freshness"]
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
    skipped = evidence["skipped"]
    for sentence in exclusion_sentences(skipped):
        print(sentence, file=sys.stderr)
    budget = skipped["corpus_budget"]
    if not budget["complete"]:
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
    mono = evidence["monorepo"]
    if mono["detected"]:
        reasons = "; ".join(
            escape_terminal_text(reason) for reason in mono["reasons"]
        )
        print(
            "monorepo detected: " + reasons + ".",
            file=sys.stderr,
        )
        print(
            "Vocabulary is usually healthier per sub-project — consider "
            "running glossabet at a lower level for each sub-project.",
            file=sys.stderr,
        )
    if report:
        _print_terminology_report(evidence)
    return 0


def scan_command(path_arg: str, graphify: bool = True) -> int:
    return _scan(path_arg, report=False, graphify=graphify)


def analyze_command(path_arg: str, graphify: bool = True) -> int:
    return _scan(path_arg, report=True, graphify=graphify)
