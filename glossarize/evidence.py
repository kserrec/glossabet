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

from glossarize import __version__
from glossarize.scanner import detect_monorepo, walk_repository
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
    identifier_counts: Counter = Counter()
    languages: Counter = Counter()
    modules: dict[str, dict] = defaultdict(lambda: {"code_files": 0, "languages": set()})
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
        for name in iter_identifiers(text):
            identifier_counts[name] += 1
            for token in tokenize_identifier(name):
                token_counts[token] += 1
                token_files[token][rel] += 1

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
        "modules": [
            {
                "path": path,
                "code_files": info["code_files"],
                "languages": sorted(info["languages"]),
            }
            for path, info in sorted(modules.items())
        ],
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


def scan_command(path_arg: str) -> int:
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
    return 0
