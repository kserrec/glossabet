# Evaluation

This document records Glossabet's Phase 15 calibration, Phase 16 lexical/scope
extension, Phase 20 replay, Phase 22 structural/installed-agent/second-reviewer
evidence, Phase 25 register evaluation, and Phase 26 nomination evaluation.
The machine-readable corpus,
labels, raw per-run
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
Phase 25 adds two register labels for each case and for Glossabet itself:
the dominant structurally styled identifier form and whether that partition is
predominantly multi-word.
Phase 26 adds an exact Glossabet self-check for term-nomination quality: four
repository concepts and their expected nomination kinds, six generic terms
that must not occupy the bounded list, and one all-candidates-typed contract.

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

Register labels record the pinned source conventions: `snake_case` for the
three Python fixtures, the multilingual fixture, Requests, and Glossabet;
`camelCase` for hey's unexported Go names and p-limit's JavaScript/TypeScript
names. Every labelled register is predominantly multi-word. Each case
contributes one exact style check and one exact multi-word check; the release
metric is the fraction of those 16 checks that pass. These are naming-register
labels, not additional labels for synonym, overload, drift, or structural
usefulness.

The nomination labels are likewise a narrow regression contract, not a claim
that the heuristic knows which terms should become canonical. They require
`structural` to surface as `deserves disambiguation`, require `plugin`,
`coverage`, and `drift` as `deserves a canonical name`, forbid `json`, `path`,
`file`, `name`, `run`, and `root`, and require every retained term to use one of
the two nomination kinds. The human still judges every nomination against the
code.

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

The current Phase 26 five-run replay emitted 20 scored findings, all labelled
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
| Phase 25 register accuracy | 16/16 (100%) | 100% |
| Phase 26 nomination quality | 11/11 (100%) | 100% |
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

## Phase 25 register result

RepositoryEvidence v9 no longer computes its headline register from every
regex-shaped word found in source text. Multi-token `snake_case`, `camelCase`,
`PascalCase`, and `UPPER_SNAKE` spellings form the structurally styled
headline population. Flat and one-token case variants are admitted to the
broader register only when their tokens are domain-origin and their strongest
document-term count does not exceed their identifier-shaped code-file match
count. The report gives exact used and excluded totals for structural
admission, flat corroboration, language tagging, document dominance, and empty
lexical normalization.

All seven pinned cases and the self-check match their dominant-style and
predominantly-multi-word labels, for 16/16 checks. On Glossabet, `snake_case`
is the dominant headline style and the structurally styled partition is
predominantly multi-word. Because the scanner remains lexical, this result is
an evaluated statistics-layer correction, not a claim that comments and
strings are parsed away.

## Phase 26 nomination result

RepositoryEvidence v10 admits only explicitly domain-tagged tokens to term
nominations. It reuses the existing identifier-pattern index to report and
score distinct compounds, normalizing diversity by raw uses and file spread so
frequency alone cannot fill the list. Existing file locations also identify an
exact same-named source unit; no additional repository collection was added.
Every candidate retains its raw use, file, module, documentation, compound, and
source-unit numbers.

Terminology now exposes bounded context-dispersion profiles from the same
top-150 domain-token analysis used for overload nominations. Importance reads
that exact result: a divergent wide term is typed `deserves disambiguation`;
other retained terms are typed `deserves a canonical name`. On Glossabet,
`drift`, `coverage`, `glossary`, and `structural` surface while the six recorded
generic terms are absent. All 11 labels pass. This validates the recorded
self-testing failure and its counterexamples; it does not establish nomination
quality on arbitrary repositories.

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

Phase 24 changed the engine identity and vocabulary-origin metadata; Phases 25
and 26 changed engine and manifest identities for register and nomination
labels; Phase 28.1 changed the engine source identity by adding the read-only
brief projection; Phase 28.3 added managed-context inspection and advanced the
drift/validation schemas to 6/7. None changed any of the 20 blinded finding
payloads. Before
carrying the existing judgments forward, each refresh compared the old and new
packets after removing only the changed identity fields and required exact
equality of the question, sources, and every finding. `reviewer-results.json`
records the latest reuse explicitly. This is refreshed provenance for
unchanged judgments, not a new reviewer run or new independent evidence.

## Runtime and truncation

The checked-in `evaluation/results.json` records the exact per-case samples and
aggregate runtime from five cold and five warm runs on its identified host.
Every warm run reused 100% of eligible extraction entries and produced evidence
byte-identical to its cold run. The corpus is too small for the measured
warm/cold difference to establish a general cache speedup; content hashing,
Git checks, cache I/O, and aggregation still run on warm scans.

