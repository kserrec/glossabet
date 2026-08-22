#!/usr/bin/env python3
"""Reproducible performance baseline for the engine's main builders.

Standard library only. Every input is a checked-in fixture copied into a
temporary directory, the extraction cache is confined to that directory, and
nothing touches the network, the user's cache, or the working tree. Each case
runs one untimed warm-up, then ``--repeat`` timed repetitions; the report
gives the median wall time, the peak Python heap during the call
(``tracemalloc``), the artifact size the result would serialize to
(``json.dumps(sort_keys=True, indent=2)``, the artifact writer's format), and
the work/coverage ledger counts that explain the numbers.

Absolute timings are one machine's numbers, never a contract; see
``docs/PERFORMANCE.md`` for how to read and reproduce them.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import platform
import pstats
import shutil
import statistics
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURES = {
    "payment-service": ROOT / "examples" / "payment-service",
    "language-semantics": ROOT / "evaluation" / "fixtures" / "language-semantics",
    "structural-complete": ROOT / "evaluation" / "fixtures" / "structural-complete",
    "structural-truncation": ROOT / "evaluation" / "fixtures" / "structural-truncation",
}
CORPUS_MANIFEST = ROOT / "evaluation" / "corpus.json"


@dataclass(frozen=True)
class Case:
    name: str
    description: str
    run: Callable[[], object]
    ledger: Callable[[object], dict[str, object]]
    before: Callable[[], None] = lambda: None
    # What the result serializes to; the identity for documents, the
    # coverage record for in-memory indexes.
    payload: Callable[[object], object] = lambda result: result


@dataclass(frozen=True)
class Measurement:
    name: str
    description: str
    median_ms: float
    min_ms: float
    peak_kib: float
    output_bytes: int
    ledger: dict[str, object]


def _output_bytes(value: object) -> int:
    """Bytes of the artifact this value would be written as: already
    serialized text as-is, a document in the artifact writer's format."""
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return len(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)) + 1


def _copy_fixture(name: str, work: Path) -> Path:
    target = work / name
    shutil.copytree(FIXTURES[name], target, symlinks=True)
    return target


def _manifest_glossary(source_id: str) -> dict[str, object]:
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    for source in manifest["sources"]:
        if source["id"] == source_id:
            glossary: dict[str, object] = source["glossary"]
            return glossary
    raise KeyError(source_id)


