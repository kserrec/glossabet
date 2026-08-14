"""RepositoryEvidence: build and persist glossarize-out/evidence.json.

Deterministic by construction: no timestamps, sorted collections, stable
tie-breaks. Bounded by construction (PLAN.md principle 12): every cap is
recorded in the artifact so truncated never reads as complete.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from itertools import combinations

from glossarize import __version__
from glossarize.imports import build_imports_section, extract_imports
from glossarize.importance import build_naming_candidates
from glossarize.scanner import detect_monorepo, walk_repository
from glossarize.terminology import build_terminology
from glossarize.tokenize import doc_words, iter_identifiers, tokenize_identifier

SCHEMA_VERSION = 1

OUT_DIR = "glossarize-out"
EVIDENCE_FILE = "evidence.json"


@dataclass(frozen=True)
class Limits:
    tokens: int = 5000
    identifiers: int = 2000
    doc_terms: int = 2000
    locations_per_term: int = 5


def _git_stamp(root: Path) -> dict:
    def git(*args: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return proc.stdout if proc.returncode == 0 else None

    head = git("rev-parse", "HEAD")
    if head is None:
        return {"head": None, "dirty": None}
    status = git("status", "--porcelain")
    return {
        "head": head.strip(),
        "dirty": bool(status.strip()) if status is not None else None,
    }


def _capped(counter: Counter, cap: int, entry) -> dict:
    """Top-`cap` entries by (-count, key), with the remainder logged."""
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    kept, dropped = ranked[:cap], ranked[cap:]
    return {
        "items": [entry(term, count) for term, count in kept],
        "truncated": None if not dropped else {
            "dropped_terms": len(dropped),
            "dropped_occurrences": sum(c for _, c in dropped),
        },
    }


def _read_text(path: Path) -> str | None:
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return None
    if "\0" in text[:1024]:  # binary despite its extension
        return None
    return text


def build_evidence(root: Path, limits: Limits = Limits()) -> dict:
    root = root.resolve()
    walk = walk_repository(root)

    token_counts: Counter = Counter()
    token_files: dict[str, Counter] = defaultdict(Counter)
    token_modules: dict[str, Counter] = defaultdict(Counter)
    neighbors: dict[str, Counter] = defaultdict(Counter)
    module_neighbor_sets: dict[str, dict[str, set]] = defaultdict(
        lambda: defaultdict(set)
    )
    identifier_counts: Counter = Counter()
    languages: Counter = Counter()
    modules: dict[str, dict] = defaultdict(lambda: {"code_files": 0, "languages": set()})
    file_imports: list[tuple[str, list[str]]] = []
    code_bytes = 0

    for rel, language in walk.code_files:
        text = _read_text(root / rel)
        if text is None:
            continue
        code_bytes += len(text)
        languages[language] += 1
        module = rel.rsplit("/", 1)[0] if "/" in rel else "."
        modules[module]["code_files"] += 1
        modules[module]["languages"].add(language)
        specs = extract_imports(text, language)
        if specs:
            file_imports.append((rel, specs))
        for name in iter_identifiers(text):
            identifier_counts[name] += 1
            tokens = tokenize_identifier(name)
            uniq = sorted(set(tokens))
            for token in tokens:
                token_counts[token] += 1
                token_files[token][rel] += 1
                token_modules[token][module] += 1
            for a, b in combinations(uniq, 2):
                neighbors[a][b] += 1
                neighbors[b][a] += 1
            for token in uniq:
                seen = module_neighbor_sets[token][module]
                if len(seen) < 30:  # bounded context sample per (term, module)
                    seen.update(t for t in uniq if t != token)

    doc_term_counts: Counter = Counter()
    doc_entries = []
    doc_word_total = 0
    for rel in walk.doc_files:
        text = _read_text(root / rel)
        if text is None:
            continue
        words = doc_words(text)
        doc_word_total += len(words)
        doc_term_counts.update(words)
        doc_entries.append({"path": rel, "words": len(words)})

    def token_entry(term: str, count: int) -> dict:
        per_file = token_files[term]
        locations = sorted(per_file.items(), key=lambda kv: (-kv[1], kv[0]))
        kept = locations[: limits.locations_per_term]
        return {
            "term": term,
            "count": count,
            "files": len(per_file),
            "locations": [{"path": p, "count": c} for p, c in kept],
            "locations_truncated": len(locations) > len(kept),
        }

    modules_list = [
        {
            "path": path,
            "code_files": info["code_files"],
            "languages": sorted(info["languages"]),
        }
        for path, info in sorted(modules.items())
    ]
    imports_section = build_imports_section(file_imports, walk.code_files)

    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": "glossarize", "version": __version__},
        "repository": {"git": _git_stamp(root)},
        "totals": {
            "code_files": len(walk.code_files),
            "doc_files": len(walk.doc_files),
            "other_files": walk.other_files,
            "code_bytes": code_bytes,
            "doc_words": doc_word_total,
        },
        "languages": dict(sorted(languages.items())),
        "modules": modules_list,
        "imports": imports_section,
        "naming_candidates": build_naming_candidates(
            imports_section, modules_list, token_counts, token_files,
            token_modules, doc_term_counts,
        ),
        "files": {
            "code": [
                {"path": p, "language": lang}
                for p, lang in sorted(walk.code_files)
            ],
            "docs": sorted(doc_entries, key=lambda d: d["path"]),
        },
        "vocabulary": {
            "tokens": _capped(token_counts, limits.tokens, token_entry),
            "identifiers": _capped(
                identifier_counts, limits.identifiers,
                lambda term, count: {"name": term, "count": count},
            ),
            "doc_terms": _capped(
                doc_term_counts, limits.doc_terms,
                lambda term, count: {"term": term, "count": count},
            ),
        },
        "terminology": build_terminology(
            identifier_counts, token_counts, token_modules,
            neighbors, module_neighbor_sets, doc_term_counts,
        ),
        "monorepo": detect_monorepo(root, walk),
        "skipped": {
            "sensitive": sorted(walk.skipped_sensitive),
            "oversized": sorted(walk.skipped_oversized),
        },
    }


def write_evidence(root: Path, evidence: dict) -> Path:
    out = root / OUT_DIR
    out.mkdir(exist_ok=True)
    path = out / EVIDENCE_FILE
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return path


def _print_terminology_report(evidence: dict) -> None:
    term = evidence["terminology"]
    reg = term["register"]
    print(
        f"\n== house register ({reg['unique_identifiers']} unique identifiers, "
        f"top {term['considered_tokens']} of {term['vocabulary_size']} "
        f"tokens analyzed) =="
    )
    styles = ", ".join(f"{k} {v}%" for k, v in reg["identifier_styles_pct"].items())
    print(f"styles: {styles or 'n/a'}")
    dist = ", ".join(
        f"{k} words {v}%" for k, v in reg["token_count_distribution_pct"].items()
    )
    print(f"identifier length: {dist or 'n/a'}")
    for label, key in (("suffixes", "common_suffix_tokens"),
                       ("prefixes", "common_prefix_tokens")):
        affixes = ", ".join(f"{a['token']} ({a['identifiers']})" for a in reg[key])
        print(f"common {label}: {affixes or 'none'}")

    layers = term["layers"]
    print("\n== code vs docs vocabulary ==")
    for label, key in (("shared", "shared_top"), ("code-only", "code_only_top"),
                       ("doc-only", "doc_only_top")):
        print(f"{label}: {', '.join(layers[key]) or 'none'}")

    syn = term["synonym_candidates"]
    print(f"\n== possible vocabulary overlaps "
          f"({syn['considered_pairs']} pairs considered) ==")
    if not syn["items"]:
        print("none nominated")
    for item in syn["items"]:
        print(
            f"{item['a']} ~ {item['b']} (similarity {item['similarity']}; "
            f"shared contexts: {', '.join(item['shared_contexts'])})"
        )
    if syn["dropped_items"]:
        print(f"... and {syn['dropped_items']} more not shown")

    over = term["overload_candidates"]
    print("\n== possibly overloaded terms ==")
    if not over["items"]:
        print("none nominated")
    for item in over["items"]:
        mods = ", ".join(m["path"] for m in item["modules"])
        print(f"{item['term']} across {mods} (dispersion {item['dispersion']})")
    if over["dropped_items"]:
        print(f"... and {over['dropped_items']} more not shown")

    naming = evidence["naming_candidates"]
    print("\n== naming candidates (import graph is best-effort) ==")
    for cand in naming["modules"]:
        print(f"module {cand['path']} — {'; '.join(cand['reasons'])}")
    for cand in naming["terms"]:
        print(f"term {cand['term']} — {'; '.join(cand['reasons'])}")
    dropped = naming["modules_dropped"] + naming["terms_dropped"]
    if dropped:
        print(f"... and {dropped} more not shown")
    print(
        "\nThese are nominations with evidence, not verdicts — "
        "judge each against the code."
    )


def _scan(path_arg: str, report: bool) -> int:
    root = Path(path_arg)
    if not root.is_dir():
        print(f"glossarize: not a directory: {path_arg}", file=sys.stderr)
        return 1
    evidence = build_evidence(root)
    out_path = write_evidence(root.resolve(), evidence)
    totals = evidence["totals"]
    print(
        f"scanned {totals['code_files']} code files, "
        f"{totals['doc_files']} doc files "
        f"({len(evidence['languages'])} languages) -> {out_path}"
    )
    skipped = evidence["skipped"]
    if skipped["sensitive"]:
        print(
            f"excluded {len(skipped['sensitive'])} sensitive file(s) from evidence",
            file=sys.stderr,
        )
    if skipped["oversized"]:
        print(
            f"skipped {len(skipped['oversized'])} oversized file(s) (>2MB)",
            file=sys.stderr,
        )
    mono = evidence["monorepo"]
    if mono["detected"]:
        print(
            "monorepo detected: " + "; ".join(mono["reasons"]) + ".\n"
            "Vocabulary is usually healthier per sub-project — consider "
            "running glossarize at a lower level for each sub-project.",
            file=sys.stderr,
        )
    if report:
        _print_terminology_report(evidence)
    return 0


def scan_command(path_arg: str) -> int:
    return _scan(path_arg, report=False)


def analyze_command(path_arg: str) -> int:
    return _scan(path_arg, report=True)
