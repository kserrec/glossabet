#!/usr/bin/env python3
"""Reproducible performance baseline for the engine's main builders.

The quick default uses checked-in fixtures. ``--scale`` adds deterministic
generated repositories and artifacts, also entirely inside the benchmark's
temporary directory. The extraction cache is confined there, and nothing
touches the network, the user's cache, or the working tree. Each case runs one
untimed warm-up, then ``--repeat`` timed repetitions; the report gives the
median wall time, the peak Python heap during the call
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
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
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


@dataclass(frozen=True)
class ScaleSizes:
    """Deterministic input sizes for the opt-in generated cases."""

    source_files: int
    source_directories: int
    terminology_terms: int
    compound_terms: int
    graph_groups: int
    graph_members_per_group: int


FULL_SCALE = ScaleSizes(
    source_files=1_000,
    source_directories=50,
    terminology_terms=175,
    compound_terms=750,
    graph_groups=60,
    graph_members_per_group=24,
)
CI_SCALE = ScaleSizes(
    source_files=40,
    source_directories=8,
    terminology_terms=40,
    compound_terms=30,
    graph_groups=8,
    graph_members_per_group=6,
)


def _output_bytes(value: object) -> int:
    """Bytes of the artifact this value would be written as: already
    serialized text as-is, a document in the artifact writer's format."""
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return len(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)) + 1


def _copy_fixture(name: str, work: Path) -> Path:
    target = work / name
    shutil.copytree(
        FIXTURES[name],
        target,
        symlinks=True,
        ignore=shutil.ignore_patterns(".env", "*.env", ".env.*", "*.env.*"),
    )
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
            "usable": result["usable"],
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
            "projection_complete": context["projection_complete"],
            "source_complete": context["source_complete"],
            "intentional_exclusions": len(context["intentional_exclusions"]),
            "source_omissions": len(context["source_omissions"]),
            "truncations": len(context["truncations"]),
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


def _scale_token(index: int) -> str:
    """A stable alphabetic token whose lexical form does not depend on locale."""
    letters = []
    number = index
    while True:
        number, remainder = divmod(number, 26)
        letters.append(chr(ord("a") + remainder))
        if number == 0:
            break
        number -= 1
    return "concept" + "".join(reversed(letters))


def _generate_scale_repository(root: Path, sizes: ScaleSizes) -> list[str]:
    """Create a many-directory source corpus and return its domain tokens."""
    terms = [_scale_token(index) for index in range(sizes.source_files)]
    for index, term in enumerate(terms):
        directory = root / f"package_{index % sizes.source_directories:03d}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"module_{index:04d}.py").write_text(
            f"def handle_{term}_record({term}_value: int) -> int:\n"
            f"    return {term}_value + 1\n",
            encoding="utf-8",
        )
    return terms


def _generate_scale_graph(root: Path, sizes: ScaleSizes) -> dict[str, object]:
    """Create a graph just beyond the structural-group output cap."""
    nodes: list[dict[str, object]] = []
    links: list[dict[str, str]] = []
    communities: list[dict[str, object]] = []
    for group_index in range(sizes.graph_groups):
        members = []
        for member_index in range(sizes.graph_members_per_group):
            node_id = f"g{group_index:03d}-n{member_index:03d}"
            members.append(node_id)
            nodes.append({
                "id": node_id,
                "label": (
                    f"{_scale_token(group_index)} "
                    f"{_scale_token(member_index)} service"
                ),
                "source_file": (
                    f"src/group_{group_index:03d}/module_{member_index:03d}.py"
                ),
            })
            if member_index:
                links.append({"source": members[-2], "target": node_id})
        communities.append({
            "id": f"group-{group_index:03d}",
            "label": f"{_scale_token(group_index)} subsystem",
            "cohesion": 0.75,
            "nodes": members,
        })
    document: dict[str, object] = {
        "built_at_commit": "a" * 40,
        "nodes": nodes,
        "links": links,
        "communities": communities,
    }
    graph_path = root / "graphify-out" / "graph.json"
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return document