def build_cases(work: Path, cache_dir: Path) -> list[Case]:
    """Every benchmark case over fixtures copied under ``work``."""
    from glossabet.agent.agent_context import (
        build_agent_context,
        serialize_agent_context,
    )
    from glossabet.analysis.evidence import (
        DocumentationVocabulary,
        ProductionVocabulary,
        SourceExtractor,
        _fold_code_files,
        _fold_doc_files,
        build_evidence,
    )
    from glossabet.analysis.graphify import build_structural_groups
    from glossabet.analysis.terminology import build_terminology
    from glossabet.corpus.config import load_config
    from glossabet.corpus.scanner import walk_repository
    from glossabet.glossary.drift import build_drift
    from glossabet.glossary.findings import glossary_terms
    from glossabet.glossary.matching import EvidenceIndex
    from glossabet.glossary.store import load_glossary, save_glossary
    from glossabet.runtime import git_state

    payment = _copy_fixture("payment-service", work)
    semantics = _copy_fixture("language-semantics", work)
    complete = _copy_fixture("structural-complete", work)
    truncation = _copy_fixture("structural-truncation", work)
    save_glossary(semantics, _manifest_glossary("language-semantics-fixture"))

    payment_glossary = load_glossary(payment)
    semantics_glossary = load_glossary(semantics)
    assert payment_glossary is not None and semantics_glossary is not None

    payment_evidence = build_evidence(payment, cache=False)
    semantics_evidence = build_evidence(semantics, cache=False)
    semantics_terms = glossary_terms(semantics_glossary)

    def clear_cache_dir() -> None:
        shutil.rmtree(cache_dir, ignore_errors=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

    def evidence_ledger(evidence: object) -> dict[str, object]:
        assert isinstance(evidence, dict)
        budget = evidence["skipped"]["corpus_budget"]
        totals = evidence["totals"]
        return {
            "code_files": totals["code_files"],
            "doc_files": totals["doc_files"],
            "budget_used_source_files": budget["used"]["source_files"],
            "budget_used_source_bytes": budget["used"]["source_bytes"],
            "corpus_complete": budget["complete"],
        }

    def terminology_inputs() -> tuple[ProductionVocabulary, DocumentationVocabulary]:
        config = load_config(semantics)
        walk = walk_repository(semantics, config)
        extractor = SourceExtractor(semantics, None, walk.corpus_budget)
        vocabulary = ProductionVocabulary()
        documentation = DocumentationVocabulary()
        _fold_code_files(walk, extractor, vocabulary)
        _fold_doc_files(walk, extractor, documentation)
        return vocabulary, documentation

    vocabulary, documentation = terminology_inputs()

    def terminology_ledger(result: object) -> dict[str, object]:
        assert isinstance(result, dict)
        return {
            "synonym_considered_pairs": result["synonym_candidates"]["considered_pairs"],
            "synonym_items": len(result["synonym_candidates"]["items"]),
            "overload_items": len(result["overload_candidates"]["items"]),
        }

    def matching_ledger(index: object) -> dict[str, object]:
        assert isinstance(index, EvidenceIndex)
        return {
            "glossary_terms": len(semantics_terms),
            "identifier_entries": len(index.identifier_entries),
            "compound_positions_complete": (
                index.coverage["compound_match_positions"]["complete"]
            ),
        }

    def drift_ledger(result: object) -> dict[str, object]:
        assert isinstance(result, dict)
        return {
            "findings": sum(
                len(section["items"])
                for name, section in result.items()
                if isinstance(section, dict) and "items" in section
            ),
            "collections_complete": all(
                ledger["complete"]
                for ledger in result["coverage"]["collections"].values()
            ),
            "production_corpus_complete": (
                result["coverage"]["production_corpus_complete"]
            ),
        }

    def structural_ledger(result: object) -> dict[str, object]:
        assert isinstance(result, dict)
        return {
            "available": result["available"],
            "groups": len(result["groups"]),
            "groups_dropped": result["groups_dropped"],
            "groups_complete": result["coverage"]["groups"]["complete"],
        }

    def context_ledger(serialized: object) -> dict[str, object]:
        assert isinstance(serialized, str)
        document = json.loads(serialized)
        context = document["coverage"]["context"]
        return {
            "projection": context["projection"],
            "complete": context["complete"],
            "omissions": len(context["omissions"]),
        }

    def context_case(full: bool) -> str:
        return serialize_agent_context(
            build_agent_context(payment_evidence, payment_glossary, full=full)
        )

    git_stamp = git_state.repository_git_stamp(complete)
    return [
        Case(
            "evidence_cold",
            "payment-service: build_evidence(cache=True) with an empty cache",
            lambda: build_evidence(payment, cache=True),
            evidence_ledger,
            before=clear_cache_dir,
        ),
        Case(
            "evidence_warm",
            "payment-service: build_evidence(cache=True) with a warm cache",
            lambda: build_evidence(payment, cache=True),
            evidence_ledger,
        ),
        Case(
            "evidence_multilanguage",
            "language-semantics (Python/Go/TypeScript/Rust/Ruby): build_evidence(cache=False)",
            lambda: build_evidence(semantics, cache=False),
            evidence_ledger,
        ),
        Case(
            "terminology",
            "language-semantics: build_terminology over the folded production vocabulary",
            lambda: build_terminology(vocabulary, documentation.term_counts),
            terminology_ledger,
        ),
        Case(
            "compound_matching",
            "language-semantics: EvidenceIndex over the glossary's terms (one bounded trie pass)",
            lambda: EvidenceIndex(semantics_evidence, semantics_terms),
            matching_ledger,
            payload=lambda index: index.coverage,
        ),
        Case(
            "drift",
            "language-semantics: build_drift against the manifest glossary",
            lambda: build_drift(semantics_evidence, semantics_glossary),
            drift_ledger,
        ),
        Case(
            "graphify_complete",
            "structural-complete: build_structural_groups (graph loaded in full)",
            lambda: build_structural_groups(complete, git_stamp),
            structural_ledger,
        ),
        Case(
            "graphify_truncated",
            "structural-truncation: build_structural_groups (groups capped)",
            lambda: build_structural_groups(truncation, git_stamp),
            structural_ledger,
        ),
        Case(
            "agent_context_lean",
            "payment-service: build_agent_context(full=False) + serialize",
            lambda: context_case(False),
            context_ledger,
        ),
        Case(
            "agent_context_full",
            "payment-service: build_agent_context(full=True) + serialize",
            lambda: context_case(True),
            context_ledger,
        ),
    ]


def measure(case: Case, repeat: int) -> Measurement:
    case.before()
    warm = case.run()  # untimed warm-up: imports, first-touch allocations
    timings: list[float] = []
    peaks: list[int] = []
    result = warm
    for _ in range(repeat):
        case.before()
        tracemalloc.start()
        started = time.perf_counter()
        result = case.run()
        timings.append(time.perf_counter() - started)
        peaks.append(tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()
    return Measurement(
        name=case.name,
        description=case.description,
        median_ms=statistics.median(timings) * 1000,
        min_ms=min(timings) * 1000,
        peak_kib=statistics.median(peaks) / 1024,
        output_bytes=_output_bytes(case.payload(result)),
        ledger=case.ledger(result),
    )


def profile(cases: list[Case], top: int) -> str:
    profiler = cProfile.Profile()
    for case in cases:
        case.before()
        case.run()  # warm-up outside the profile
        case.before()
        profiler.enable()
        case.run()
        profiler.disable()
    buffer = io.StringIO()
    stats = pstats.Stats(profiler, stream=buffer)
    stats.sort_stats("cumulative").print_stats(top)
    stats.sort_stats("tottime").print_stats(top)
    return buffer.getvalue()


def environment() -> dict[str, object]:
    from glossabet import __version__

    return {
        "glossabet": __version__,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "fixtures": {name: str(path.relative_to(ROOT)) for name, path in FIXTURES.items()},
    }


def render(measurements: list[Measurement], repeat: int) -> str:
    lines = [
        f"Glossabet benchmark — {repeat} timed repetition(s) after 1 warm-up; "
        "median wall time, median peak heap (tracemalloc), serialized bytes",
        "",
        f"{'case':<24}{'median ms':>12}{'min ms':>10}{'peak KiB':>12}{'bytes':>10}  ledger",
    ]
    for item in measurements:
        ledger = ", ".join(f"{key}={value}" for key, value in item.ledger.items())
        lines.append(
            f"{item.name:<24}{item.median_ms:>12.2f}{item.min_ms:>10.2f}"
            f"{item.peak_kib:>12.0f}{item.output_bytes:>10}  {ledger}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=5,
                        help="timed repetitions per case after one warm-up (default 5)")
    parser.add_argument("--json", type=Path, default=None,
                        help="also write the measurements and environment as JSON")
    parser.add_argument("--profile", action="store_true",
                        help="print a cProfile summary of one run of every case")
    parser.add_argument("--top", type=int, default=25,
                        help="rows per cProfile table (default 25)")
    parser.add_argument("--only", action="append", default=None,
                        help="run only the named case (repeatable)")
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    for name, path in FIXTURES.items():
        if not path.is_dir():
            print(f"benchmark: fixture is missing: {name} ({path})", file=sys.stderr)
            return 1

    with tempfile.TemporaryDirectory(prefix="glossabet-benchmark-") as raw:
        work = Path(raw)
        cache_dir = work / "cache"
        cache_dir.mkdir()
        os.environ["GLOSSABET_CACHE_DIR"] = str(cache_dir)
        cases = build_cases(work / "fixtures", cache_dir)
        if args.only:
            unknown = sorted(set(args.only) - {case.name for case in cases})
            if unknown:
                parser.error(f"unknown case(s): {', '.join(unknown)}")
            cases = [case for case in cases if case.name in args.only]
        measurements = [measure(case, args.repeat) for case in cases]
        env = environment()
        print(f"python {env['python']} ({env['implementation']}) on {env['platform']}")
        print(render(measurements, args.repeat))
        if args.profile:
            print()
            print(profile(cases, args.top))
        if args.json is not None:
            args.json.write_text(json.dumps({
                "environment": env,
                "repeat": args.repeat,
                "measurements": [item.__dict__ for item in measurements],
            }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
