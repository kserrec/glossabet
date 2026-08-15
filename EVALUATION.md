# Evaluation

This document records Glossarize's Phase 15 calibration, Phase 16 lexical/scope
extension, and Phase 20 replay on the current engine. The machine-readable
corpus, labels, raw per-run timings, findings, truncation markers, provenance
digests, and threshold checks live in
[`evaluation/corpus.json`](evaluation/corpus.json) and
[`evaluation/results.json`](evaluation/results.json).

## What was evaluated

The corpus fixes five cases, including three repositories at immutable
revisions:

| Case | Language | Revision | License | Production code files |
|---|---|---|---|---:|
| Glossarize calibration fixture | Python | repository-local original source | Apache-2.0 | 6 |
| Language-semantics fixture | Python and Clojure, with multilingual identifiers | repository-local original source | Apache-2.0 | 5 |
| [Requests](https://github.com/psf/requests/tree/8068356288978c4f54661ae6f95afe0e0831885e) | Python | `8068356288978c4f54661ae6f95afe0e0831885e` | [Apache-2.0](https://github.com/psf/requests/blob/8068356288978c4f54661ae6f95afe0e0831885e/LICENSE) | 22 |
| [hey](https://github.com/rakyll/hey/tree/5626f79b8698df6daf9b25799c9805c6acc96740) | Go | `5626f79b8698df6daf9b25799c9805c6acc96740` | [Apache-2.0](https://github.com/rakyll/hey/blob/5626f79b8698df6daf9b25799c9805c6acc96740/LICENSE) | 6 |
| [p-limit](https://github.com/sindresorhus/p-limit/tree/df476048d023ff868cd45b35ee47f5fb0ca2b25a) | JavaScript and TypeScript declarations | `df476048d023ff868cd45b35ee47f5fb0ca2b25a` | [MIT](https://github.com/sindresorhus/p-limit/blob/df476048d023ff868cd45b35ee47f5fb0ca2b25a/license) | 6 |

Together they contain 90 included source/documentation files, 45 production
code files, 659,883 budgeted source bytes, and 190 walked entries. Third-party
source is fetched into a temporary directory for a run and is not vendored in
this repository. The local fixture is original Apache-2.0 material designed to
pin a true parallel rename, a discouraged term still in use, a stale canonical
term, and a genuinely overloaded term. The Phase 16 fixture pins two legitimate
`Session` concepts in disjoint path scopes plus 15 explicit normalization
checks covering Unicode scripts, accented Latin, acronyms with digit
suffixes, and Clojure kebab-case identifiers.

## Labelling method

One reviewer read each pinned repository's source and primary documentation,
then wrote a small evaluation glossary and labelled the emitted terminology
and drift findings as correct and useful or as false alarms. A finding is
"useful" only when the reviewer judged that showing it to a maintainer would
help a vocabulary review; correctness alone is not enough.

Precision treats every emitted but unlabelled finding as a false alarm. Recall
is reported only where a complete expected set is practical: all detectors in
the controlled fixture, and the finite watched-term/canonical-fading checks in
the real repositories. The evaluation does **not** claim recall over every
possible real-repository synonym or overloaded meaning.

The glossaries are evaluation instruments, not vocabularies endorsed by the
upstream maintainers. The reviewer also authored the corpus labels and the
calibration, so reviewer-usefulness is not independent or blinded. Those facts
make this a regression and release gate, not a user study.

The language-semantics labels are exact rather than subjective: required token
spellings, forbidden lossy spellings, and complete identifier-to-token
mappings. Its glossary is validated by the same production schema, and an
empty drift set is a complete expectation for that controlled fixture.

## Calibration result

The Phase 14 baseline emitted 64 scored findings. Eleven matched the labels and
53 were false alarms: 17.19% overall precision, 4% terminology-candidate
precision, 64.29% drift precision, and 1,325 false alarms per thousand
production code files. The dominant failure was synonym scoring: shared
contexts made distinct sibling fields look interchangeable—for example
`duration`/`min`, `request`/`delay`, and `cpu`/`io`.

Phase 15 made three conservative changes to the existing synonym heuristic:

1. candidate terms may overlap in at most 20% of the smaller term's files;
2. they must share at least two exact identifier substitution patterns, such
   as `*_queue` and `run_*`; and
3. context similarity must be at least 0.55 instead of 0.40.

The current Phase 20 five-run replay emitted 11 scored findings, all labelled
correct and useful, with no labelled finding missed where recall was complete:

| Metric | Result | Release threshold |
|---|---:|---:|
| Terminology precision | 100% | ≥80% |
| Drift precision | 100% | ≥90% |
| Recall where labels are complete | 100% | ≥90% |
| Reviewer usefulness | 100% | ≥80% |
| False alarms / 1,000 production code files | 0 | ≤50 |
| Corpus-budget truncations | 0 | 0 |
| Minimum warm-cache reuse | 100% | 100% |
| Phase 16 lexical contract | 15/15 (100%) | 100% |

All internal release thresholds pass. This does **not** establish 100%
real-world accuracy: eleven positive findings and three small external
repositories are far too little evidence for that claim. It establishes that
the pinned counterexamples and curated real-project checks pass and that future
changes have a reproducible gate.

## Phase 16 lexical and scope result

The Phase 15 implementation used an ASCII-only source identifier expression,
dropped digit runs, and had no language branch for Clojure kebab-case. Replaying
that contract against the 15 Phase 16 labels satisfied only 1 check: it lost
seven of eight required tokens, emitted both forbidden lossy
tokens (`http` and `json`), and missed or mis-tokenized all five required
identifier spellings. The Phase 16 lexical implementation satisfies all 15
without adding a parser. It also produces no terminology or drift finding for
the two deliberately disjoint `Session` meanings.

Glossary scope is an optional non-empty set of literal repository-relative
path prefixes. An omitted scope is repository-wide. Two owners may reuse an
NFKC-casefolded term or alias only when their path regions are disjoint; an
ancestor prefix and descendant overlap. Drift and lexical reconciliation
filter term occurrences and stable bindings to that region. The normalized
Graphify groups currently lack source paths, so structural reconciliation
marks scoped coverage partial or skips conclusions that could otherwise be
false. It does not infer scope from a group label.

## Runtime and truncation

On the recorded 8-core Linux host with CPython 3.12.3, the sum of per-case
five-run medians was 0.399 seconds cold and 0.358 seconds warm—4.43 and 3.97
seconds per thousand included source files. Every warm run reused 100% of
eligible extraction entries and produced evidence byte-identical to its cold
run. The corpus is too small for the measured warm/cold difference to establish
a general cache speedup; content hashing, Git checks, cache I/O, and aggregation
still run on warm scans.

Requests hit existing output caps: 1,072 identifier entries, 981 documentation
terms, and 15 external-import entries were omitted from their displayed
sections and reported by truncation markers. No repository hit the new corpus
budget. Exact absence checks already suppress conclusions when their required
index is truncated.

## Aggregate safety limits

The measured corpus took about 4.43 cold seconds per thousand source files.
The scanner now applies immutable per-repository ceilings of:

- 10,000 included code/documentation files;
- 32,000,000 included source bytes;
- 100,000 processed directory entries; and
- 10,000 entries in any one directory.

Relative to the whole evaluation corpus, these retain about 111× file, 48×
byte, and 526× walk-entry headroom. At the observed file-normalized rate, the
file ceiling corresponds to roughly 44 seconds; repository composition and
hardware can change that substantially, so it is a safety bound rather than a
runtime guarantee.

When a source-file or byte ceiling is reached, Glossarize continues its bounded
walk, includes later files that still fit, and reports exact skipped-file/byte
counts plus a bounded path sample. When a walk or per-directory ceiling is
reached, the unvisited remainder cannot be counted without defeating the work
limit; evidence therefore reports a lower bound, a reason/path sample, and
`exact: false`. In every case `skipped.corpus_budget.complete` becomes `false`
and the CLI states that the evidence is partial.

## Reproducing the result

This command fetches only the three pinned public repositories into a temporary
directory, runs five cold and five warm measurements per case, replaces the raw
result file, and exits nonzero if a release threshold fails:

```bash
uv run python evaluation/run.py --fetch --runs 5 --output evaluation/results.json --check
```

The evaluation helper invokes `git` without a shell, disables prompts and
global/system Git configuration, and does not run or import target-project
code. Fetch time is excluded from runtime measurements. Timings will vary by
machine; quality labels and finding keys should remain stable at the pinned
commits.

The result identifies engine version 0.1.0, the evidence/drift/evaluator schema
versions, a SHA-256 digest over the evaluator and every engine Python source
file, the exact manifest digest, and a framed path/content digest over every
accepted corpus file. The manifest pins that digest and accepted-file count for
all five cases; local fixtures are additionally recomputed without network,
while external cases retain their immutable commit identity. The reusable
release gate rejects stale engine/manifest/corpus metadata, missing or reordered
cases, malformed digests, fewer than five runs, or non-passing thresholds:

```bash
uv run python evaluation/run.py --verify-results evaluation/results.json
```

## Parsing-adapter decision

No parser dependency was added. The required trigger was a remaining labelled
failure for which parsing produced a measured accuracy gain. After the lexical
and scope work, the new fixture has 15/15 lexical checks, no false drift, and
the full corpus still has zero false alarms; there is therefore no measured
incremental benefit to justify a parser yet.

The concrete candidate reviewed on 2026-08-14 was
[`tree-sitter-language-pack` 1.14.3](https://pypi.org/project/tree-sitter-language-pack/1.14.3/).
Its Linux x86-64 wheel is 2,357,083 bytes and declares one runtime dependency,
[`tree-sitter >=0.23`](https://pypi.org/project/tree-sitter/0.26.0/); the current
`tree-sitter` 0.26.0 CPython 3.12 Linux wheel is 667,487 bytes. That is
3,024,570 bytes of initial native wheels before grammar data. The package supports 371
grammars by [downloading parsers on first use and caching them
locally](https://github.com/xberg-io/tree-sitter-language-pack#what-and-why),
which would add runtime network/data-flow behavior, native parser input
surface, user-cache state, and a large grammar/query compatibility matrix.
Using individual grammar wheels instead would require the core binding plus up
to 30 grammar packages to cover Glossarize's 30 current language labels.

GitHub's [global advisory query](https://api.github.com/advisories?ecosystem=pip&affects=tree-sitter-language-pack)
returned no published advisories affecting
either Python package, and the candidate repository's
[security-advisory page](https://github.com/xberg-io/tree-sitter-language-pack/security/advisories)
returned none on 2026-08-14. That is an alerts snapshot, not a claim that native
parsers are risk-free. With zero labelled errors left for parsing to fix, these
binary, transitive, network, security, and maintenance costs do not earn a
runtime dependency. A future parser proposal must add a labelled counterexample
and compare its accuracy against this recorded standard-library baseline.

## What remains unknown

- The corpus is small and biased toward compact open-source libraries.
- There is no independent maintainer or multi-reviewer usefulness study.
- Real-repository heuristic recall is not exhaustively labelled.
- Graphify-assisted structural findings are not evaluated here.
- The multilingual fixture covers representative Python and Clojure forms,
  not every identifier grammar among the 30 recognized languages.
- Lexical extraction still sees identifier-like words in comments and string
  contents. It does not claim parser-level symbol identity.
- Scoped structural validation remains partial until an adapter supplies
  trustworthy repository paths for normalized groups.
