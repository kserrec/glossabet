"""RepositoryEvidence: build and persist glossabet-out/evidence.json.

Deterministic by construction: no timestamps, sorted collections, stable
tie-breaks. Bounded by construction (PLAN.md principle 12): every cap is
recorded in the artifact so truncated never reads as complete.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from glossabet import __version__
from glossabet.runtime.artifacts import write_artifact
from glossabet.corpus.cache import load_cache, save_cache
from glossabet.corpus.config import load_config
from glossabet.runtime.coverage import capped_collection
from glossabet.corpus.extraction import SourceExtractor
from glossabet.runtime import git_state
from glossabet.analysis.graphify import (
    build_structural_groups,
    disabled_structural_groups,
    structure_candidates,
)
from glossabet.corpus.imports import build_imports_section, module_of
from glossabet.analysis.importance import build_naming_candidates
from glossabet.corpus.scanner import detect_monorepo, walk_repository
from glossabet.analysis.terminology import build_terminology
from glossabet.corpus.tokenize import tokenization_contract, tokenize_identifier
from glossabet.analysis.vocabulary import DocumentationVocabulary, ProductionVocabulary

SCHEMA_VERSION = 13

EVIDENCE_FILE = "evidence.json"


@dataclass(frozen=True)
class Limits:
    """Detail caps for the evidence artifact's vocabulary tables."""

    tokens: int = 5000
    identifiers: int = 2000
    doc_terms: int = 2000
    locations_per_term: int = 5


def _capped(counter: Counter, cap: int, entry) -> dict:
    """Top-`cap` entries by (-count, key), with the remainder logged."""
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    kept, coverage = capped_collection(
        ranked, cap, cap_reason=f"evidence detail cap is {cap} items"
    )
    dropped = ranked[cap:]
    return {
        "items": [entry(term, count) for term, count in kept],
        "truncated": None if not dropped else {
            "dropped_terms": len(dropped),
            "dropped_occurrences": sum(c for _, c in dropped),
        },
        "coverage": coverage,
    }


def _location_sample(per_file: Counter, cap: int) -> tuple[list[dict], bool]:
    ranked = sorted(per_file.items(), key=lambda item: (-item[1], item[0]))
    kept = ranked[:cap]
    return (
        [{"path": path, "count": count} for path, count in kept],
        len(ranked) > len(kept),
    )


def build_evidence(root: Path, limits: Limits = Limits(),
                   cache: bool = False, stats: dict | None = None,
                   graphify: bool = True) -> dict:
    """Cold and warm scans share this one aggregation path, so a cached run
    is byte-identical to a fresh one by construction."""
    root = root.resolve()
    config = load_config(root)
    walk = walk_repository(root, config)
    git_stamp = git_state.repository_git_stamp(root)
    extractor = SourceExtractor(
        root, load_cache(root) if cache else None, walk.corpus_budget
    )

    # Repository vocabulary is deliberately production-scoped. Test and
    # fixture files remain visible in the inventory and cache, but do not
    # steer naming, drift, or terminology signals unless configuration marks
    # their path as production. Generated and vendored content is not read.
    vocabulary = ProductionVocabulary()
    documentation = DocumentationVocabulary()
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

    for rel, language, role in walk.code_files:
        entry = extractor.code_entry(rel, language, role)
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

    doc_entries = []
    doc_word_total = 0
    for rel, role in walk.doc_files:
        entry = extractor.doc_entry(rel, role)
        if entry is None:
            # Keep the inventory consistent with totals: the file exists and
            # is counted; the budget skip above names why no words were read.
            doc_entries.append({"path": rel, "role": role, "words": 0})
            continue
        doc_word_total += entry["word_total"]
        if role == "production":
            analyzed_production_doc_files += 1
            documentation.fold(entry["words"], rel)
        doc_entries.append({
            "path": rel,
            "role": role,
            "words": entry["word_total"],
        })

    if cache:
        save_cache(root, extractor.cache_files, git_stamp)
    if stats is not None:
        stats.update({
            "reused": extractor.reused, "extracted": extractor.extracted,
        })

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
        per_file = documentation.term_files[term]
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
    terminology = build_terminology(vocabulary, documentation.term_counts)
    naming = build_naming_candidates(
        imports_section, production_modules_list, vocabulary,
        documentation.term_counts, terminology["context_dispersion"],
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
                documentation.term_counts, limits.doc_terms, doc_term_entry,
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


def persist_evidence(root: Path, **options) -> dict:
    """Build the evidence for one command run through the cache and write
    it — the step every evidence-reading command performs after opening
    its run. ``options`` are ``build_evidence`` keyword arguments."""
    evidence = build_evidence(root, cache=True, **options)
    write_evidence(root, evidence)
    return evidence

