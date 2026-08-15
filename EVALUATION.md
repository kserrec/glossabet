# Evaluation

This document records Glossabet's Phase 15 calibration, Phase 16 lexical/scope
extension, Phase 20 replay, and Phase 22 structural, installed-agent, and
second-reviewer evidence. The machine-readable corpus, labels, raw per-run
timings, findings, truncation markers, provenance digests, and threshold checks
live in
[`evaluation/corpus.json`](evaluation/corpus.json) and
[`evaluation/results.json`](evaluation/results.json). Installed-agent and
second-reviewer evidence live in the adjacent `agent-*` and `reviewer-*` files.

## What was evaluated

The corpus fixes seven cases, including three repositories at immutable
revisions:

| Case | Language | Revision | License | Production code files |
|---|---|---|---|---:|
| Glossabet calibration fixture | Python | repository-local original source | Apache-2.0 | 6 |
| Language-semantics fixture | Python and Clojure, with multilingual identifiers | repository-local original source | Apache-2.0 | 5 |
| [Requests](https://github.com/psf/requests/tree/8068356288978c4f54661ae6f95afe0e0831885e) | Python | `8068356288978c4f54661ae6f95afe0e0831885e` | [Apache-2.0](https://github.com/psf/requests/blob/8068356288978c4f54661ae6f95afe0e0831885e/LICENSE) | 22 |
| [hey](https://github.com/rakyll/hey/tree/5626f79b8698df6daf9b25799c9805c6acc96740) | Go | `5626f79b8698df6daf9b25799c9805c6acc96740` | [Apache-2.0](https://github.com/rakyll/hey/blob/5626f79b8698df6daf9b25799c9805c6acc96740/LICENSE) | 6 |
| [p-limit](https://github.com/sindresorhus/p-limit/tree/df476048d023ff868cd45b35ee47f5fb0ca2b25a) | JavaScript and TypeScript declarations | `df476048d023ff868cd45b35ee47f5fb0ca2b25a` | [MIT](https://github.com/sindresorhus/p-limit/blob/df476048d023ff868cd45b35ee47f5fb0ca2b25a/license) | 6 |
| Structural-completeness fixture | Python plus a hand-authored Graphify export | repository-local original source | Apache-2.0 | 6 |
| Structural-truncation fixture | Python plus a capped hand-authored Graphify export | repository-local original source | Apache-2.0 | 1 |

Together they contain 99 included source/documentation files, 52 production
code files, 661,164 budgeted source bytes, and 204 walked entries. Third-party
source is fetched into a temporary directory for a run and is not vendored in
this repository. The calibration fixture pins a true parallel rename, a
discouraged term still in use, a stale canonical term, and a genuinely
overloaded term. The Phase 16 fixture pins two legitimate `Session` concepts
in disjoint path scopes plus 15 explicit normalization checks covering Unicode
scripts, accented Latin, acronyms with digit suffixes, and Clojure kebab-case
identifiers. The Phase 22 fixtures pin all five structural-finding families,
the seventh group member beyond the display sample, exact near-match
provenance, and the 51st group beyond the adapter detail cap.

## Labelling method

The primary reviewer read each pinned repository's source and primary
documentation, then wrote a small evaluation glossary and labelled emitted
terminology, drift, and structural findings as correct and useful or as false
alarms. A finding is
"useful" only when the reviewer judged that showing it to a maintainer would
help a vocabulary review; correctness alone is not enough.

Precision treats every emitted but unlabelled finding as a false alarm. Recall
is reported only where a complete expected set is practical: all detectors in
the controlled terminology and structural fixtures, and the finite
watched-term/canonical-fading checks in the real repositories. The evaluation
does **not** claim recall over every possible real-repository synonym,
overloaded meaning, or structural problem.

The glossaries are evaluation instruments, not vocabularies endorsed by the
upstream maintainers. The primary reviewer also authored the corpus labels and
the calibration. Phase 22 therefore adds a second, separate Codex session that
received only a blinded packet of the 20 emitted findings, their evidence, and
the usefulness question. It did not receive the source repository, manifest,
evaluation results, or primary labels. This is an independent second judgment,
but it is neither an outside maintainer nor a user study.

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

The current Phase 22 five-run replay emitted 20 scored findings, all labelled
correct and useful by the primary reviewer, with no labelled finding missed
where recall was complete:

| Metric | Result | Release threshold |
|---|---:|---:|
| Terminology precision | 100% | ≥80% |
| Drift precision | 100% | ≥90% |
| Drift recall where complete | 100% | ≥90% |
| Structural precision | 100% | ≥90% |
| Structural recall where complete | 100% | ≥90% |
| Primary-reviewer usefulness | 100% | ≥80% |
| Blinded second-reviewer usefulness | 17/20 (85%) | ≥80% |
| False alarms / 1,000 production code files | 0 | ≤50 |
| Corpus-budget truncations | 0 | 0 |
| Minimum warm-cache reuse | 100% | 100% |
| Phase 16 lexical contract | 15/15 (100%) | 100% |
| Phase 22 structural contract | 26/26 (100%) | 100% |

All deterministic release thresholds and the separate second-reviewer
threshold pass. This does **not** establish 100% real-world accuracy: 20
positive findings, two controlled structural fixtures, and three small
external repositories are far too little evidence for that claim. It
establishes that the pinned counterexamples and curated real-project checks
pass and that future changes have a reproducible gate.

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

## Phase 22 structural and reviewer result

The complete structural fixture emits the eight expected structural findings:
one unnamed boundary, four pairwise boundary mismatches, one overloaded region,
one orphaned concept, and one fragmented concept. Structural precision and
recall are both 100% where the fixture's labels are declared complete. Seventeen
additional contracts prove that full group tokens include the seventh member
even though `members_sample` does not, and that provenance uses exact accepted
paths rather than suffix or substring matches.

The truncation fixture supplies 51 groups. The adapter retains 50, reports one
drop with an exact total, marks the affected validation sections partial, and
does not emit an absence-based structural finding from incomplete evidence.
All nine truncation contracts pass. These are controlled adapter fixtures, not
evidence about structural accuracy on arbitrary Graphify-generated repositories.

The blinded second reviewer judged 17 of 20 findings useful and agreed with the
primary reviewer on 17. Its three disagreements are retained in
[`evaluation/reviewer-results.json`](evaluation/reviewer-results.json): it
rejected the p-limit `Pause Queue` fading alert as action-poor, considered
authentication and authorization a reasonable pair inside one Identity
Boundary, and found the tenant-fragmentation count insufficient without module
or context detail. The deterministic correctness labels were not changed to
manufacture agreement.

## Runtime and truncation

On the recorded 8-core Linux host with CPython 3.12.3, the sum of per-case
five-run medians was 0.520 seconds cold and 0.525 seconds warm—5.248 and 5.298
seconds per thousand included source files. Every warm run reused 100% of
eligible extraction entries and produced evidence byte-identical to its cold
run. The corpus is too small for the measured warm/cold difference to establish
a general cache speedup; content hashing, Git checks, cache I/O, and aggregation
still run on warm scans.

Requests hit existing output caps: 1,072 identifier entries, 981 documentation
terms, and 15 external-import entries were omitted from their displayed
sections and reported by truncation markers. The structural-truncation fixture
also hit the 50-group detail cap as intended. No repository hit the corpus
budget. Exact absence checks suppress conclusions when their required index is
truncated.

## Aggregate safety limits

The measured corpus took 5.248 cold seconds per thousand source files.
The scanner now applies immutable per-repository ceilings of:

- 10,000 included code/documentation files;
- 32,000,000 included source bytes;
- 100,000 processed directory entries; and
- 10,000 entries in any one directory.

Relative to the whole evaluation corpus, these retain about 101× file, 48×
byte, and 490× walk-entry headroom. At the observed file-normalized rate, the
file ceiling corresponds to roughly 52 seconds; repository composition and
hardware can change that substantially, so it is a safety bound rather than a
runtime guarantee.

When a source-file or byte ceiling is reached, Glossabet continues its bounded
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

The result identifies engine version 0.1.0, the evidence, drift, validation,
and evaluator schema versions, a SHA-256 digest over the evaluator and every
engine Python source file, the exact manifest digest, and a framed path/content
digest over every accepted corpus file. The manifest pins that digest and
accepted-file count for all seven cases; local fixtures and their structural
scores are additionally recomputed without network, while external cases
retain their immutable commit identity. The reusable release gate also
recomputes aggregate metrics and thresholds, and rejects stale inputs, missing
or reordered cases, fewer than five runs, weakened Graphify coverage, or
non-passing thresholds:

```bash
uv run python evaluation/run.py --verify-results evaluation/results.json
```

The second-reviewer lane can be regenerated only with an authenticated Codex
CLI. It creates an isolated temporary working directory, runs one ephemeral
read-only session, rejects commands outside the blinded packet, and writes the
packet and summarized judgments to the repository:

```bash
uv run python evaluation/review.py --run-reviewer
uv run python evaluation/review.py --verify-results evaluation/reviewer-results.json
```

The committed result records Codex CLI 0.147.0, one bounded packet-only
command, and the configured-default model because the CLI did not report a
model identifier.

## Installed-agent boundary result

During Phase 22, [`scripts/agent_eval.py`](scripts/agent_eval.py) temporarily
installed the repository's actual Codex plugin and exercised the canonical
skill through Codex CLI 0.147.0 on Linux. All 11 scenarios passed: current,
stale, and absent Graphify state; malformed, oversized, and symlinked
glossaries; partial agent projection; monorepo scope choice; resumed glossary
state; excluded sensitive files; and a standalone installed skill with no
`glossabet` command on `PATH`.

The bounded traces prove that Codex read the skill from the temporary plugin,
version-checked that plugin's exact engine, and used one attributable `inspect`
command per plugin scenario. The sensitive canary appeared in neither tool
output nor the final response, no command directly named an excluded path, and
no repository path changed except the documented `glossabet-out/evidence.json`
refresh permitted to `inspect`. The missing-CLI scenario stopped after the
failed version check and never invoked `inspect`. The temporary plugin,
marketplace, and exact empty cache parent were removed and re-queried after the
run.

This agent-mediated gate is not deterministic. Across the five full plugin
batches performed while building Phase 22, four satisfied the required single
version preflight. For the final wheel bytes specifically, the first of two
unchanged batches stopped before scenario scoring because Codex did not produce
exactly one successful version check; the unchanged repeat passed. The
Phase 22 JSON at that time recorded that successful exact-bundle run. It proved
one complete boundary execution, not a zero-flake rate for future model
invocations.

After the repository and documentation rename, Kyle separately authorized an
exact local artifact refresh without ending the owner self-testing pause. The
final rebuilt wheel differed from the Phase 22 wheel only in `METADATA` and
`RECORD`; every executable package entry was byte-identical. The final wheel
passed all 11 scenarios in its first full batch. The current committed JSON
records that run and binds it to plugin tree SHA-256
`b1a558baf1f6b4a32e9c9d5c0a9d87cda88f5b84607b02c1f4daad1a4cf132dd`.
An earlier metadata-only refresh also passed before the final README status
sync required the final rebuild. The first public-main CI run then proved that
the evaluator's tree identity had also included an ignored local
`__pycache__` file: local verification saw that file, while every clean CI
checkout correctly did not. The identity function now excludes only Python's
interpreter-generated cache directories, a focused regression test preserves
that behavior, and the same final wheel passed all 11 scenarios again against
the corrected identity. Temporary plugin and marketplace state was removed and
verified absent after every run. That makes the three post-Phase 22 batches
three for three and the combined observation seven of eight complete batches;
the sample remains too small to claim a stable future success rate.

The authenticated regeneration command temporarily changes user-level Codex
plugin/marketplace state and then removes only its uniquely named state. The
offline verifier makes no Codex or network call:

```bash
uv run python scripts/agent_eval.py --run
uv run python scripts/agent_eval.py --verify-results evaluation/agent-results.json
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
to 30 grammar packages to cover Glossabet's 30 current language labels.

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
- There is no independent maintainer or user study. The second reviewer is a
  separate blinded Codex session, not outside adopter evidence.
- Real-repository heuristic recall is not exhaustively labelled.
- Structural recall is labelled only in controlled hand-authored Graphify
  fixtures, not on varied third-party Graphify exports.
- Installed-agent evidence covers Codex CLI 0.147.0 on one Linux host. Other
  Codex versions and operating systems, ChatGPT, and Claude Code are unverified.
- The installed-agent preflight passed seven of eight observed full plugin
  batches. Phase 22 passed four of five, including one of two unchanged
  attempts against that exact wheel; all three post-Phase 22 batches passed,
  including the final wheel's corrected clean-tree evidence run. Reliability
  beyond that small observed sample is unknown.
- The multilingual fixture covers representative Python and Clojure forms,
  not every identifier grammar among the 30 recognized languages.
- Lexical extraction still sees identifier-like words in comments and string
  contents. It does not claim parser-level symbol identity.
- Scoped structural validation remains partial until an adapter supplies
  trustworthy repository paths for normalized groups.
