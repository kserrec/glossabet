"""RepositoryEvidence: build and persist glossabet-out/evidence.json.

Deterministic by construction: no timestamps, sorted collections, stable
tie-breaks. Bounded by construction: every cap is recorded in the artifact so
truncated never reads as complete.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict, TypeVar

from glossabet import __version__
from glossabet.analysis.evidence_types import (
    DocFileEntry,
    DocTermEntry,
    DocTermTable,
    EvidenceDocument,
    IdentifierEntry,
    IdentifierTable,
    ModuleRecord,
    NamingCandidates,
    ProductionModuleRecord,
    TokenEntry,
    TokenTable,
    TruncationMarker,
    VocabularySection,
)
from glossabet.analysis.graphify import (
    build_structural_groups,
    disabled_structural_groups,
    structure_candidates,
)
from glossabet.analysis.importance import build_naming_candidates
from glossabet.analysis.terminology import build_terminology
from glossabet.analysis.vocabulary import DocumentationVocabulary, ProductionVocabulary
from glossabet.corpus.cache import load_cache, save_cache
from glossabet.corpus.config import load_config
from glossabet.corpus.extraction import SourceExtractor
from glossabet.corpus.imports import build_imports_section, module_of
from glossabet.corpus.scanner import WalkResult, detect_monorepo, walk_repository
from glossabet.corpus.tokenize import tokenization_contract, tokenize_identifier
from glossabet.runtime import git_state
from glossabet.runtime.artifacts import write_artifact
from glossabet.runtime.coverage import (
    CoverageLedger,
    capped_collection,
    location_sample,
)

E = TypeVar("E")

EVIDENCE_SCHEMA_VERSION = 17

EVIDENCE_FILE = "evidence.json"


@dataclass(frozen=True)
class Limits:
    """Detail caps for the evidence artifact's vocabulary tables."""

    tokens: int = 5000
    identifiers: int = 2000
    doc_terms: int = 2000
    locations_per_term: int = 5


def _capped(
    counter: Counter[str], cap: int, entry: Callable[[str, int], E],
) -> tuple[list[E], TruncationMarker | None, CoverageLedger]:
    """Top-`cap` entries by (-count, key), with the remainder logged: the
    kept entries, the truncation marker (``None`` when nothing was dropped),
    and the coverage ledger — the three fields of one vocabulary table."""
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    kept, coverage = capped_collection(
        ranked, cap, cap_reason=f"evidence detail cap is {cap} items"
    )
    dropped = ranked[cap:]
    truncated: TruncationMarker | None = None if not dropped else {
        "dropped_terms": len(dropped),
        "dropped_occurrences": sum(c for _, c in dropped),
    }
    return [entry(term, count) for term, count in kept], truncated, coverage


class _ModuleFold(TypedDict):
    """Per-module tallies of the code-file pass."""

    code_files: int
    languages: set[str]
    code_files_by_role: Counter[str]


def _empty_module_fold() -> _ModuleFold:
    return {"code_files": 0, "languages": set(), "code_files_by_role": Counter()}


@dataclass
class _CodeFold:
    """What one pass over the walk's code files accumulates besides the
    production vocabulary itself."""
    languages: Counter[str] = field(default_factory=Counter)
    modules: dict[str, _ModuleFold] = field(
        default_factory=lambda: defaultdict(_empty_module_fold)
    )
    file_imports: list[tuple[str, str, list[str]]] = field(default_factory=list)
    production_code_files: list[tuple[str, str]] = field(default_factory=list)
    analyzed_production_files: int = 0
    code_bytes: int = 0


def _fold_code_files(
    walk: WalkResult, extractor: SourceExtractor,
    vocabulary: ProductionVocabulary,
) -> _CodeFold:
    code = _CodeFold()
    for rel, language, role in walk.code_files:
        entry = extractor.code_entry(rel, language, role)
        if entry is None:
            continue
        code.code_bytes += entry["size"]  # on-disk bytes, not decoded characters
        code.languages[language] += 1
        module = module_of(rel)
        code.modules[module]["code_files"] += 1
        code.modules[module]["languages"].add(language)
        code.modules[module]["code_files_by_role"][role] += 1
        if role == "production":
            code.analyzed_production_files += 1
            code.production_code_files.append((rel, language))
            if entry["imports"]:
                code.file_imports.append((rel, language, entry["imports"]))
            vocabulary.fold(entry["identifiers"], rel, module, language)
    return code


def _fold_doc_files(
    walk: WalkResult, extractor: SourceExtractor,
    documentation: DocumentationVocabulary,
) -> tuple[list[DocFileEntry], int, int]:
    """Doc inventory entries, total words, and the production doc count."""
    doc_entries: list[DocFileEntry] = []
    doc_word_total = 0
    analyzed_production_doc_files = 0
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
    return doc_entries, doc_word_total, analyzed_production_doc_files


def _module_lists(
    modules: dict[str, _ModuleFold],
) -> tuple[list[ModuleRecord], list[ProductionModuleRecord]]:
    """All modules, and the production-scoped modules naming ranks over."""
    modules_list: list[ModuleRecord] = [
        {
            "path": path,
            "code_files": info["code_files"],
            "code_files_by_role": dict(sorted(info["code_files_by_role"].items())),
            "languages": sorted(info["languages"]),
        }
        for path, info in sorted(modules.items())
    ]
    production_modules_list: list[ProductionModuleRecord] = [
        {
            "path": path,
            "code_files": info["code_files_by_role"].get("production", 0),
            "languages": sorted(info["languages"]),
        }
        for path, info in sorted(modules.items())
        if info["code_files_by_role"].get("production", 0)
    ]
    return modules_list, production_modules_list


