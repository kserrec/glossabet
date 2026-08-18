"""Importance signals -> ranked "likely deserves a name" nominations.

Every candidate carries its reasons in plain numbers; the score only orders
the list. Nomination evidence for the skill's Step 3, never truth.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import PurePosixPath

from glossabet.runtime.coverage import capped_collection
from glossabet.analysis.vocabulary import ProductionVocabulary
from glossabet.corpus.tokenize import (
    TOKEN_ORIGIN_DOMAIN,
    TOKEN_ORIGIN_LANGUAGE,
    tokenize_identifier,
)

MODULE_CANDIDATE_CAP = 10
TERM_CANDIDATE_CAP = 15
SOURCE_UNIT_ANCHOR_WEIGHT = 15
NOMINATION_CANONICAL_NAME = "deserves a canonical name"
NOMINATION_DISAMBIGUATION = "deserves disambiguation"


def _module_candidates(imports_section: dict, modules: list[dict],
                       doc_term_counts: Counter) -> Iterable[dict]:
    fan_in: dict[str, set] = defaultdict(set)
    fan_out: dict[str, set] = defaultdict(set)
    weight: Counter = Counter()
    for edge in imports_section["internal_edges"]:
        fan_in[edge["to"]].add(edge["from"])
        fan_out[edge["from"]].add(edge["to"])
        weight[edge["to"]] += edge["count"]

    by_path = {m["path"]: m for m in modules}
    for path, importers in fan_in.items():
        if path == ".":
            continue  # the repo root is not a nameable part
        info = by_path.get(path, {})
        code_files = info.get("code_files", 0)
        base = path.rsplit("/", 1)[-1].lower()
        doc_mentions = doc_term_counts.get(base, 0)
        reasons = [f"imported by {len(importers)} module(s)"]
        if code_files:
            reasons.append(f"{code_files} code file(s)")
        if fan_out.get(path):
            reasons.append(f"imports {len(fan_out[path])} module(s)")
        if doc_mentions:
            reasons.append(f"mentioned {doc_mentions} time(s) in docs")
        score = (
            len(importers) * 3
            + math.log1p(code_files) * 2
            + math.log1p(weight[path])
            + math.log1p(doc_mentions) * 2
        )
        yield {
            "kind": "module",
            "path": path,
            "score": round(score, 2),
            "reasons": reasons,
        }


def _term_candidates(token_counts: Counter, token_files: dict,
                     token_modules: dict,
                     doc_term_counts: Counter,
                     token_origins: dict[str, str],
                     token_patterns: dict,
                     context_dispersion: dict) -> Iterable[dict]:
    dispersion_by_term = {
        item["term"]: item
        for item in context_dispersion.get("items", [])
    }
    ranked = sorted(token_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    for term, count in ranked:
        if token_origins.get(term) != TOKEN_ORIGIN_DOMAIN:
            continue
        files = len(token_files.get(term, ()))
        spread = len(token_modules.get(term, ()))
        doc_mentions = doc_term_counts.get(term, 0)
        if spread < 2:
            continue  # naming importance requires repository breadth
        patterns = token_patterns.get(term, Counter())
        distinct_compounds = len(patterns)
        compound_uses = sum(patterns.values())
        compound_density = compound_uses / max(1, count)
        compound_diversity = distinct_compounds / math.sqrt(max(1, count))
        source_units_named = sum(
            tokenize_identifier(PurePosixPath(path).stem) == [term]
            for path in token_files.get(term, ())
        )
        reasons = [
            f"{count} use(s) across {files} file(s)",
            f"spread across {spread} module(s)",
        ]
        if doc_mentions:
            reasons.append(f"mentioned {doc_mentions} time(s) in docs")
        reasons.append(
            f"{distinct_compounds} distinct compound pattern(s) across "
            f"{compound_uses} compound use(s)"
        )
        if source_units_named:
            reasons.append(f"names {source_units_named} source file(s)")
        dispersion = dispersion_by_term.get(term)
        nomination_kind = NOMINATION_CANONICAL_NAME
        if dispersion is not None:
            reasons.append(
                f"context dispersion {dispersion['dispersion']} across "
                f"{dispersion['modules']} module(s)"
            )
            if dispersion["divergent"]:
                nomination_kind = NOMINATION_DISAMBIGUATION
        score = (
            spread * 2
            + math.log1p(min(count, 100))
            + math.log1p(doc_mentions) * 2
            + compound_diversity * 8
            + (distinct_compounds / max(1, files)) * 6
            + compound_density * 4
            + min(source_units_named, 1) * SOURCE_UNIT_ANCHOR_WEIGHT
        )
        yield {
            "kind": "term",
            "nomination_kind": nomination_kind,
            "term": term,
            "score": round(score, 2),
            "reasons": reasons,
        }


def _ranked(
    candidates: Iterable[dict], cap: int, key, label: str,
    *, incomplete_reasons: Iterable[str] = (),
) -> tuple[list[dict], dict]:
    return capped_collection(
        sorted(candidates, key=key),
        cap,
        cap_reason=f"{label} candidate detail cap is {cap} items",
        incomplete_reasons=incomplete_reasons,
    )


def build_naming_candidates(imports_section: dict, modules: list[dict],
                            vocabulary: ProductionVocabulary,
                            doc_term_counts: Counter,
                            context_dispersion: dict | None = None) -> dict:
    """Ranked module and term naming candidates from import structure, the
    production vocabulary, documentation, and terminology dispersion."""
    token_counts = vocabulary.token_counts
    token_files = vocabulary.token_files
    token_modules = vocabulary.token_modules
    token_origins = vocabulary.token_origins
    token_patterns = vocabulary.token_patterns
    context_dispersion = context_dispersion or {}
    language_tokens_excluded = vocabulary.language_token_count()
    untagged_tokens_excluded = sum(
        term not in token_origins for term in token_counts
    )
    term_input_reasons = []
    if language_tokens_excluded:
        term_input_reasons.append(
            f"{language_tokens_excluded} language-origin vocabulary token(s) "
            "excluded from the term naming candidate pool"
        )
    if untagged_tokens_excluded:
        term_input_reasons.append(
            f"{untagged_tokens_excluded} untagged vocabulary token(s) "
            "excluded from the domain-only term naming candidate pool"
        )
    module_input_reasons = []
    if imports_section.get("edges_truncated"):
        module_input_reasons.append(
            f"{imports_section['edges_truncated']} import edge(s) beyond the "
            "edge cap were unavailable to module naming candidates"
        )
    module_items, module_coverage = _ranked(
        _module_candidates(imports_section, modules, doc_term_counts),
        MODULE_CANDIDATE_CAP,
        key=lambda candidate: (-candidate["score"], candidate["path"]),
        label="module naming",
        incomplete_reasons=module_input_reasons,
    )
    term_items, term_coverage = _ranked(
        _term_candidates(
            token_counts, token_files, token_modules, doc_term_counts,
            token_origins, token_patterns, context_dispersion,
        ),
        TERM_CANDIDATE_CAP,
        key=lambda candidate: (-candidate["score"], candidate["term"]),
        label="term naming",
        incomplete_reasons=term_input_reasons,
    )
    return {
        "modules": module_items,
        "modules_dropped": module_coverage["dropped_items"],
        "terms": term_items,
        "terms_dropped": term_coverage["dropped_items"],
        "coverage": {
            "modules": module_coverage,
            "terms": term_coverage,
        },
    }
