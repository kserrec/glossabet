# Evaluation

Glossabet's evaluation is a reproducible set of labelled repository cases,
structural fixtures, recorded agent-host boundary runs, and a blinded
usefulness review. It tests concrete contracts and known examples; it does not
establish that Glossabet improves arbitrary real projects or that agent
behavior is reliable in every future session.

For the maintainer-facing authority map—scenario inputs, response schemas,
provider code, generated baselines, immutable raw runs, archives, and files
that must not be edited manually—see
[`evaluation/README.md`](evaluation/README.md). This document remains the
authority for methodology, measured claims, and their limits.

The schema-6 manifest is [`evaluation/corpus.json`](evaluation/corpus.json). Recorded
results are immutable testimony about the exact inputs identified inside each
JSON file. During ordinary development they may lag the source tree but must
remain internally genuine. A release requires separate `--current` checks and,
when needed, newly authorized live evidence against the exact candidate.
Every deterministic source ID is unique and must be one safe path component;
absolute, parent, nested, and separator-bearing IDs are rejected before they
can name evaluator cache or checkout state.

## Deterministic corpus

[`evaluation/run.py`](evaluation/run.py) owns the deterministic lane. It runs
five cold and five warm measurements per repository, compares cold/warm output,
scores labelled expectations, records every coverage limitation, and binds the
engine, manifest, and inputs by SHA-256.

The seven cases are:

| Case | Purpose |
| --- | --- |
| `calibration-fixture` | Controlled synonym, overload, canonical-fading, watched-term, and parallel-term labels |
| `language-semantics-fixture` | Unicode, acronym/digit, Python/Clojure forms, scoped homonyms, and language-origin behavior |
| `requests` | Pinned Apache-2.0 Python repository |
| `hey` | Pinned Apache-2.0 Go repository |
| `p-limit` | Pinned MIT JavaScript/TypeScript repository |
| `structural-complete-fixture` | Hand-labelled usable Graphify groups and structural findings |
| `structural-truncation-fixture` | Explicit Graphify caps, lower bounds, and partial structural coverage |

The three external revisions are referenced by URL and exact commit; they are
not vendored. `--fetch` retrieves only those public revisions into temporary
space. Without `--fetch`, the runner uses already available checkouts or the
local fixtures and makes no network request. Target code is scanned as hostile
text and is never imported or executed.

The manifest also labels Glossabet's own naming register and distinctive-term
nominations. These self-cases are useful regression evidence, not independent
third-party validation.

### Metrics and release thresholds

The configured thresholds are intentionally explicit:

| Measure | Release threshold |
| --- | ---: |
| Terminology precision | at least 0.80 |
| Drift precision / recall where coverage is complete | at least 0.90 each |
| Structural precision / recall where coverage is complete | at least 0.90 each |
| Reviewer-labelled usefulness | at least 0.80 |
| False alarms per 1,000 production code files | at most 50 |
| Cold seconds per 1,000 source files on the recorded environment | at most 10 |
| Corpus-budget truncations | 0 |
| Minimum warm-cache reuse | 1.0 |
| Lexical contract, register accuracy, nomination quality, structural contract | 1.0 each |
| Warm outputs equal cold outputs | true |

Recall is scored only where the relevant evidence is complete. A capped lower
bound is never rewarded as if it were a complete negative result. Timing is a
recorded release signal for this fixed corpus and environment, not a universal
performance guarantee. Larger generated measurements are documented separately
in [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).

### Recorded result

[`evaluation/results.json`](evaluation/results.json) is schema 8 and records
Glossabet 0.1.0 on CPython 3.12.3, Linux 6.17, with evidence schema 17, drift
schema 7, and validation schema 12.

| Observation | Recorded value |
| --- | ---: |
| Cases / source files / production code files | 7 / 99 / 52 |
| Source bytes / walked entries | 661,164 / 204 |
| Terminology, drift, and structural precision | 1.0 each |
| Drift and structural recall where complete | 1.0 each |
| Lexical and structural contract rates | 1.0 each |
| Register accuracy | 1.0 |
| False alarms | 0 |
| Minimum cache reuse; warm output parity | 1.0; true |
| Cold / warm timing | Recorded in `evaluation/results.json`; the normalized cold ceiling is 10 seconds per 1,000 source files |
| Cases with any deliberate truncation | 2 |
| Corpus-budget truncations | 0 |
| Distinctive nomination quality | 0.75 |

