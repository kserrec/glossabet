# Glossabet — Current Roadmap

Last updated: 2026-08-27.

Glossabet 0.1.0 is an unreleased source alpha. The implementation and local
release machinery exist, but Kyle is still testing the product as its owner.
Outside testing, contribution intake, release-candidate work, and publication
remain paused until he explicitly advances those gates.

This file contains only current and future work. The complete construction
record is preserved under [`docs/history/`](docs/history/README.md).

## Product boundary

Glossabet gathers deterministic repository evidence, an agent proposes names,
and a human decides what becomes canonical. The skill is instructed not to
save canonical terms without explicit human approval; the `save` command can
validate the document but cannot prove that approval occurred.

Every future change must preserve these constraints:

- Repository content is hostile static data: never import or execute it.
- Production operation is local and makes no network requests.
- Reads and writes stay bounded, path-confined, symlink-aware, and explicit.
- Every cap or omission remains visible; incomplete evidence never reads as
  complete.
- Generated Glossabet context does not feed back into lexical evidence.
- Persisted schemas, deterministic ordering, and compatibility behavior change
  only through an explicit migration.
- Runtime dependencies remain zero unless a concrete correctness or security
  need justifies a reviewed exception.
- External account use, paid/live evaluation, publication, tags, releases, and
  repository-setting changes require separate explicit authorization.

## 0. Targeted hardening and cleanup (active)

**Outcome:** the reviewed 0.1.0 alpha keeps its existing architecture while
its declared platform support, analytical completeness contracts, boundary
behavior, finding bounds, compatibility policy, and inheritance surface become
internally consistent. The binding starting point is
`db5e76aca747892611b06114100c59b4d7a4e676`; newer deliberate decisions win
when later work has already resolved a finding.

This is an oversized plan. Its Phases correspond to the specification's
numbered passes; each Step is one complete single-pass change. Every production
Step begins with a failing scenario and a named invariant, changes tests with
production code, runs focused tests before the full suite, runs Ruff and mypy,
preserves deterministic ordering, updates every affected persisted schema in
the same commit, and ends in one focused commit. No Step may add a runtime
dependency, service layer, provider framework, generic measurement algebra, or
unrequested module split. The existing CLI-to-artifact flow, Graphify adapter
boundary, distribution duplication, bounded imperative builders, and trust
protections remain protected.

### Phase 0 — exact baseline

- [x] **Step 0.1 — record the before-state and executable plan**
  (2026-08-27). `HEAD` and `origin/main` both equal the reviewed commit and the
  worktree began clean. The declared matrix is CPython 3.10–3.14 on Ubuntu,
  macOS, and Windows; package metadata also says `OS Independent`. The public
  commands are `scan`, `analyze`, `inspect`, `brief`, `sync-context`, `show`,
  `save`, `drift`, `validate`, `cache-clear`, and `install`.

  Product formats are evidence 15, agent context 3, glossary 1, drift 6,
  validation 8, config 1, managed context 1, managed block 1, brief 1, and
  cache 5. Evaluation formats are deterministic results 7, Codex results 5
  and history 1, Claude results 1 and history 1, reviewer packet 1, and
  reviewer results 2. Persisted analytical compatibility vocabulary currently
  includes `count_complete`, `files_complete`, `locations_truncated`,
  `total_findings_complete`, and validation's convenience `graph_available`
  beside its richer `graph` state. Tolerant readers also retain older or
  hand-built evidence ledgers, Graphify's legacy top-level `edges` fallback,
  and the pre-rename `glossarize-out` exclusion.

  On local CPython 3.12/Linux: `uv sync --locked` passed; 798 tests passed;
  Ruff, mypy (55 product files), workflow policy, deterministic/Codex/reviewer
  evidence verification, isolated wheel build, distribution parity, and wheel
  smoke all passed. `actionlint` is not installed locally, but the matching CI
  static job passed actionlint 1.7.12.

  The current GitHub run for this exact commit failed seven of fifteen matrix
  lanes: every Windows lane failed the same seven base tests (Claude scratch
  cleanup on read-only Git objects masks both a synthetic failure and
  `KeyboardInterrupt`; four evaluation-CLI cases require POSIX missing-file
  wording/path spelling; one race test requires POSIX symlink state), and all
  three Python 3.14 lanes additionally failed the allocator-sensitive
  `tracemalloc` threshold. These are two evaluation-infrastructure defects plus
  platform/interpreter-sensitive tests. No product defect or
  unsupported-environment mismatch was observed. Static checks passed; the
  distribution job was skipped because it needs the failed matrix, while the
  same distribution checks passed locally.