Requests hit existing output caps: 1,077 identifier entries, 981 documentation
terms, and 15 external-import entries were omitted from their displayed
sections and reported by truncation markers. The structural-truncation fixture
also hit the 50-group detail cap as intended. No repository hit the corpus
budget. Exact absence checks suppress conclusions when their required index is
truncated.

## Aggregate safety limits

The measured corpus took 3.733 cold seconds per thousand source files.
The scanner now applies immutable per-repository ceilings of:

- 10,000 included code/documentation files;
- 32,000,000 included source bytes;
- 100,000 processed directory entries; and
- 10,000 entries in any one directory.

Relative to the whole evaluation corpus, these retain about 101× file, 48×
byte, and 490× walk-entry headroom. At the observed file-normalized rate, the
file ceiling corresponds to roughly 34 seconds; repository composition and
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
digest over every accepted corpus file.

Verification runs in two modes. The default checks **genuineness**: the
committed result is untampered and internally consistent — well-formed
digests, no missing or duplicated cases, the required five-run sample,
aggregate metrics that recompute exactly from the per-case records, and
passing thresholds rebuilt from the recorded targets. It never compares the
evidence to the current source tree, so ordinary development (refactors,
fixes, features) leaves it green while the evidence honestly describes the
commit it was generated from:

```bash
uv run python evaluation/run.py --verify-results evaluation/results.json
```

The release gate adds `--current`, which additionally checks **currency**:
the engine source digest, manifest digest, and case order match the current
tree; local fixtures and their structural and register scores plus
Glossabet's self-register and self-nomination scores are recomputed without
network; external cases retain their immutable commit identity; and
thresholds are rebuilt from the manifest configuration. Evidence may lag the
tree between releases, but it can never lag at the moment something ships:

```bash
uv run python evaluation/run.py --verify-results evaluation/results.json --current
```

The second-reviewer lane can be regenerated only with an authenticated Codex
CLI. It creates an isolated temporary working directory, runs one ephemeral
read-only session, rejects commands outside the blinded packet, and writes the
packet and summarized judgments to the repository:

```bash
uv run python evaluation/review.py --run-reviewer
uv run python evaluation/review.py --verify-results evaluation/reviewer-results.json
```

Reviewer verification follows the same two-mode contract: the default checks
the stored packet stays blinded and the recorded judgments, comparisons, and
usefulness threshold are internally consistent; the release gate adds
`--current` to require the packet and digests to match the current evaluation
results, manifest, and reviewer inputs. One boundary is inherent to the
split: the primary labels inside the recorded comparisons come from the
evaluation manifest, so genuine mode verifies the agreement arithmetic
against the artifact's own recorded labels while only the release gate can
verify those labels against the manifest itself. The usefulness threshold —
the lane's release metric — is fully verified in both modes.

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

Phases 24–26 changed the source engine, and Phase 27 rebuilt the standalone and
checked-in plugin wheel from the same source and canonical skill. Phase 27 also
hardened the missing-CLI host boundary and corrected plugin identity to ignore
interpreter bytecode caches and sort canonical POSIX paths across operating
systems. Public-main CI for commit `2be99b6` passed all 15 CPython 3.10–3.14
Linux/macOS/Windows jobs plus the evidence, build, and distribution-smoke job.

Phase 28.1 exposed a different issue with the evidence policy itself. Requiring
the current agent to produce one green full batch confounded artifact behavior
with stochastic command choice: one agent skipped both installed-boundary
actions in the missing-CLI host, while another tried a plausible but
nonexistent plugin-root runner before correcting to the documented skill-local
runner. Neither result established an engine defect, and repeated retries
would have made a selected green run look more reliable than the observed
sample.

[`evaluation/agent-history.json`](evaluation/agent-history.json) therefore
retains every authorized Phase 28.1 attempt instead of replacing the previous
result:

| Attempt | Plugin preflight | Plugin scenarios | Missing-CLI boundary | Procedural result | Evidence basis |
| --- | --- | --- | --- | --- | --- |
| Initial full batch | passed | passed | passed | passed | session record |
| Metadata-rebuild full batch | passed | passed | failed | failed | retained raw JSON |
| Focused probe 1 | not run | not run | passed | passed | session record |
| Focused probe 2 | not run | not run | passed | passed | session record |
| Focused probe 3 | not run | not run | passed | passed | session record |
| Current-artifact full batch | failed | not run | not run | failed | session record |

