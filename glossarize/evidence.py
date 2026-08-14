"""RepositoryEvidence: build and persist glossarize-out/evidence.json.

Deterministic by construction: no timestamps, sorted collections, stable
tie-breaks. Bounded by construction (PLAN.md principle 12): every cap is
recorded in the artifact so truncated never reads as complete.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from glossarize import __version__
from glossarize.artifacts import OUT_DIR, repo_root, write_artifact
from glossarize.cache import entry_if_valid, load_cache, save_cache
from glossarize.config import load_config
from glossarize.graphify import (
    build_structural_groups,
    disabled_structural_groups,
    structure_candidates,
)
from glossarize.imports import build_imports_section, extract_imports, module_of
from glossarize.importance import build_naming_candidates
from glossarize.scanner import detect_monorepo, walk_repository
from glossarize.terminology import build_terminology
from glossarize.tokenize import (
    doc_words,
    iter_identifiers,
    tokenization_contract,
    tokenize_identifier,
)

SCHEMA_VERSION = 5

EVIDENCE_FILE = "evidence.json"


@dataclass(frozen=True)
class Limits:
    tokens: int = 5000
    identifiers: int = 2000
    doc_terms: int = 2000
    locations_per_term: int = 5


# Config keys that let a repository's own .git/config name a program git will
# execute (core.fsmonitor runs on `git status`, hooks on many operations). We
# only read HEAD and dirty state from an untrusted repo, so we override these
# to empty on every call: a hostile .git/config must not achieve code
# execution. Command-line -c beats repo-local config.
_GIT_SAFE_CONFIG = ("-c", "core.fsmonitor=", "-c", "core.hooksPath=/dev/null")

# Freshness describes repository inputs, not Glossarize's own output. Keep the
# pathspec here literal and mirrored in skill/SKILL.md: the whole top-level
# output directory is Glossarize-owned, whether its files are tracked or
# untracked. The pathspec is relative to `git -C root`, not Git's top level,
# because a supported per-subproject scan may start inside a larger worktree.
# --no-renames ensures a move across that ownership boundary still exposes the
# changed non-output path. Git-ignored paths retain Git's ordinary status
# semantics and every other tracked or untracked path remains visible.
_GIT_FRESHNESS_STATUS_ARGS = (
    "status",
    "--porcelain=v1",
    "--untracked-files=all",
    "--no-renames",
    "--",
    ".",
    f":(exclude){OUT_DIR}",
    f":(exclude){OUT_DIR}/**",
)


def _git_stamp(root: Path) -> dict:
    def git(*args: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", *_GIT_SAFE_CONFIG, "-C", str(root), *args],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return proc.stdout if proc.returncode == 0 else None

    head = git("rev-parse", "HEAD")
    if head is None:
        return {"head": None, "dirty": None}
    status = git(*_GIT_FRESHNESS_STATUS_ARGS)
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


def _read_source(path: Path) -> tuple[bytes, str] | None:
    try:
        content = path.read_bytes()
    except OSError:
        return None
    if b"\0" in content[:1024]:  # binary despite its extension
        return None
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


class _Vocabulary:
    """Identifier vocabulary accumulated across the walk: shared token
    counts plus the per-file, per-module, and co-occurrence views the
    downstream analyses need — one aggregate instead of six parallel dicts.
    """

    def __init__(self) -> None:
        self.token_counts: Counter = Counter()
        self.token_files: dict[str, Counter] = defaultdict(Counter)
        self.token_modules: dict[str, Counter] = defaultdict(Counter)
        self.token_patterns: dict[str, Counter] = defaultdict(Counter)
        self.neighbors: dict[str, Counter] = defaultdict(Counter)
        self.module_neighbor_sets: dict[str, dict[str, set]] = defaultdict(
            lambda: defaultdict(set)
        )
        self.identifier_counts: Counter = Counter()
        self.identifier_files: dict[str, Counter] = defaultdict(Counter)

    def fold(self, identifiers: dict[str, int], rel: str, module: str) -> None:
        """Fold one code file's identifier counts into every view."""
        for name, count in sorted(identifiers.items()):
            self.identifier_counts[name] += count
            self.identifier_files[name][rel] += count
            tokens = tokenize_identifier(name)
            uniq = sorted(set(tokens))
            for token in tokens:
                self.token_counts[token] += count
                self.token_files[token][rel] += count
                self.token_modules[token][module] += count
            if len(tokens) >= 2:
                for index, token in enumerate(tokens):
                    pattern = tuple(tokens[:index] + ["*"] + tokens[index + 1:])
                    self.token_patterns[token][pattern] += count
            for a, b in combinations(uniq, 2):
                self.neighbors[a][b] += count
                self.neighbors[b][a] += count
            for token in uniq:
                seen = self.module_neighbor_sets[token][module]
                if len(seen) < 30:  # bounded context sample per (term, module)
                    seen.update(t for t in uniq if t != token)