### Phase 1 — trustworthy CI and release gate

- [x] **Step 1.1 — portable owned-scratch cleanup and failure precedence**
  (2026-08-27). Reproduced the bare `shutil.rmtree` failure on read-only Git
  object layouts and the lifecycle paths that replaced a scenario failure or
  `KeyboardInterrupt`. The invariant is now: cleanup may remove only the exact
  evaluator-created child beneath the unchanged configured parent, and a
  secondary cleanup failure may never replace the first evaluation failure.

  Claude scratch ownership binds the resolved parent and root identities to a
  random on-disk marker, rejects replaced roots and parent changes, refuses to
  permission-correct symlinks or junctions, and retries only the failed
  unlink/rmdir after clearing a Windows read-only bit. Cleanup reports an
  explicit boolean result. Claude and Codex runners preserve the exact original
  exception object—including `KeyboardInterrupt`—while recording and reporting
  a stable secondary cleanup diagnostic; cleanup remains primary when no
  evaluation error came first. Attempt schemas did not change shape.

  Focused lifecycle and confinement tests passed. The complete local suite is
  805 passed and one Windows-only junction test skipped on Linux; Ruff, product
  mypy, workflow policy, and all three offline evidence verifiers passed.
  `actionlint` remains unavailable locally and no workflow changed. Actual
  Windows and full declared-matrix execution remains for Step 1.4.
- [ ] **Step 1.2 — platform-semantic CLI and race contracts.** Replace raw
  operating-system prose and absolute-path expectations with Glossabet-owned
  prefixes, exit/channel behavior, canary preservation, non-traversal, and safe
  outcomes. Keep exact POSIX symlink-state assertions only in POSIX tests; do
  not weaken the underlying race protections.
- [ ] **Step 1.3 — deterministic bounded-read verification.** Replace the
  interpreter-allocation threshold with an instrumented stream/open seam that
  proves bounded requests, no cap-sized allocation request, minimum evidence
  read before oversize rejection, and exact-boundary behavior.
- [ ] **Step 1.4 — close the support and distribution gates.** Run every
  declared lane, Ruff, mypy, actionlint, workflow policy, recorded-evidence
  verification, build/plugin/distribution/wheel smoke, and confirm that the
  package job actually executes. Change support metadata only if a remaining
  limitation is deliberate and documented, never to hide a portable defect.

### Phase 2 — canonical scope and boundary behavior

- [ ] **Step 2.1 — one NFC scope identity.** Add one scope-domain NFC
  canonicalizer and make validation, duplicate/overlap/ownership checks,
  lookup, comparison, save, and load consume it. Prove composed/decomposed
  identity and ancestry, canonically distinct paths, deterministic persistence,
  and rejection of equivalent competing owners; bump the glossary schema if
  the persisted semantic change requires it.
- [ ] **Step 2.2 — deliberate command/filesystem boundaries.** Give parsed
  JSON `null` a schema diagnostic distinct from input failure; treat an
  uncertain exact-name lookup as uninspectable for writes; and recognize a
  genuine `glossabet-out` subtree without rejecting an unrelated repository
  beneath a similarly named ancestor. Prove each positive, negative, and
  uncertainty case without creating a general directory classifier.

### Phase 3 — exactness, completeness, sampling, and skipped checks

- [ ] **Step 3.1 — occurrence exactness contract.** Migrate numeric occurrence
  facts from ambiguous “complete” names to `count_exact`, `files_exact`, and
  `modules_exact`; retain collection `complete` and display
  `locations_truncated`; persist exact global identifier module counts; and
  distinguish upstream clipping from final display sampling for scoped,
  single-token, and compound occurrences. Update affected schema versions,
  fixtures, serializers, consumers, and documentation together with no parallel
  legacy fields unless the compatibility policy explicitly requires them.