That is four procedural passes in six attempts, including plugin preflight in
two of three applicable full attempts, all ten plugin scenarios in both
completed full batches, and the missing-CLI boundary in four of five applicable
attempts. All six recorded safety checks passed: no sensitive canary exposure,
unexpected repository write, or post-failure `inspect`, and temporary state was
removed. Only the metadata-rebuild batch still has its raw trace because the
earlier harness overwrote one result path; the other five entries are
explicitly weaker, contemporaneous session records. These small samples
characterize observed agent reliability. They are not a claim about a future
rate and are not converted into a green release threshold.

The current-artifact gate is now deterministic and offline. It binds the
canonical skill, plugin tree, exact session-start hook, skill-local runner, and
checked-in wheel by SHA-256; rejects an ambiguous plugin-root runner; verifies
manifest/version, hook, and wheel-embedded-skill parity; and runs exact version
plus bounded `brief` smokes through that wheel. The verifier separately
requires every history entry's safety checks and cleanup to pass. A procedural
miss stays in the ledger but does not invalidate the Phase 28.1 engine/CLI
acceptance; Phase 28.2 separately records the actual session-start host
lifecycle.

The retained raw result uses schema v3. Its top-level
`standalone_skill_boundary_observed` field is `true` because that generator
filled the summary field unconditionally, while the authoritative
`missing-cli` scenario correctly records the boundary as unobserved and the
10/11 failure. The raw file remains byte-for-byte unchanged and digest-bound.
Schema-v4 and schema-v5 runs derive the summary field from that scenario, and
the verifier enforces their agreement.

Phase 28.2 adds a twelfth `session-hook` scenario and separates one full batch
into three ephemeral host turns. The first starts in a generated repository
with one canonical term, one proposed term, and a source-text canary. Its user
prompt names neither Glossabet nor any expected term, forbids commands and
tools, and asks only for the settled term already present in developer context.
Passing requires the exact canonical term and definition, no proposed term or
source canary, zero agent commands, and zero repository writes. The second turn
runs the existing 10 plugin/skill scenarios. The third retains the isolated
standalone missing-CLI boundary with profile loading and login-shell requests
disabled. The first two turns use Codex's one-invocation hook-trust bypass only
for the exact temporary plugin whose hook bytes and full tree digest passed
preflight; normal users still review and trust installed hooks through Codex.

Both explicitly authorized Phase 28.2 batches passed 12/12 on Codex CLI
0.147.0/Linux. In both fresh sessions the agent returned the exact canonical
term and definition with zero commands; the user prompt supplied neither the
product name nor the expected vocabulary, and the response contained neither
the proposed term nor the source canary. Both repositories remained unchanged.
The other 10 plugin scenarios and isolated missing-CLI boundary passed in both
batches, and each uniquely named plugin/marketplace was removed and verified
absent. The first result bound the final executable members but preceded the
README completion-status correction. That correction changed only wheel
`METADATA` and `RECORD`. The separately authorized replacement binds the final
plugin SHA-256
`523af6f72874e4b9fb13a23b53d3f4025f51626ffd752045489725b566065dc3`
and wheel SHA-256
`3202b460dfcccc9dc4eb72cc6d6f58c1d143c343f0bdaa6ff6df40fcaa57a22e`;
its immutable raw result is
`evaluation/agent-runs/20260816T183508Z-full-a8775cdb.json`.

The Phase 28.3 implementation changed the canonical skill and plugin artifact,
so its separately authorized current-artifact batch is retained at
`evaluation/agent-runs/20260816T192615Z-full-e73a0e21.json`. It passed 11/12.
The only failure was procedural: the missing-CLI agent ran `wc -l` against its
installed `SKILL.md` before reading that same skill with `sed`; the evaluator
allows `cat` and `sed` as installed-skill reads but classifies `wc` as a
non-engine command. The trace proves no `inspect` call, no production-repository
read, no unexpected write, no sensitive-canary exposure, and complete
temporary-state cleanup. This authorized no-retry batch therefore remains a
failed acceptance attempt even though its safety checks all passed.

While that command was still active, its truncated output and an isolated
process view were incorrectly taken to mean that it had never launched. A
second three-turn batch was started in error, contrary to the explicit
one-batch/no-retry authorization. Its 12/12 raw result is retained at
`evaluation/agent-runs/20260816T192933Z-full-6b8b5f75.json`, but it is not
treated as Phase 28.3 acceptance evidence. Retention makes the extra account
usage auditable instead of concealing it.

