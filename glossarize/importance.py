"""Importance signals -> ranked "likely deserves a name" nominations.

Every candidate carries its reasons in plain numbers; the score only orders
the list. Nomination evidence for the skill's Step 3, never truth.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from heapq import nsmallest

from glossarize.coverage import coverage_ledger

MODULE_CANDIDATE_CAP = 10
TERM_CANDIDATE_CAP = 15


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
                     doc_term_counts: Counter) -> Iterable[dict]:
    ranked = sorted(token_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    for term, count in ranked:
        files = len(token_files.get(term, ()))
        spread = len(token_modules.get(term, ()))
        doc_mentions = doc_term_counts.get(term, 0)
        if spread < 2 and not doc_mentions:
            continue  # a single-module term with no doc presence isn't hot
        reasons = [f"{count} use(s) across {files} file(s)"]
        if spread > 1:
            reasons.append(f"spread across {spread} module(s)")
        if doc_mentions:
            reasons.append(f"mentioned {doc_mentions} time(s) in docs")
        score = (
            spread * 3
            + min(files, 20)
            + math.log1p(count)
            + math.log1p(doc_mentions) * 4
        )
        yield {
            "kind": "term",
            "term": term,
            "score": round(score, 2),
            "reasons": reasons,
        }


def _ranked(
    candidates: Iterable[dict], cap: int, key, label: str
) -> tuple[list[dict], dict]:
    total = 0

    def counted():
        nonlocal total
        for candidate in candidates:
            total += 1
            yield candidate

    kept = nsmallest(cap, counted(), key=key)
    reasons = []
    if total > len(kept):
        reasons.append(f"{label} candidate detail cap is {cap} items")
    return kept, coverage_ledger(total, len(kept), reasons=reasons)


def build_naming_candidates(imports_section: dict, modules: list[dict],
                            token_counts: Counter, token_files: dict,
                            token_modules: dict,
                            doc_term_counts: Counter) -> dict:
    module_items, module_coverage = _ranked(
        _module_candidates(imports_section, modules, doc_term_counts),
        MODULE_CANDIDATE_CAP,
        key=lambda candidate: (-candidate["score"], candidate["path"]),
        label="module naming",
    )
    term_items, term_coverage = _ranked(
        _term_candidates(token_counts, token_files, token_modules, doc_term_counts),
        TERM_CANDIDATE_CAP,
        key=lambda candidate: (-candidate["score"], candidate["term"]),
        label="term naming",
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