def build_scale_cases(work: Path, sizes: ScaleSizes) -> list[Case]:
    """Generated scale evidence; callers opt in explicitly with ``--scale``."""
    from glossabet.agent.agent_context import (
        build_agent_context,
        serialize_agent_context,
    )
    from glossabet.analysis.evidence import build_evidence
    from glossabet.analysis.graphify import GROUP_CAP, build_structural_groups
    from glossabet.analysis.terminology import PAIR_TOP_N, build_terminology
    from glossabet.analysis.vocabulary import ProductionVocabulary
    from glossabet.glossary.matching import EvidenceIndex

    repository = work / "repository"
    terms = _generate_scale_repository(repository, sizes)
    graph_root = work / "graph"
    graph_document = _generate_scale_graph(graph_root, sizes)
    evidence = build_evidence(repository, cache=False)
    compound_terms = [
        f"handle {term} record" for term in terms[:sizes.compound_terms]
    ]

    vocabulary = ProductionVocabulary.from_files([
        (
            f"src/module_{index:04d}.py",
            f"package_{index % 20:02d}",
            "python",
            {f"route_{_scale_token(index)}_handler": 2},
        )
        for index in range(sizes.terminology_terms)
    ])

    def evidence_ledger(result: object) -> dict[str, object]:
        assert isinstance(result, dict)
        budget = result["skipped"]["corpus_budget"]
        return {
            "source_files": result["totals"]["source_files"],
            "source_directories": sizes.source_directories,
            "source_bytes": budget["used"]["source_bytes"],
            "source_files_complete": budget["complete"],
            "identifier_details": len(result["vocabulary"]["identifiers"]["items"]),
        }

    def terminology_ledger(result: object) -> dict[str, object]:
        assert isinstance(result, dict)
        coverage = result["coverage"]["eligible_tokens"]
        return {
            "eligible_tokens": coverage["total_items"],
            "considered_tokens": result["considered_tokens"],
            "pair_top_n": PAIR_TOP_N,
            "considered_pairs": result["synonym_candidates"]["considered_pairs"],
            "eligible_tokens_complete": coverage["complete"],
        }

    def matching_ledger(result: object) -> dict[str, object]:
        assert isinstance(result, EvidenceIndex)
        positions = result.coverage["compound_match_positions"]
        return {
            "glossary_terms": len(compound_terms),
            "identifier_entries": len(result.identifier_entries),
            "match_starts": positions["total_items"],
            "match_starts_processed": positions["included_items"],
            "match_work_complete": positions["complete"],
        }

    def graph_ledger(result: object) -> dict[str, object]:
        assert isinstance(result, dict)
        coverage = result["coverage"]["groups"]
        return {
            "input_nodes": len(graph_document["nodes"]),
            "input_edges": len(graph_document["links"]),
            "input_communities": len(graph_document["communities"]),
            "group_output_cap": GROUP_CAP,
            "groups_included": coverage["included_items"],
            "groups_dropped": coverage["dropped_items"],
            "groups_complete": coverage["complete"],
        }

    def context_case() -> str:
        return serialize_agent_context(build_agent_context(evidence, None, full=True))

    def context_ledger(result: object) -> dict[str, object]:
        assert isinstance(result, str)
        document = json.loads(result)
        context = document["coverage"]["context"]
        return {
            "source_files": evidence["totals"]["source_files"],
            "projection": context["projection"],
            "projection_complete": context["projection_complete"],
            "source_complete": context["source_complete"],
            "intentional_exclusions": len(context["intentional_exclusions"]),
            "source_omissions": len(context["source_omissions"]),
            "truncations": len(context["truncations"]),
        }

    stamp = {"head": "a" * 40, "dirty": False}
    return [
        Case(
            "scale_evidence_repository",
            f"generated repository: evidence over {sizes.source_files} source files",
            lambda: build_evidence(repository, cache=False),
            evidence_ledger,
        ),
        Case(
            "scale_terminology_top_n",
            f"generated vocabulary: {sizes.terminology_terms} domain terms near top-N",
            lambda: build_terminology(vocabulary, Counter()),
            terminology_ledger,
        ),
        Case(
            "scale_compound_matching",
            f"generated evidence: {len(compound_terms)} compound glossary terms",
            lambda: EvidenceIndex(evidence, compound_terms),
            matching_ledger,
            payload=lambda index: index.coverage,
        ),
        Case(
            "scale_graphify_group_cap",
            f"generated Graphify input: {sizes.graph_groups} communities near group cap",
            lambda: build_structural_groups(graph_root, stamp),
            graph_ledger,
        ),
        Case(
            "scale_agent_context",
            "full agent-context projection from the generated repository evidence",
            context_case,
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


def environment(scale_sizes: ScaleSizes | None = None) -> dict[str, object]:
    from glossabet import __version__

    details: dict[str, object] = {
        "glossabet": __version__,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "fixtures": {name: str(path.relative_to(ROOT)) for name, path in FIXTURES.items()},
    }
    if scale_sizes is not None:
        details["scale"] = asdict(scale_sizes)
    return details


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
    parser.add_argument(
        "--scale",
        action="store_true",
        help="add deterministic generated scale cases (off by default)",
    )
    parser.add_argument(
        "--scale-size",
        choices=("full", "ci"),
        default=None,
        help="generated input size; full by default with --scale, ci for tests",
    )
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    if args.scale_size is not None and not args.scale:
        parser.error("--scale-size requires --scale")
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
        scale_sizes = None
        if args.scale:
            scale_sizes = CI_SCALE if args.scale_size == "ci" else FULL_SCALE
            cases.extend(build_scale_cases(work / "scale", scale_sizes))
        if args.only:
            unknown = sorted(set(args.only) - {case.name for case in cases})
            if unknown:
                parser.error(f"unknown case(s): {', '.join(unknown)}")
            cases = [case for case in cases if case.name in args.only]
        measurements = [measure(case, args.repeat) for case in cases]
        env = environment(scale_sizes)
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