def build_evidence(root: Path, limits: Limits = Limits(),
                   cache: bool = False, stats: dict | None = None,
                   graphify: bool = True) -> dict:
    """Cold and warm scans share this one aggregation path, so a cached run
    is byte-identical to a fresh one by construction."""
    root = root.resolve()
    config = load_config(root)
    walk = walk_repository(root, config)
    git_stamp = _git_stamp(root)
    cached = load_cache(root) if cache else None
    cache_files: dict[str, dict] = {}
    reused = extracted = 0

    # Repository vocabulary is deliberately production-scoped. Test and
    # fixture files remain visible in the inventory and cache, but do not
    # steer naming, drift, or terminology signals unless configuration marks
    # their path as production. Generated and vendored content is not read.
    vocabulary = _Vocabulary()
    languages: Counter = Counter()
    modules: dict[str, dict] = defaultdict(
        lambda: {
            "code_files": 0,
            "languages": set(),
            "code_files_by_role": Counter(),
        }
    )
    file_imports: list[tuple[str, list[str]]] = []
    production_code_files: list[tuple[str, str]] = []
    code_files_by_role = Counter(role for _, _, role in walk.code_files)
    doc_files_by_role = Counter(role for _, role in walk.doc_files)
    analyzed_production_code_files = 0
    analyzed_production_doc_files = 0
    code_bytes = 0

    def fetch_entry(rel: str, kind: str, extractor) -> dict | None:
        nonlocal reused, extracted
        source = _read_source(root / rel)
        if source is None:
            return None
        content, content_sha256 = source
        entry = entry_if_valid(cached, rel, kind, content_sha256)
        if entry is None:
            text = content.decode(errors="ignore")
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
            rel, "code", lambda text: _extract_code_entry(text, language)
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
                file_imports.append((rel, entry["imports"]))
            vocabulary.fold(entry["identifiers"], rel, module)

    doc_term_counts: Counter = Counter()
    doc_term_files: dict[str, Counter] = defaultdict(Counter)
    doc_entries = []
    doc_word_total = 0
    for rel, role in walk.doc_files:
        entry = fetch_entry(rel, "doc", _extract_doc_entry)
        if entry is None:
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
        locations = sorted(per_file.items(), key=lambda kv: (-kv[1], kv[0]))
        kept = locations[: limits.locations_per_term]
        return {
            "term": term,
            "count": count,
            "files": len(per_file),
            "modules": len(vocabulary.token_modules.get(term, ())),
            "locations": [{"path": p, "count": c} for p, c in kept],
            "locations_truncated": len(locations) > len(kept),
        }

    def identifier_entry(name: str, count: int) -> dict:
        per_file = vocabulary.identifier_files[name]
        locations = sorted(per_file.items(), key=lambda kv: (-kv[1], kv[0]))
        kept = locations[: limits.locations_per_term]
        return {
            "name": name,
            "tokens": tokenize_identifier(name),
            "count": count,
            "files": len(per_file),
            "locations": [{"path": path, "count": uses} for path, uses in kept],
            "locations_truncated": len(locations) > len(kept),
        }

    def doc_term_entry(term: str, count: int) -> dict:
        per_file = doc_term_files[term]
        locations = sorted(per_file.items(), key=lambda kv: (-kv[1], kv[0]))
        kept = locations[: limits.locations_per_term]
        return {
            "term": term,
            "count": count,
            "files": len(per_file),
            "locations": [
                {"path": path, "count": uses} for path, uses in kept
            ],
            "locations_truncated": len(locations) > len(kept),
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
    naming = build_naming_candidates(
        imports_section, production_modules_list, vocabulary.token_counts,
        vocabulary.token_files, vocabulary.token_modules, doc_term_counts,
    )
    naming.update(structure_candidates(structural))

    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": "glossarize", "version": __version__},
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
            **build_terminology(
                vocabulary.identifier_counts, vocabulary.token_counts,
                vocabulary.token_files, vocabulary.token_modules,
                vocabulary.token_patterns, vocabulary.neighbors,
                vocabulary.module_neighbor_sets, doc_term_counts,
            ),
            "scope": {
                "roles": ["production"],
                "code_files": analyzed_production_code_files,
                "doc_files": analyzed_production_doc_files,
            },
        },
        "monorepo": detect_monorepo(root, walk),
        "skipped": {
            "sensitive": sorted(walk.skipped_sensitive),
            "oversized": sorted(walk.skipped_oversized),
            "symlinks_escaping_repo": sorted(walk.skipped_symlinks),
            "configured": sorted(walk.skipped_configured),
            "generated": sorted(walk.skipped_generated),
            "vendored": sorted(walk.skipped_vendored),
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
        f"top {term['considered_tokens']} of {term['vocabulary_size']} "
        f"tokens analyzed from {term['scope']['code_files']} production "
        f"code file(s)) =="
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
    for cand in naming["structures"]:
        print(f"structure {cand['label']} — {'; '.join(cand['reasons'])}")
    dropped = (naming["modules_dropped"] + naming["terms_dropped"]
               + naming["structures_dropped"])
    if dropped:
        print(f"... and {dropped} more not shown")
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
        print(f"graphify adapter: {warning}", file=sys.stderr)
    if structural.get("available"):
        freshness = structural["freshness"]
        print(
            f"graphify graph: {structural['nodes']} nodes, "
            f"{structural['edges']} edges, "
            f"{len(structural['groups'])} structural group(s); "
            f"freshness {freshness['status']} — {freshness['detail']}"
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
        f"file(s) -> {out_path}"
    )
    skipped = evidence["skipped"]
    if skipped["sensitive"]:
        print(
            f"excluded {len(skipped['sensitive'])} sensitive path(s) from evidence",
            file=sys.stderr,
        )
    if skipped["oversized"]:
        print(
            f"skipped {len(skipped['oversized'])} oversized file(s) (>2MB)",
            file=sys.stderr,
        )
    if skipped["symlinks_escaping_repo"]:
        print(
            f"skipped {len(skipped['symlinks_escaping_repo'])} symlink(s) "
            "resolving outside the repository",
            file=sys.stderr,
        )
    if skipped["configured"]:
        print(
            f"ignored {len(skipped['configured'])} configured path(s)",
            file=sys.stderr,
        )
    if skipped["generated"]:
        print(
            f"excluded {len(skipped['generated'])} generated path(s) "
            "from lexical analysis",
            file=sys.stderr,
        )
    if skipped["vendored"]:
        print(
            f"excluded {len(skipped['vendored'])} vendored path(s) "
            "from lexical analysis",
            file=sys.stderr,
        )
    budget = skipped["corpus_budget"]
    if not budget["complete"]:
        omitted = budget["skipped"]["source_files"]
        details = []
        if omitted:
            details.append(f"excluded {omitted} source file(s)")
        if budget["walk_remainder"]["truncated"]:
            details.append("directory walk omitted an inexact remainder")
        print(
            "corpus budget reached: " + "; ".join(details)
            + "; evidence is partial",
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


def scan_command(path_arg: str, graphify: bool = True) -> int:
    return _scan(path_arg, report=False, graphify=graphify)


def analyze_command(path_arg: str, graphify: bool = True) -> int:
    return _scan(path_arg, report=True, graphify=graphify)
