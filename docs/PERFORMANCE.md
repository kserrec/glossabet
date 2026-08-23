# Performance baseline

Glossabet has no measured runtime bottleneck; this document exists so that
claim rests on a reproducible measurement rather than intuition, and so any
future optimization can show a before/after on the same inputs.

## Reproduce

The quick smoke suite is the default. It uses checked-in fixtures, performs no
network access, and writes its inputs and cache only under a temporary
directory:

```bash
uv run python scripts/benchmark.py
```

The generated scale suite is opt-in and adds five larger deterministic cases:

```bash
uv run python scripts/benchmark.py --scale --repeat 3
```

Options: `--repeat N` (timed repetitions per case, default 5), `--json PATH`
(machine-readable results and environment), `--profile` (a `cProfile`
summary of one run of every case, sorted by cumulative and internal time),
`--only CASE` (repeatable), `--scale` (add the generated cases), and
`--scale-size ci` (reduced generated inputs used only to test the harness).

### Method

- **Smoke inputs** are checked-in, git-tracked fixtures copied into a temporary
  directory before any measurement: `examples/payment-service` (its committed
  `glossabet-out/glossary.json` is the glossary), `evaluation/fixtures/
  language-semantics` (Python, Go, TypeScript, Rust, Ruby; its glossary is the
  one recorded in `evaluation/corpus.json`), `evaluation/fixtures/
  structural-complete`, and `evaluation/fixtures/structural-truncation` (both
  with committed `graphify-out/graph.json`). Fixture identity is therefore the
  repository commit.
- **Scale inputs** are deterministically constructed under the same temporary
  directory. The full sizes are 1,000 source files in 50 directories, 175
  terminology terms, 750 compound glossary terms, and 60 Graphify communities
  containing 1,440 nodes. No large generated fixture is committed.
- **Cache** is confined to the temporary directory through
  `GLOSSABET_CACHE_DIR`; `evidence_cold` empties it before every repetition,
  `evidence_warm` runs against the cache the previous run left.
- **Warm-up policy:** every case runs once untimed (imports, first-touch
  allocations, `git` resolution), then `--repeat` timed repetitions.
- **Wall time** is `time.perf_counter` around the builder call; the table
  reports the median.
- **Peak memory** is `tracemalloc`'s peak traced Python heap during the call
  (median across repetitions). It counts Python allocations only — not the
  interpreter's baseline, the `git` subprocess, or OS file cache.
- **Bytes** is the size the result would be written as by the artifact
  writer (`json.dumps(sort_keys=True, indent=2)` plus a newline), or the
  serialized agent context's UTF-8 length.
- **Ledger** columns are the work/coverage counts that explain the numbers
  (corpus budget used, considered pairs, groups dropped, context omissions).

There are deliberately no absolute timing assertions in CI: runners are
heterogeneous and a threshold would only flake. The suite checks the quick
default and a reduced, 40-file form of every scale generator, including each
reported work/coverage ledger.

### Smoke fixture cases

- `evidence_cold` — payment-service: build_evidence(cache=True) with an empty cache
- `evidence_warm` — payment-service: build_evidence(cache=True) with a warm cache
- `evidence_multilanguage` — language-semantics (Python/Go/TypeScript/Rust/Ruby): build_evidence(cache=False)
- `terminology` — language-semantics: build_terminology over the folded production vocabulary
- `compound_matching` — language-semantics: EvidenceIndex over the glossary's terms (one bounded trie pass)
- `drift` — language-semantics: build_drift against the manifest glossary
- `graphify_complete` — structural-complete: build_structural_groups (graph loaded in full)
- `graphify_truncated` — structural-truncation: build_structural_groups (groups capped)
- `agent_context_lean` — payment-service: build_agent_context(full=False) + serialize
- `agent_context_full` — payment-service: build_agent_context(full=True) + serialize

### Generated scale cases

- `scale_evidence_repository` — evidence generation over 1,000 small source
  files distributed across 50 directories, below every corpus budget.
- `scale_terminology_top_n` — 175 generated domain terms, enough to fill the
  configured 150-token pairwise boundary.
- `scale_compound_matching` — 750 compound terms against 2,000 identifier
  entries, below the matching work budget.
- `scale_graphify_group_cap` — 1,440 nodes, 1,380 edges, and 60 communities,
  deliberately just beyond the 50-group output cap.
- `scale_agent_context` — full context projection from the 1,000-file evidence
  document.

## Baseline — Linux-6.17.0-35-generic-x86_64-with-glibc2.39, CPython 3.12.3, Glossabet 0.1.0

Measured 2026-08-22 on one developer machine (x86_64); these are
that machine's numbers, not a contract. `--repeat 5`. The "peak before"
column is the same commit's reader before the change described below.

