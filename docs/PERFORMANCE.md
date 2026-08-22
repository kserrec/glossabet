# Performance baseline

Glossabet has no measured runtime bottleneck; this document exists so that
claim rests on a reproducible measurement rather than intuition, and so any
future optimization can show a before/after on the same inputs.

## Reproduce

One command, standard library only, no network, no writes outside a
temporary directory:

```bash
uv run python scripts/benchmark.py
```

Options: `--repeat N` (timed repetitions per case, default 5), `--json PATH`
(machine-readable results and environment), `--profile` (a `cProfile`
summary of one run of every case, sorted by cumulative and internal time),
`--only CASE` (repeatable).

### Method

- **Inputs** are checked-in, git-tracked fixtures copied into a temporary
  directory before any measurement: `examples/payment-service` (its committed
  `glossabet-out/glossary.json` is the glossary), `evaluation/fixtures/
  language-semantics` (Python, Go, TypeScript, Rust, Ruby; its glossary is the
  one recorded in `evaluation/corpus.json`), `evaluation/fixtures/
  structural-complete`, and `evaluation/fixtures/structural-truncation` (both
  with committed `graphify-out/graph.json`). Fixture identity is therefore the
  repository commit.
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
heterogeneous and a threshold would only flake. The suite checks that the
script runs and reports every case.

### Cases

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

## Findings

**Time.** Every evidence build (~23 ms) is dominated by the two `git`
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