- [ ] **Step 3.2 — epistemically sound analytical decisions.** Apply identical
  fragmentation rules to simple and compound terms: emit a lower-bound count
  already above threshold, suppress an inexact below-threshold negative, and
  record the incomplete reason. Add one “unproven zero” helper and use it for
  parallel/watched/fading/binding and related checks when tables, locations,
  work, term limits, or production corpus coverage make absence unknowable.
- [ ] **Step 3.3 — projection semantics.** Separate selected projection,
  `projection_complete`, `source_complete`, intentional protocol exclusions,
  limit-driven truncations, and the applied limits. Prove that a designed lean
  exclusion does not read as projection failure and that serialization remains
  bounded and deterministic.
- [ ] **Step 3.4 — validation execution and graph state.** Separate all-checks
  execution/skips from the exact total produced by evaluated checks; rationalize
  externally visible graph state around `present`, `usable`, `freshness`, and
  `warnings`; apply the compatibility policy to `graph_available`; and migrate
  validation schema, evaluation scoring, fixtures, docs, and distribution
  copies in one coherent change.

### Phase 4 — bounded findings and clear ownership

- [ ] **Step 4.1 — bound large finding details.** Store exact structural
  `concept_count` with a bounded sample and explicit sample truncation, then
  audit only other per-finding collections proportional to accepted glossary
  size. Prove exact totals, payload bounds, intended serialized size, and
  deterministic order.
- [ ] **Step 4.2 — expose conceptual module owners.** Move clear internal scope
  imports from persistence re-export façades to `glossary.scope`, preserve only
  policy-backed public compatibility re-exports, audit a few similarly clear
  cases, and prove no dependency cycle. Do not perform a repository-wide import
  rewrite.
- [ ] **Step 4.3 — conditional cohesion improvements.** Reassess
  `agent_context.py` after its schema change and split protocol model from
  projection code into exactly two modules only if local reasoning materially
  improves and output stays byte-identical. Likewise add mypy coverage only for
  the critical evaluator cleanup/lifecycle modules if that gives a narrow,
  maintainable gate. Record a no-change decision when either move is churn.

### Phase 5 — comments, compatibility, and repository coherence

- [ ] **Step 5.1 — repository and evaluation authority map.** Make the existing
  top-level architecture surface identify canonical product/test/evaluation/
  script/skill/plugin/history/generated ownership; make `evaluation/README.md`
  distinguish scenarios, schemas, accepted baselines, raw runs, provider code,
  archives, and files not edited manually; archive rather than delete useful
  evidence; and keep irrelevant history out of source distributions.
- [ ] **Step 5.2 — explicit compatibility policy.** Document accepted persisted
  versions, Python import-path status, field deprecation horizons, legacy output
  exclusions, and removal criteria. Apply it narrowly to graph/evidence
  fallbacks, re-exports, tolerant hand-built artifacts, and pre-rename output
  names; keep every retained path tied to a purpose or lifetime.
- [ ] **Step 5.3 — current-invariant comments and authoritative history.** Audit
  the named large modules for test-directed, development-history,
  conversational, rhetorical, and narrating comments; retain or add only
  security, ordering, bound, exactness, projection, failure-precedence, and
  compatibility invariants. Classify plans/history, leave one apparent current
  roadmap, preserve reproducibility evidence, and verify packaging/distribution
  parity after movement.

### Phase 6 — cold review and stopping decision

- [ ] **Step 6.1 — complete regression and deterministic-artifact surface.** Run
  the full local gates, all declared CI lanes, distribution/plugin builds and
  smoke tests, representative public workflows, repeated cold/warm fixture and
  repository runs, and semantic before/after artifact comparisons for ordering,
  omissions, exactness, skipped state, and size. Investigate unrelated drift.
- [ ] **Step 6.2 — fresh inheritance review, residue audit, and stop.** A fresh
  reviewer uses only current source and top-level docs to identify subsystem,
  I/O, validation, matching, partial-evidence, canonical/derived,
  compatibility, and safe-change ownership. Remove only proven residue from
  this work, confirm no category-one defect or worthwhile category-two
  simplification remains, record disproportionate rejections, and declare the
  clean local optimum without beginning another speculative refactor cycle.

## 1. Complete the owner walkthrough

**Outcome:** Kyle has exercised the public workflow as a first-time user and
has judged its explanations, proposals, persisted state, drift reporting,
resumption behavior, and cleanup instructions from observed output.