`evaluation/results.json` is authoritative for the exact configured-check
outcomes of the retained run. The distinctive-term nomination score of 0.75
persistently misses its deliberately exact 1.0 threshold. Cold throughput is
compared with a 10.0-second ceiling and has crossed both sides of that ceiling
across unchanged regenerations on the recorded host, so an unrecorded rerun is
not substituted for the retained measurement. The producer-owned result file,
not this prose summary, is the authority for the exact retained timing.
Therefore this artifact does not claim that all deterministic release
thresholds pass. It is still valid evidence: the default verifier checks that
the failure and all underlying results are represented honestly.

Run the local/genuine verifier with:

```bash
uv run python evaluation/run.py --verify-results evaluation/results.json
```

At a release candidate, regenerate the deterministic result from that exact
source state and require:

```bash
uv run python evaluation/run.py --verify-results evaluation/results.json --current
```

`--current` recomputes local fixture identities, structural/register scores,
thresholds, case order, engine and manifest digests, and the current-source
comparison. It is not an ordinary per-edit gate.

## Blinded usefulness review

[`evaluation/review.py`](evaluation/review.py) is the thin command entry point
for [`evaluation/reviewer/`](evaluation/reviewer/). `packet.py` builds a packet
that withholds the primary useful/not-useful labels; `host.py` records one
separate ephemeral Codex review in an isolated temporary directory; and
`results.py` owns comparison and offline verification. The reviewer receives
only the prompt, response schema, and bounded packet; its sandbox is read-only
and the harness rejects unrelated tool behavior. Offline verification never
imports the live host.

[`evaluation/reviewer-results.json`](evaluation/reviewer-results.json) records
20 judgments: 17 useful, a 0.85 secondary-usefulness rate, and 0.85 agreement
with the primary labels. The configured usefulness threshold is 0.80. The
record identifies Codex CLI 0.147.0; the CLI did not report its configured
model identifier. This is a second model judgment, not an outside maintainer or
user study.

[`evaluation/reviewer-reviewed-packets/`](evaluation/reviewer-reviewed-packets/)
retains the exact blinded packet bytes read by accepted reviewer runs, named by
their SHA-256 digest. The verifier permits judgment reuse after evaluator-
metadata changes only when the current packet's question, sources, and blinded
findings still exactly match the referenced retained packet. New runs add an
immutable packet before atomically committing their result, so a failed run
cannot overwrite the packet needed to verify a previously accepted result.

Default verification checks blinding, packet/result integrity, comparison
arithmetic, and the recorded usefulness threshold. `--current` additionally
requires packet and input identities to match the current deterministic
result:

```bash
uv run python evaluation/review.py --verify-results evaluation/reviewer-results.json
```

Generating a new reviewer result invokes an authenticated model host and needs
separate authorization; verification does not.

## Installed Codex boundary

[`scripts/agent_eval.py`](scripts/agent_eval.py) checks the user-facing boundary
with the repository's actual temporary plugin and canonical skill. The current
scenario manifest contains fourteen cases:

- fresh, stale, and absent Graphify state;
- malformed, oversized, and symlinked glossaries;
- partial projection, monorepo selection, resumed glossary state, and excluded
  sensitive content;
- maintainer `GLOSSARY.md` only and structured-plus-maintainer glossary states;
- fresh-session hook delivery; and
- the standalone installed skill with no `glossabet` executable available.

[`evaluation/agent-results.json`](evaluation/agent-results.json) records 14/14
passes on Codex CLI 0.147.0 and Linux 6.17. Its three host turns observed the
fresh-session hook, plugin skill flow, and missing-CLI stop. The run's exact
input identities and immutable raw bytes are retained by
[`evaluation/agent-history.json`](evaluation/agent-history.json); earlier
passes and misses remain there instead of being selected away. Safety gates
cover canary disclosure, unexpected repository writes, forbidden inspection
after a failed boundary, and cleanup of the evaluator-owned temporary plugin
state. Before/after snapshots include ordinary directory and non-regular entry
metadata so empty-directory or FIFO/socket/device mutations are visible without
opening special files. Dotenv entry names are matched case-insensitively and
represented only by their path key and bounded `lstat` metadata—type, mode,
size, modification time, device, and inode—and are never opened or descended.
A valid `inspect` write may change
`glossabet-out/evidence.json` and its parent directory metadata; the parent is
accepted only when that exact pair changed and its type, mode, device, and inode
identity stayed stable, or when a new parent contains only the allowed file.
Separate plugin/source tree identities first exclude case-insensitive dotenv
and bytecode-cache names without reading them, ignore real directory structure,
reject every included symlink or non-regular entry before a content read, and
hash included regular-file paths and bytes only so the digest remains
host-independent.