def _vocabulary_section(
    vocabulary: ProductionVocabulary, documentation: DocumentationVocabulary,
    limits: Limits,
) -> VocabularySection:
    def token_entry(term: str, count: int) -> TokenEntry:
        per_file = vocabulary.token_files[term]
        locations, locations_truncated = location_sample(
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

    def identifier_entry(name: str, count: int) -> IdentifierEntry:
        per_file = vocabulary.identifier_files[name]
        locations, locations_truncated = location_sample(
            per_file, limits.locations_per_term
        )
        return {
            "name": name,
            "tokens": tokenize_identifier(name),
            "count": count,
            "files": len(per_file),
            "modules": len({module_of(path) for path in per_file}),
            "locations": locations,
            "locations_truncated": locations_truncated,
        }

    def doc_term_entry(term: str, count: int) -> DocTermEntry:
        per_file = documentation.term_files[term]
        locations, locations_truncated = location_sample(
            per_file, limits.locations_per_term
        )
        return {
            "term": term,
            "count": count,
            "files": len(per_file),
            "locations": locations,
            "locations_truncated": locations_truncated,
        }

    tokens, tokens_truncated, tokens_coverage = _capped(
        vocabulary.token_counts, limits.tokens, token_entry
    )
    identifiers, identifiers_truncated, identifiers_coverage = _capped(
        vocabulary.identifier_counts, limits.identifiers, identifier_entry
    )
    doc_terms, doc_terms_truncated, doc_terms_coverage = _capped(
        documentation.term_counts, limits.doc_terms, doc_term_entry
    )
    token_table: TokenTable = {
        "items": tokens, "truncated": tokens_truncated,
        "coverage": tokens_coverage,
    }
    identifier_table: IdentifierTable = {
        "items": identifiers, "truncated": identifiers_truncated,
        "coverage": identifiers_coverage,
    }
    doc_term_table: DocTermTable = {
        "items": doc_terms, "truncated": doc_terms_truncated,
        "coverage": doc_terms_coverage,
    }
    return {
        "normalization": tokenization_contract(),
        "tokens": token_table,
        "identifiers": identifier_table,
        "doc_terms": doc_term_table,
    }


DEFAULT_LIMITS = Limits()


def build_evidence(root: Path, limits: Limits = DEFAULT_LIMITS,
                   cache: bool = False, stats: dict[str, int] | None = None,
                   graphify: bool = True) -> EvidenceDocument:
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
    code = _fold_code_files(walk, extractor, vocabulary)
    doc_entries, doc_word_total, analyzed_production_doc_files = (
        _fold_doc_files(walk, extractor, documentation)
    )

    if cache:
        save_cache(root, extractor.cache_files, git_stamp)
    if stats is not None:
        stats.update({
            "reused": extractor.reused, "extracted": extractor.extracted,
        })

    modules_list, production_modules_list = _module_lists(code.modules)
    imports_section = build_imports_section(
        code.file_imports, code.production_code_files
    )
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
    naming_candidates: NamingCandidates = {
        "modules": naming["modules"],
        "modules_dropped": naming["modules_dropped"],
        "terms": naming["terms"],
        "terms_dropped": naming["terms_dropped"],
        "structures": structural_naming["structures"],
        "structures_dropped": structural_naming["structures_dropped"],
        "structures_source_groups_dropped": (
            structural_naming["structures_source_groups_dropped"]
        ),
        "structures_complete": structural_naming["structures_complete"],
        "coverage": {
            "modules": naming["coverage"]["modules"],
            "terms": naming["coverage"]["terms"],
            "structures": structural_naming["coverage"]["structures"],
        },
    }

    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "generator": {"name": "glossabet", "version": __version__},
        "repository": {"git": git_stamp},
        "configuration": config.as_evidence(),
        "totals": {
            "source_files": len(walk.code_files) + len(walk.doc_files),
            "source_bytes": walk.corpus_budget.source_bytes,
            "code_files": len(walk.code_files),
            "doc_files": len(walk.doc_files),
            "code_files_by_role": dict(sorted(
                Counter(role for _, _, role in walk.code_files).items()
            )),
            "doc_files_by_role": dict(sorted(
                Counter(role for _, role in walk.doc_files).items()
            )),
            "other_files": walk.other_files,
            "code_bytes": code.code_bytes,
            "doc_words": doc_word_total,
        },
        "languages": dict(sorted(code.languages.items())),
        "modules": modules_list,
        "imports": imports_section,
        "naming_candidates": naming_candidates,
        "structural_groups": structural,
        "files": {
            "code": [
                {"path": path, "language": language, "role": role}
                for path, language, role in sorted(walk.code_files)
            ],
            "docs": sorted(doc_entries, key=lambda d: d["path"]),
        },
        "vocabulary": _vocabulary_section(vocabulary, documentation, limits),
        "terminology": {
            **terminology,
            "scope": {
                "roles": ["production"],
                "code_files": code.analyzed_production_files,
                "doc_files": analyzed_production_doc_files,
            },
        },
        "monorepo": detect_monorepo(root, walk, config),
        "skipped": {
            **walk.skipped_as_evidence(),
            "oversized_identifiers": vocabulary.oversized_identifiers,
            "corpus_budget": walk.corpus_budget.as_evidence(),
        },
    }


def write_evidence(root: Path, evidence: EvidenceDocument) -> Path:
    return write_artifact(root, EVIDENCE_FILE, evidence)


def persist_evidence(root: Path, *, graphify: bool = True) -> EvidenceDocument:
    """Build the evidence for one command run through the cache and write
    it — the step every evidence-reading command performs after opening
    its run."""
    evidence = build_evidence(root, cache=True, graphify=graphify)
    write_evidence(root, evidence)
    return evidence