| case | median ms | peak KiB before | peak KiB after | bytes | ledger |
|---|---:|---:|---:|---:|---|
| `evidence_cold` | 28.6 | 87 | 87 | 31,033 | budget_used_source_bytes=850, budget_used_source_files=2, code_files=1, corpus_complete=True, doc_files=1 |
| `evidence_warm` | 29.0 | 62,508 | 138 | 31,033 | budget_used_source_bytes=850, budget_used_source_files=2, code_files=1, corpus_complete=True, doc_files=1 |
| `evidence_multilanguage` | 23.2 | 131 | 131 | 38,061 | budget_used_source_bytes=741, budget_used_source_files=6, code_files=5, corpus_complete=True, doc_files=1 |
| `terminology` | 1.8 | 6 | 6 | 3,851 | overload_items=0, synonym_considered_pairs=28, synonym_items=0 |
| `compound_matching` | 0.4 | 6 | 6 | 353 | compound_positions_complete=True, glossary_terms=6, identifier_entries=21 |
| `drift` | 1.4 | 10 | 10 | 2,689 | collections_complete=True, findings=0, production_corpus_complete=True |
| `graphify_complete` | 2.3 | 62,505 | 136 | 5,754 | available=True, groups=5, groups_complete=True, groups_dropped=0 |
| `graphify_truncated` | 6.3 | 62,505 | 140 | 40,462 | available=True, groups=50, groups_complete=False, groups_dropped=1 |
| `agent_context_lean` | 10.4 | 100 | 100 | 17,594 | complete=False, omissions=4, projection=lean |
| `agent_context_full` | 11.6 | 102 | 102 | 17,813 | complete=False, omissions=1, projection=full |

## Generated scale observation — Linux-6.17.0-35-generic-x86_64-with-glibc2.39, CPython 3.12.3

Measured 2026-08-22 on the same developer machine with `--scale --repeat 3`.
These wall times include `tracemalloc` overhead and describe this environment,
not other machines or future commits.

| case | median ms | peak KiB | bytes | work/coverage evidence |
|---|---:|---:|---:|---|
| `scale_evidence_repository` | 4,209.27 | 20,849 | 1,263,767 | source_files=1,000, source_directories=50, source_bytes=89,816, source_files_complete=True, identifier_details=2,000 |
| `scale_terminology_top_n` | 516.51 | 31 | 9,628 | eligible_tokens=177, considered_tokens=150, pair_top_n=150, considered_pairs=11,175, eligible_tokens_complete=False |
| `scale_compound_matching` | 83.26 | 810 | 361 | glossary_terms=750, identifier_entries=2,000, match_starts=5,000, match_starts_processed=5,000, match_work_complete=True |
| `scale_graphify_group_cap` | 201.87 | 1,600 | 80,394 | input_nodes=1,440, input_edges=1,380, input_communities=60, group_output_cap=50, groups_included=50, groups_dropped=10, groups_complete=False |
| `scale_agent_context` | 277.30 | 3,106 | 137,867 | source_files=1,000, projection=full, projection_complete=False, omissions=4 |

The two incomplete ledgers are expected and explicit: terminology received
177 eligible terms but intentionally analyzed only its top 150, and Graphify
retained 50 of 60 known communities. Repository traversal and compound
matching remained complete. A profile of the same generated repository took
1.92 seconds without traced-allocation measurement; 1.32 seconds was the
bounded terminology analysis, chiefly its 11,175 pair comparisons. That is a
visible cost at generated scale, but it is the intended fixed upper boundary,
not an unbounded growth path or a material interactive defect. No production
optimization was justified.

## Self-scan observation

Also measured 2026-08-22 with three repetitions over a temporary copy of the
current Glossabet working tree. The copy explicitly excluded `.git`, the
virtual environment, tool caches, and all dotenv filename variants; evidence
generation used `cache=False`. The median with `tracemalloc` enabled was
4,888.21 ms with a 21,274 KiB peak and a 4,288,581-byte serialized document.
The ledger reported 152 source files, 2,032,272 source bytes, and a complete
corpus. This is a changing-worktree observation, not a stable fixture or a
performance gate.

## Findings

**Smoke time.** Every fixture evidence build (~23 ms) is dominated by the two `git`
subprocess calls of the freshness stamp (`repository_git_stamp`, ~6 ms of
Python-side wait per call on this machine) and process start-up; the
Python-side work — walk, extraction, tokenization, terminology, naming — is a
few milliseconds on these fixtures. No single Python function dominates the
profile (`--profile`); the largest internal-time entries are `tokenize_identifier`
and `pathlib` path construction at well under a millisecond each. No
time optimization was justified.

**Memory.** One hotspot dominated every case that reads a repository JSON
document (the extraction cache, `graph.json`, `glossary.json`): the bounded
reader requested `cap + 1` bytes in one `read()` call, and CPython allocates
the requested size up front, so a two-byte file under the 64 MB repository
JSON bound peaked at ~62 MB of Python heap. `runtime.artifacts.read_bounded_bytes`
now reads in growing chunks (64 KiB doubling to 1 MiB) up to the same
`cap + 1` limit, so peak memory follows the content. Output is byte-identical
(the bound is still judged from the bytes read; `tests/test_artifacts.py`
pins both the memory ceiling and the cross-chunk bound), and the three
affected cases fell from ~62,500 KiB to ~140 KiB with no timing change.

No other optimization was identified as justified.