**Prerequisite:** none. This is the next product task. During the walkthrough,
present exactly one action at a time and diagnose any failure before changing
code.

**Current status:** not complete. The owner self-testing pause remains active.
The walkthrough covers the README, the reproducible payment-service example,
a real no-glossary naming session with rejection and revision, artifact review,
maintained-glossary commands, a fresh-session reuse check, and disposable tests
of Claude installation, `sync-context`, cache cleanup, and uninstall guidance.
It does not authorize live evaluator batches, outside testing, or publication.

## 2. Finish the two optional live-host evidence lanes

These lanes improve host-specific evidence but do not broaden the product's
local security claims.

### Claude Code session-start evidence

**Outcome:** the existing evaluator records three controlled normal-profile
scenarios: canonical vocabulary present, vocabulary absent, and root-skill
invocation with model tools disabled.

**Prerequisite:** fresh explicit authorization to use Kyle's existing Claude
Max subscription for exactly three Claude Code calls with no retry, at no more
than 200,000 input and 6,000 output tokens total and a command-line cap of
$0.25 per call, plus creation and deletion of the evaluator's one named
temporary directory. Normal authentication is reused; no login state is read,
copied, or changed.

**Current status:** pending authorization. The offline evaluator and corrected
Draft 7-compatible response schema pass their tests. The retained first batch
stopped before SessionStart or model use because its earlier schema declared a
newer JSON Schema draft; that 0/3 miss remains in the evidence ledger. A manual
owner smoke test is useful partial evidence but does not satisfy the controlled
acceptance.

### Post-approval skill behavior

**Outcome:** recorded live scenarios show that report refresh writes only the
derived root `GLOSSABET.md` without promoting proposed terms, and that a
maintainer-owned `GLOSSARY.md` is read only after the skill first states its
independent naming baseline.

**Prerequisite:** the evaluator changes must be implemented and tested offline;
then Kyle must explicitly authorize the stated number of authenticated Codex
turns and their token/cost ceiling.

**Current status:** not started. Existing installed-agent evidence covers the
Step 0 boundary, not these post-approval behaviors.

## 3. Modularize and type the evaluation harnesses

**Outcome:** the four evaluation entry points (`scripts/agent_eval.py`,
`scripts/claude_eval.py`, `evaluation/run.py`, `evaluation/review.py`) are
thin wrappers over lane-oriented packages under `evaluation/` (`harness`,
`codex`, `claude`, `deterministic`, `reviewer`); offline verification never
imports live-host modules; lifecycle state is explicit dataclasses rather than
attributes attached to exceptions; evaluation code passes mypy; every recorded
result binds to an aggregate evaluator-code identity covering all governing
source. Behavior, thresholds, schemas, and every committed result, history,
scenario, and packet JSON stay byte-for-byte unchanged.

**Full specification:** [`docs/plans/evaluation-modularization.md`](docs/plans/evaluation-modularization.md)
— binding for scope, non-goals, import direction, type strategy, compatibility
contracts, and per-pass acceptance.

**Prerequisite:** none; this is engineering work independent of the owner
pause. No live evaluator run, `--probe-missing-cli`, `--fetch`,
`--run-reviewer`, or plugin lifecycle smoke is ever part of it.

**Current status:** in progress. One pass per session (`/next` executes one
step and stops); each pass ends green with no recorded-evidence change.

- [x] Pass 1 — characterize behavior and establish shared identity
  (2026-08-22). `evaluation` and `evaluation.harness` are packages;
  `harness/io.py` holds the shared bounded-JSON, framed-hash, tree-walk, and
  atomic-replace primitives; `harness/identity.py` computes each lane's
  aggregate source identity (wrapper + lane package + transitively imported
  harness modules), now written into every lane's `evaluator_sha256` /
  `source_sha256`. Characterization tests pin all four CLIs
  (`tests/test_evaluation_cli.py`); identity mutation and boundary tests live
  in `tests/test_evaluation_harness.py`. Note: the Claude results verifier
  exits 1 by design — it reports the retained 0/3 batch — and the
  characterization pins that, not the spec's "passes" wording.