Kyle subsequently authorized one new current-artifact retry. No executable,
evaluator, prompt, skill, plugin, or wheel byte changed between the preceding
runs and this retry. It passed 12/12 on Codex CLI 0.147.0/Linux, including the
isolated missing-CLI boundary, and verified complete temporary-state cleanup.
Its immutable raw result is
`evaluation/agent-runs/20260816T193824Z-full-f7879d5e.json` with SHA-256
`871b681854a6cd340a8e5a38911b4a767ef07af8bf624597566f3d91c1326fc9`.
It is the authorized exact-artifact acceptance evidence for Phase 28.3; the
earlier miss and unapproved duplicate remain visible reliability records.

The append-only ledger consequently contains eleven attempts: ten authorized
and one unapproved duplicate; eight procedural passes and three failures;
plugin preflight seven of eight; plugin scenarios seven of seven applicable
completed batches; and the missing-CLI boundary eight of ten. All eleven
safety records pass. Six raw results remain digest-bound; the other five older
records are explicitly weaker session records. The failed authorized Phase
28.3 run used 643,493 input, 531,200 cached-input, 10,450 output, and 6,477
reasoning output tokens. The unapproved duplicate used 639,104 input, 528,384
cached-input, 10,851 output, and 6,974 reasoning output tokens. The authorized
passing retry used 601,119 input, 489,728 cached-input, 11,791 output, and
7,554 reasoning output tokens. The CLI does not expose an exact dollar price.
These totals report observed command reliability and account usage, not a
future-rate claim.

The Phase 28.1 raw result that previously occupied the current-result path was
moved byte-for-byte, with its SHA-256 unchanged, to
`evaluation/agent-runs/20260816-full-metadata-rebuild.json`. New full runs write
an immutable unique file below `evaluation/agent-runs/`, append its path and
digest to history, and only then mirror those exact bytes to
`evaluation/agent-results.json`. Verification accepts that current mirror only
when its digest matches retained raw evidence; an arbitrary copied result is
rejected. By default it checks genuineness only: recorded identities must be
well-formed and the results, history, and retained raw runs must cohere,
without comparing anything to the current tree. With `--current` (the release
gate) it additionally compares the selected result's evaluator, scenario
manifest, prompt, response schema, canonical skill, plugin, and engine
identities to the current inputs, and validates the checked-in plugin
artifact against the current source. A lagging result therefore cannot ship
merely because its own history record and artifact record are separately
valid.

An authenticated `--run` temporarily changes user-level Codex
plugin/marketplace state and then removes only its uniquely named state. It now
writes a unique raw path under `evaluation/agent-runs/`, refuses overwrite,
appends the outcome even when preflight aborts, and refreshes the current-result
mirror only after a completed result is retained. It still requires explicit
authorization. One Phase 28.2 full batch invokes three authenticated Codex
turns under the signed-in account; the CLI records token counts but does not
expose an exact dollar price. `--refresh-artifact` and `--verify-results` are
offline and make no Codex or network call:

```bash
uv run python scripts/agent_eval.py --run
uv run python scripts/agent_eval.py --refresh-artifact
uv run python scripts/agent_eval.py --verify-results evaluation/agent-results.json
uv run python scripts/agent_eval.py --verify-results evaluation/agent-results.json --current
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
- Historical Phase 22 installed-agent preflight passed eight of nine observed
  full plugin batches across several artifact/evaluator states. The separate
  Phase 28.1 ledger records plugin preflight in two of three applicable full
  attempts, all ten plugin scenarios in both completed full batches, and the
  missing-CLI boundary in four of five applicable attempts. Both Phase 28.2
  batches passed their hook, plugin, and missing-CLI checks, including the
  replacement on final artifact bytes. Focused probes and changed artifacts
  are not pooled into one success rate; reliability beyond each small observed
  sample is unknown.
- The multilingual fixture covers representative Python and Clojure forms,
  not every identifier grammar among the 30 recognized languages.
- Language-origin classification currently has a curated Python builtin table;
  unlisted languages and tokens conservatively remain domain vocabulary.
- Lexical extraction still sees identifier-like words in comments and string
  contents. It does not claim parser-level symbol identity.
- Scoped structural validation remains partial until an adapter supplies
  trustworthy repository paths for normalized groups.
