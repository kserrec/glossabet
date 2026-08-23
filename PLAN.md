# Glossabet — Current Roadmap

Last updated: 2026-08-22.

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
- [ ] Pass 3 — extract Codex traces and scenarios (pure parsing, fixtures
  separated from judgments).
- [ ] Pass 4 — extract Codex host lifecycle (explicit `PluginLifecycle`
  dataclass, cleanup tests at every stage); `scripts/agent_eval.py` becomes a
  thin wrapper.
- [ ] Pass 5 — extract Claude offline results and history.
- [ ] Pass 6 — extract Claude host, scenarios, and runner; thin wrapper.
- [ ] Pass 7 — split deterministic sources and scoring (formulas intact, typed
  production documents).
- [ ] Pass 8 — split deterministic aggregation, verification, and CLI; thin
  wrapper.
- [ ] Pass 9 — split the reviewer lane; thin wrapper; explicit narrow
  dependency on deterministic result reading.
- [ ] Pass 10 — mypy gate for `evaluation/` and the wrappers, dependency
  tests, sdist/wheel checks, and documentation (`ARCHITECTURE.md`,
  `docs/CODE-WALKTHROUGH.md`, `EVALUATION.md`, command docs; drop the
  duplicated "Persisted documents are…" line).

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