- [x] Pass 2 — extract Codex offline results and history (2026-08-22).
  `evaluation/codex/` holds `contract.py` (paths, constants, error type,
  lane JSON I/O), `scenarios.py` (manifest validation), `artifact.py`
  (release-gate plugin artifact check — the lane's only subprocess, never
  in default mode), `results.py` (result + history verification, typed
  summaries), `history.py` (typed attempt records, immutable retention);
  `scripts/agent_eval.py` keeps only host/scenario code. Tests import the
  new owners; `tests/test_codex_lane.py` proves default verification spawns
  nothing and reads no user state. **Evaluation expectation changed with
  Kyle's authorization:** `plugin` left `self_nominations.required` in
  `evaluation/corpus.json` (8 checks, 7 passing; `drift` remains the open
  miss). Its nomination was carried by the Codex evaluator living in one
  file, not by product code, and vanished when that file was split.
  Open heuristic observation: nomination ranking is sensitive to how
  non-product tooling is laid out across modules. Recorded
  `evaluation/results.json` is untouched and still verifies as genuine.
- [x] Pass 3 — extract Codex traces and scenarios (2026-08-22).
  `evaluation/codex/trace.py` (bounded JSONL/event parsing, command
  extraction, path-redacting summaries, installed-version check),
  `fixtures.py` (per-scenario repositories and the write-diff snapshot; its
  only process is `git` for the two graph fixtures), `scenarios.py`
  (manifest validation plus every per-scenario, session-hook, and
  missing-CLI judgment, pure). `scripts/agent_eval.py` is 932 lines of host
  lifecycle and orchestration. `tests/test_codex_lane.py` proves judgment
  modules import no process machinery and fixtures spawn only `git`.
- [x] Pass 4 — extract Codex host lifecycle (2026-08-22).
  `evaluation/codex/host.py` (command execution, version probe, temporary
  marketplace, `PluginLifecycle` dataclass advanced by `install_plugin` and
  consumed by `cleanup_plugin`, standalone-skill shadow), `runner.py`
  (hook/plugin/missing-CLI sessions, result assembly, typed `AbortedRun`
  built after cleanup, original exception re-raised unmodified), `cli.py`.
  `scripts/agent_eval.py` is an 18-line wrapper. No exception in the lane
  carries attached state. `tests/test_codex_lane.py` proves cleanup at
  every stage (before marketplace, after marketplace, after plugin
  install, during interrupt, cleanup-failure-after-failure) and that
  importing the results verifier never loads the host module.
- [x] Pass 5 — extract Claude offline results and history (2026-08-22).
  `evaluation/claude/contract.py` (paths, pinned host/budget/limit
  expectations, canaries, `ClaudeEvaluationError` and the typed
  `ScratchCleanupFailed`, the lane's `ensure_ascii=False` JSON encoding,
  strict symlink-rejecting tree digest, manifest/schema loaders),
  `events.py` (pure JSONL event readers shared by live judgment and
  offline verification), `history.py` (typed attempt records, `AbortedRun`,
  write-once raw results, mirror promotion), `results.py`
  (`verify_history`, `verify_results`). The lane's last exception-attached
  attribute is gone: a cleanup failure is a distinct exception type.
  `tests/test_claude_lane.py` proves offline modules import no host and
  default verification spawns nothing and never touches the home directory.
- [x] Pass 6 — extract Claude host, scenarios, and runner (2026-08-22).
  `evaluation/claude/host.py` (sanitized normal-profile environment,
  version/auth preflight, installed-plugin inspection, the zero-tool
  `claude` command, output sanitization, scratch ownership), `fixtures.py`
  (scenario repositories and write-diff snapshot; only `git` is spawned),
  `scenarios.py` (pure per-scenario judgment), `runner.py` (three bounded
  host calls, guaranteed scratch removal, typed `AbortedRun` retained
  before the original exception is re-raised), `cli.py`.
  `scripts/claude_eval.py` is an 18-line wrapper. `tests/test_claude_lane.py`
  proves scratch removal under ordinary failure and interruption and that
  a cleanup failure is a typed error carrying no attached attribute.
