"""RepositoryEvidence: build and persist glossabet-out/evidence.json.

Deterministic by construction: no timestamps, sorted collections, stable
tie-breaks. Bounded by construction (PLAN.md principle 12): every cap is
recorded in the artifact so truncated never reads as complete.
"""

from __future__ import annotations

import hashlib
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from glossabet import __version__
from glossabet.artifacts import OUT_DIR, repo_root, write_artifact
from glossabet.cache import entry_if_valid, load_cache, save_cache
from glossabet.config import load_config
from glossabet.coverage import coverage_ledger
from glossabet.display import escape_terminal_text
from glossabet import git_state
from glossabet.graphify import (
    build_structural_groups,
    disabled_structural_groups,
    structure_candidates,
)
from glossabet.imports import build_imports_section, extract_imports, module_of
from glossabet.managed_block import strip_managed_context_for_evidence
from glossabet.importance import build_naming_candidates
from glossabet.scanner import (
    detect_monorepo,
    exclusion_sentences,
    walk_repository,
)
from glossabet.terminology import build_terminology
from glossabet.tokenize import (
    doc_words,
    iter_identifiers,
    tokenization_contract,
    tokenize_identifier,
)
from glossabet.vocabulary import ProductionVocabulary

SCHEMA_VERSION = 12

EVIDENCE_FILE = "evidence.json"

# Beyond this, a spelling is not a real identifier. Per-identifier pattern and
# co-occurrence analysis is quadratic in token count, so this bounds a hostile
# single-identifier file from exhausting CPU/memory. Real identifiers use a
# handful of tokens; the pinned evaluation corpus never approaches this.


@dataclass(frozen=True)
class Limits:
    tokens: int = 5000
    identifiers: int = 2000
    doc_terms: int = 2000
    locations_per_term: int = 5


def _capped(counter: Counter, cap: int, entry) -> dict:
    """Top-`cap` entries by (-count, key), with the remainder logged."""
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    kept, dropped = ranked[:cap], ranked[cap:]
    reasons = []
    if dropped:
        reasons.append(f"evidence detail cap is {cap} items")
    return {
        "items": [entry(term, count) for term, count in kept],
        "truncated": None if not dropped else {
            "dropped_terms": len(dropped),
            "dropped_occurrences": sum(c for _, c in dropped),
        },
        "coverage": coverage_ledger(
            len(ranked), len(kept), reasons=reasons
        ),
    }


def _location_sample(per_file: Counter, cap: int) -> tuple[list[dict], bool]:
    ranked = sorted(per_file.items(), key=lambda item: (-item[1], item[0]))
    kept = ranked[:cap]
    return (
        [{"path": path, "count": count} for path, count in kept],
        len(ranked) > len(kept),
    )


def _read_source(path: Path) -> tuple[bytes, str] | str:
    """Content and digest, or the corpus-budget skip reason when unreadable."""
    try:
        content = path.read_bytes()
    except OSError:
        return "unreadable"
    if b"\0" in content[:1024]:  # binary despite its extension
        return "binary-content"
    return content, hashlib.sha256(content).hexdigest()


def _extract_code_entry(text: str, language: str) -> dict:
    identifiers: Counter = Counter()
    for name in iter_identifiers(text, language):
        identifiers[name] += 1
    return {
        "kind": "code",
        "language": language,
        "identifiers": dict(sorted(identifiers.items())),
        "imports": extract_imports(text, language),
    }


def _extract_doc_entry(text: str) -> dict:
    words = doc_words(text)
    counts = Counter(words)
    return {
        "kind": "doc",
        "words": dict(sorted(counts.items())),
        "word_total": len(words),
    }