The result is evidence for one host version and operating system, not a support
claim for other Codex versions, Windows/macOS plugin lifecycle, ChatGPT, or a
future stochastic command-success rate. Two post-approval behaviors—derived
report refresh and baseline-before-reading a maintainer glossary—still lack
recorded live scenarios and remain in [`PLAN.md`](PLAN.md).

Offline/genuine verification is:

```bash
uv run python scripts/agent_eval.py --verify-results evaluation/agent-results.json
```

An authenticated `--run` uses model-account tokens, temporarily changes
user-level Codex plugin/marketplace state, and requires explicit authorization.
The evaluator uses unique raw paths and appends all outcomes. The release-only
`--current` check also binds the checked-in plugin, wheel, runner, hook, skill,
prompts, schemas, and evaluator to the exact candidate.

## Claude Code boundary

The Claude skills-directory plugin is covered offline for safe installation,
exact manifest/hook bytes, hook execution, and `claude plugin validate`. A
manual owner session on Claude Code 2.1.235/Linux provided partial evidence
that SessionStart vocabulary and `/glossabet` were available, but it allowed
project reads/tools and did not capture the controlled negative case or a
digest-bound transcript.

Claude fixture mutation snapshots use the same directory, non-regular, and
dotenv-metadata-only contract described for the Codex lane; special entries
and dotenv contents are never opened. After its named exclusions, Claude plugin
identity likewise rejects included symlinks and non-regular entries before
hashing regular-file paths and bytes.

[`evaluation/claude-results.json`](evaluation/claude-results.json) records the
one controlled three-call attempt honestly as 0/3. All processes stopped before
SessionStart or model use because the former response schema declared JSON
Schema Draft 2020-12 while the host validator accepted Draft 7. Usage was zero
input/output tokens, no cost was reported, and cleanup passed. The schema is
corrected and tested offline, but no retry was made. A fresh three-call run has
the explicit account/cost authorization prerequisite recorded in
[`PLAN.md`](PLAN.md).

This means Claude Code ambient behavior is promising but not accepted as a
controlled installed-host result. Other Claude versions and operating systems
are unverified.

## Result interpretation

The three verifier families intentionally separate two questions:

- **Genuine:** is the stored record well-formed, internally consistent,
  digest-bound to its retained inputs/raw data, and honest about failures?
- **Current:** does that genuine record describe the exact source, manifests,
  prompts, schemas, plugin, and release artifact being shipped, and do all
  release thresholds pass?

Ordinary development runs genuine verification. Refactors may make an honest
artifact stale without rewriting history. Release preparation regenerates the
needed deterministic or separately authorized live evidence, then runs
`--current`. A procedural model miss is evidence and remains visible; it is not
an engine defect unless the trace establishes that causal chain.

## Limitations

- The deterministic corpus is small and biased toward compact open-source
  libraries plus purpose-built fixtures.
- Real-repository heuristic recall is not exhaustively labelled.
- Structural recall is labelled on controlled Graphify fixtures, not varied
  third-party exports.
- The multilingual fixture covers representative Python and Clojure forms,
  not all identifier grammars among recognized file types.
- Python has a curated builtin-origin table; unknown language/library tokens
  conservatively remain possible domain vocabulary.
- Lexical extraction can see identifier-like text in comments and strings and
  does not claim parser-level symbol identity.
- Structural validation for path-scoped concepts is partial until an adapter
  supplies trustworthy repository paths for normalized groups.
- Agent/reviewer lanes are model-host evidence from small samples, not human
  adopter evidence or a future reliability rate.
- The trusted-alpha user study and exact-artifact release candidate have not
  happened.

No parser dependency was added because the labelled lexical cases left no
measured accuracy failure for a parser to fix. Reconsidering that choice
requires a labelled counterexample and a measured gain large enough to justify
native code, grammar/version maintenance, supply-chain cost, and any new cache
or network behavior.