- [x] Pass 7 — split deterministic sources and scoring (2026-08-22).
  `evaluation/deterministic/contract.py` (paths, schema version, pinned
  threshold metric set, confined Git configuration, section vocabularies,
  `EvaluationError`), `sources.py` (hostile-manifest validation, confined
  Git fetch, engine/corpus identity, cache and timed builds — the one
  process is `git` under `GIT_SAFE_CONFIG`), `scoring.py` (lexical,
  register, nomination, drift, structural families kept whole; entry points
  typed with the production `EvidenceDocument`, `DriftDocument`,
  `ValidationDocument`). Formulas moved verbatim; three shadowed locals in
  `run.py` renamed. `tests/test_deterministic_lane.py` proves scoring is
  pure and sources spawn only safe-configured `git`.
- [x] Pass 8 — split deterministic aggregation, verification, and CLI
  (2026-08-22). `evaluation/deterministic/results.py` (aggregate,
  thresholds, genuineness, currency, `verify_results`), `runner.py`
  (per-source evaluation and run composition), `cli.py`; `evaluation/run.py`
  is an 18-line wrapper; `review.py` and the tests import the new owners.
  Both verifiers and the strict `--current` stale report are unchanged; no
  recorded JSON changed. **Calibration expectation changed with Kyle's
  authorization:** the self-nomination check is now 6/8 with
  `forbidden:file` recorded as a second open miss — see the heuristic item
  below. `corpus.json` is untouched; `file` stays forbidden.
- [ ] Pass 9 — split the reviewer lane; thin wrapper; explicit narrow
  dependency on deterministic result reading.
- [ ] Pass 10 — mypy gate for `evaluation/` and the wrappers, dependency
  tests, sdist/wheel checks, and documentation (`ARCHITECTURE.md`,
  `docs/CODE-WALKTHROUGH.md`, `EVALUATION.md`, command docs; drop the
  duplicated "Persisted documents are…" line).

### Nomination heuristic open findings

**Outcome:** the self-corpus nomination check returns to 8/8 because the
ranker is better, not because the expectation was lowered.

**Evidence (2026-08-22, gathered during Phase 3):**
- `file` (forbidden generic term) is nominated "deserves a canonical name"
  on the product package alone — probed with `evaluation/`, `scripts/`, and
  `tests/` ignored via a temporary root `glossabet.json`. A heuristic false
  alarm, previously masked by evaluator tooling living in the same corpus.
- `drift` is typed "deserves disambiguation" instead of "deserves a
  canonical name" when the tooling is present, but correctly when it is
  ignored: its call-site diversity across evaluator modules reads as meaning
  diversity. Sensitivity to non-product layout, not a product defect.
- `plugin` dropped out of the bounded top-15 once the Codex evaluator was
  split into modules; its earlier nomination had been carried by that one
  file. Removed from `self_nominations.required` as never measuring product
  vocabulary.

**Prerequisite:** none; engine work under the usual production-change
rules (labelled cases first, `evaluation/results.json` regenerated only with
explicit authorization). Candidate directions: a generic-term penalty or
stop-list for nomination, and weighting dispersion by production-role
modules only. Not part of the modularization phase.

**Current status:** not started.

## 4. Trusted alpha

**Outcome:** at least two consenting maintainers have used the exact installed
build, and the measured set totals at least five varied repositories. The
record includes opt-in scope, repository traits, failures, false alarms,
usefulness feedback, and exact build identity without copying private
repository content here.

**Prerequisite:** Kyle explicitly ends the owner self-testing pause and the
owner walkthrough is complete.

**Current status:** blocked by the intentional owner pause; no invitations are
to be sent yet.

## 5. Exact-artifact release candidate

**Outcome:** one immutable source state and its wheel, source distribution, and
plugin are tied to the same hashes and pass deterministic evaluation, current
installed-agent and reviewer gates, the full supported-platform CI matrix,
distribution checks, and clean install/update/remove smoke tests. The report
separates proven behavior, measured alpha evidence, and remaining limitations.

**Prerequisite:** trusted-alpha evidence is complete.

**Current status:** not started. Ordinary development verifies recorded
evidence for integrity; the `--current` evidence gates and plugin rebuild are
release-candidate work.

## 6. External publication

**Outcome:** only after a successful release candidate, separately authorized
actions may enable GitHub private vulnerability reporting or dependency
security updates, register/upload the package, create a Git tag or GitHub
Release, or submit a public plugin listing.

**Prerequisite:** the exact-artifact release candidate passes and Kyle
explicitly authorizes each account or public-state change.

**Current status:** not authorized and not started. Local verification never
publishes merely because it passes.