def build_evidence(root: Path, limits: Limits = Limits(),
                   cache: bool = False, stats: dict | None = None,
                   graphify: bool = True) -> dict:
    """Cold and warm scans share this one aggregation path, so a cached run
    is byte-identical to a fresh one by construction."""
    root = root.resolve()
    config = load_config(root)
    walk = walk_repository(root, config)
    git_stamp = git_state.repository_git_stamp(root)
    cached = load_cache(root) if cache else None
    cache_files: dict[str, dict] = {}
    reused = extracted = 0

    # Repository vocabulary is deliberately production-scoped. Test and
    # fixture files remain visible in the inventory and cache, but do not
    # steer naming, drift, or terminology signals unless configuration marks
    # their path as production. Generated and vendored content is not read.
    vocabulary = ProductionVocabulary()
    languages: Counter = Counter()
    modules: dict[str, dict] = defaultdict(
        lambda: {
            "code_files": 0,
            "languages": set(),
            "code_files_by_role": Counter(),
        }
    )
    file_imports: list[tuple[str, str, list[str]]] = []
    production_code_files: list[tuple[str, str]] = []
    code_files_by_role = Counter(role for _, _, role in walk.code_files)
    doc_files_by_role = Counter(role for _, role in walk.doc_files)
    analyzed_production_code_files = 0
    analyzed_production_doc_files = 0
    code_bytes = 0

    def fetch_entry(rel: str, kind: str, role: str, extractor) -> dict | None:
        nonlocal reused, extracted
        source = _read_source(root / rel)
        if isinstance(source, str):
            # An inventoried file the build could not read is an omission
            # the artifact must confess: silence here would let capped or
            # broken evidence read as complete. The walk already admitted
            # the file, so reclassify it from used to skipped rather than
            # counting it on both sides of the ledger.
            try:
                size = os.path.getsize(root / rel)
            except OSError:
                size = 0
            walk.corpus_budget.reclassify_unread(
                rel, size, source, production=role == "production"
            )
            return None
        content, content_sha256 = source
        entry = entry_if_valid(cached, rel, kind, content_sha256)
        if entry is None:
            text = content.decode(errors="ignore")
            if kind == "doc":
                text = strip_managed_context_for_evidence(rel, text)
            entry = extractor(text)
            extracted += 1
        else:
            entry = dict(entry)
            reused += 1
        entry["content_sha256"] = content_sha256
        entry["size"] = len(content)
        cache_files[rel] = entry
        return entry

    for rel, language, role in walk.code_files:
        entry = fetch_entry(
            rel, "code", role, lambda text: _extract_code_entry(text, language)
        )
        if entry is None:
            continue
        code_bytes += entry["size"]  # on-disk bytes, not decoded characters
        languages[language] += 1
        module = module_of(rel)
        modules[module]["code_files"] += 1
        modules[module]["languages"].add(language)
        modules[module]["code_files_by_role"][role] += 1
        if role == "production":
            analyzed_production_code_files += 1
            production_code_files.append((rel, language))
            if entry["imports"]:
                file_imports.append((rel, language, entry["imports"]))
            vocabulary.fold(entry["identifiers"], rel, module, language)

    doc_term_counts: Counter = Counter()
    doc_term_files: dict[str, Counter] = defaultdict(Counter)
    doc_entries = []
    doc_word_total = 0
    for rel, role in walk.doc_files:
        entry = fetch_entry(rel, "doc", role, _extract_doc_entry)
        if entry is None:
            # Keep the inventory consistent with totals: the file exists and
            # is counted; the budget skip above names why no words were read.
            doc_entries.append({"path": rel, "role": role, "words": 0})
            continue
        doc_word_total += entry["word_total"]
        if role == "production":
            analyzed_production_doc_files += 1
            doc_term_counts.update(entry["words"])
            for term, count in entry["words"].items():
                doc_term_files[term][rel] += count
        doc_entries.append({
            "path": rel,
            "role": role,
            "words": entry["word_total"],
        })

    if cache:
        save_cache(root, cache_files, git_stamp)
    if stats is not None:
        stats.update({"reused": reused, "extracted": extracted})

    def token_entry(term: str, count: int) -> dict:
        per_file = vocabulary.token_files[term]
        locations, locations_truncated = _location_sample(
            per_file, limits.locations_per_term
        )
        return {
            "term": term,
            "origin": vocabulary.token_origins[term],
            "count": count,
            "files": len(per_file),
            "modules": len(vocabulary.token_modules.get(term, ())),
            "locations": locations,
            "locations_truncated": locations_truncated,
        }

    def identifier_entry(name: str, count: int) -> dict:
        per_file = vocabulary.identifier_files[name]
        locations, locations_truncated = _location_sample(
            per_file, limits.locations_per_term
        )
        return {
            "name": name,
            "tokens": tokenize_identifier(name),
            "count": count,
            "files": len(per_file),
            "locations": locations,
            "locations_truncated": locations_truncated,
        }

    def doc_term_entry(term: str, count: int) -> dict:
        per_file = doc_term_files[term]
        locations, locations_truncated = _location_sample(
            per_file, limits.locations_per_term
        )
        return {
            "term": term,
            "count": count,
            "files": len(per_file),
            "locations": locations,
            "locations_truncated": locations_truncated,
        }

    modules_list = [
        {
            "path": path,
            "code_files": info["code_files"],
            "code_files_by_role": dict(sorted(info["code_files_by_role"].items())),
            "languages": sorted(info["languages"]),
        }
        for path, info in sorted(modules.items())
    ]
    production_modules_list = [
        {
            "path": path,
            "code_files": info["code_files_by_role"].get("production", 0),
            "languages": sorted(info["languages"]),
        }
        for path, info in sorted(modules.items())
        if info["code_files_by_role"].get("production", 0)
    ]
    imports_section = build_imports_section(file_imports, production_code_files)
    structural = (
        build_structural_groups(root, git_stamp) if graphify
        else disabled_structural_groups()
    )
    terminology = build_terminology(vocabulary, doc_term_counts)
    naming = build_naming_candidates(
        imports_section, production_modules_list, vocabulary,
        doc_term_counts, terminology["context_dispersion"],
    )
    structural_naming = structure_candidates(structural)
    naming["coverage"].update(structural_naming.pop("coverage"))
    naming.update(structural_naming)

    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": "glossabet", "version": __version__},
        "repository": {"git": git_stamp},
        "configuration": config.as_evidence(),
        "totals": {
            "source_files": len(walk.code_files) + len(walk.doc_files),
            "source_bytes": walk.corpus_budget.source_bytes,
            "code_files": len(walk.code_files),
            "doc_files": len(walk.doc_files),
            "code_files_by_role": dict(sorted(code_files_by_role.items())),
            "doc_files_by_role": dict(sorted(doc_files_by_role.items())),
            "other_files": walk.other_files,
            "code_bytes": code_bytes,
            "doc_words": doc_word_total,
        },
        "languages": dict(sorted(languages.items())),
        "modules": modules_list,
        "imports": imports_section,
        "naming_candidates": naming,
        "structural_groups": structural,
        "files": {
            "code": [
                {"path": path, "language": language, "role": role}
                for path, language, role in sorted(walk.code_files)
            ],
            "docs": sorted(doc_entries, key=lambda d: d["path"]),
        },
        "vocabulary": {
            "normalization": tokenization_contract(),
            "tokens": _capped(vocabulary.token_counts, limits.tokens, token_entry),
            "identifiers": _capped(
                vocabulary.identifier_counts, limits.identifiers,
                identifier_entry,
            ),
            "doc_terms": _capped(
                doc_term_counts, limits.doc_terms, doc_term_entry,
            ),
        },
        "terminology": {
            **terminology,
            "scope": {
                "roles": ["production"],
                "code_files": analyzed_production_code_files,
                "doc_files": analyzed_production_doc_files,
            },
        },
        "monorepo": detect_monorepo(root, walk),
        "skipped": {
            **walk.skipped_as_evidence(),
            "oversized_identifiers": vocabulary.oversized_identifiers,
            "corpus_budget": walk.corpus_budget.as_evidence(),
        },
    }


def write_evidence(root: Path, evidence: dict) -> Path:
    return write_artifact(root, EVIDENCE_FILE, evidence)


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
