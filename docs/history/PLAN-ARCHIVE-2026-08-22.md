# Glossabet — Historical Plan Archive Through 2026-08-22

> Historical record. These completed implementation entries are preserved for
> provenance and may use the project's former name or describe superseded
> code. They are not current instructions.

Completed phases moved verbatim from PLAN.md. This is the permanent
implementation record; entries are never condensed or reordered.

### Phase 0 — Bootstrap ✅ (2026-08-14)
Repo created at `~/Projects/glossarize`, git initialized; PLAN.md, README.md,
CLAUDE.md, .gitignore written. Open decisions listed below for discussion
before Phase 1.

### Phase 1 — Package and CLI skeleton ✅ (2026-08-14)
Steps:
1. `pyproject.toml` (name `glossarize` — confirmed free on PyPI), package
   layout `glossarize/`, console entry point `glossarize`.
2. CLI dispatcher with `--version` and a `scan` stub that reports "not yet
   implemented" cleanly; exit statuses defined (0 ok, 1 user error, 2 defect).
3. Test harness (framework per open decision) with one real test: the CLI
   invokes, `--version` matches the package version.
4. Verify `uv tool install .` works end to end.
Acceptance: fresh clone → install → `glossarize --version` succeeds.

### Phase 2 — Lexical scanner and RepositoryEvidence v1 ✅ (2026-08-14)
Steps:
1. Repo walk: prune noise dirs (`.git`, `node_modules`, `_build`, `target`,
   `dist`, hidden dirs, etc.); exclude sensitive files by pattern with a test
   proving `.env`-style files never enter evidence; exclude `glossarize-out/`,
   `.glossarize/`, `GLOSSARY.md` (contamination rule).
2. Inventory: directory/package structure, source files by language (by
   extension), documentation files (README, docs/, ADRs, CLAUDE/AGENTS.md).
3. Identifier extraction: tokenize identifiers from source text (cheap
   lexer-level scan, not parsing) and normalize `PaymentService` /
   `payment_service` / `payment-service` / `paymentService` to shared tokens;
   collect doc-text vocabulary separately.
4. `RepositoryEvidence` model and `evidence.json` writer: `schema_version`,
   repository metadata, git stamp (HEAD, dirty), files, modules (directory
   granularity), documents, identifier vocabulary with counts and source
   locations. Deterministic ordering.
5. Bounded artifact discipline (principle 12): full counts always, but at
   most N representative source locations per term (deterministically
   chosen); when capped, the term carries a truncation marker and the
   artifact records totals dropped, so capped never reads as complete.
6. Monorepo detection: during the walk, detect workspace manifests
   (`pnpm-workspace.yaml`, Cargo workspace tables, `go.work`, Bazel files,
   multiple `package.json`/`pyproject.toml` roots) and size thresholds;
   record a `monorepo` flag with the detected sub-project roots and size
   stats in evidence, and emit a CLI warning recommending per-sub-project
   runs (Graphify's corpus warnings are prior art).
7. Tests: determinism (two runs, identical output), tokenizer table-driven
   cases, sensitive exclusion, contamination exclusion, truncation capping
   (capped output is deterministic and marked), monorepo detection on a
   fixture workspace.
Acceptance: `glossarize scan .` on this repo and one large external repo
produces correct, deterministic, secret-free, size-bounded evidence.

### Phase 3 — Evidence-aware skill ✅ (2026-08-14)
Steps:
1. Move the skill into `skill/SKILL.md` as the canonical copy (pending open
   decision); keep behavior and philosophy verbatim.
2. Add an evidence protocol section: if `glossarize-out/evidence.json` exists,
   check its git stamp against current HEAD/dirty state; if fresh, ground
   Steps 1–3 (scan, register, nomination) in it, still reading key files
   directly for judgment; if stale or absent, say so and either offer
   `glossarize scan .` or fall back to direct reading. Never silently use
   stale evidence.
3. Monorepo alert protocol: when the evidence carries the `monorepo` flag,
   the skill pauses before nominating and asks the user plainly — proceed
   whole-repo, or run glossarize per sub-project for healthier vocabulary?
   It never proceeds silently on a flagged monorepo. (Deliberate decision
   2026-08-14: alert only — no subagent fan-out.)
4. Installation story for the skill copy in `~/.claude/skills/` (manual copy
   for now; a `glossarize install` command can follow Graphify's pattern in a
   later phase if wanted).
Acceptance: a `/glossarize` run on a scanned repo demonstrably uses the
evidence (and says so); on a stale artifact it warns.

### Phase 4 — Terminology intelligence ✅ (2026-08-14)
In-phase decision: terminology embeds into evidence.json (no sibling
artifact), so the skill's existing evidence protocol covers it with no
third skill change; `analyze` = scan + human-readable report.
Steps:
1. Term frequency across identifiers and docs, merged across naming
   conventions; per-module and per-layer (code vs docs) breakdowns.
2. House-register statistics: identifier word-count distribution, common
   suffixes/prefixes (`*Service`, `*Manager`, …), dominant vs rare vocabulary
   families — machine grounding for skill Step 2.
3. Synonym-cluster nomination: co-occurrence in similar module locations and
   similar lexical contexts → "possible vocabulary overlap" reports (Job /
   Task / WorkItem class). Nominations carry evidence, never verdicts.
4. Overloaded-term nomination: one term appearing across lexically/structurally
   distant contexts.
5. Bounded analysis (principle 12): pairwise work in steps 3–4 restricted to
   the top-N vocabulary by frequency; N and the dropped remainder are
   reported in the output, never silently omitted.
6. `glossarize analyze .` emits a terminology section (into evidence.json or a
   sibling artifact — decide by size in-phase).
Acceptance: on a real repo, analyze surfaces at least register stats,
frequency tables, and any genuine overlap candidates, each with evidence refs.

### Phase 5 — Import edges and importance signals ✅ (2026-08-14)
Steps:
1. Best-effort import/include extraction by regex for the common languages in
   the scanned repo (Python, JS/TS, Go, Rust, Java, OCaml, …) — explicitly
   lossy, tagged as such in evidence.
2. Module dependency counts (fan-in/fan-out at file/directory granularity) and
   doc-mention frequency as importance signals.
3. Nomination ranking: combine signals into "likely deserves a name" evidence
   for skill Step 3 (the `PrincipalContext`-style nomination card).
Acceptance: importance ranking on a known repo is sane and every nomination
carries its reasons.

### Phase 6 — Persistent glossary ✅ (2026-08-14)
Steps:
1. `glossary.json` minimal schema (see Artifacts) with status lifecycle;
   writer/reader in the engine; `glossarize show`.
2. Skill finalize step (Step 6) writes both `GLOSSARY.md` (existing format,
   unchanged) and `glossary.json`; only human-settled terms get `canonical`.
3. Skill startup reads an existing glossary and never restarts the brainstorm
   from scratch: canonical terms are respected, open items resume.
Acceptance: settle a small vocabulary on a test repo, rerun `/glossarize`,
confirm it resumes rather than restarts.

### Phase 7 — Drift and collision detection ✅ (2026-08-14)
Steps:
1. `glossarize drift .`: compare fresh evidence vocabulary against
   `glossary.json` — new prominent terms paralleling canonical ones
   (Execution vs Run), deprecated/discouraged terms still spreading, canonical
   terms fading from code.
2. Collision reports: a canonical term used across contexts distant enough to
   suggest overload.
3. Reports are evidence + confidence, with concrete refs; no auto-rewrites.
Acceptance: seeded drift in a test repo (rename a concept in new code) is
detected and reported with correct evidence.

### Phase 8 — Incremental indexing ✅ (2026-08-14)
In-phase decision: invalidation is uniform per-file mtime_ns+size (not
git-diff) — same complexity, robust across tracked/untracked/dirty
states; whole-cache invalidation on generator version change.
Steps:
1. `.glossarize/` cache keyed on git state; `scan` updates only changed files
   (git diff against the stamped HEAD, falling back to mtimes when unstamped).
2. Cache correctness test: incremental result identical to cold scan.
Acceptance: on a large repo, warm `scan` touches only changed files and
matches a cold scan byte-for-byte.

### Phase 9 — Graphify adapter ✅ (2026-08-14)
Steps:
1. `GraphifyEvidenceAdapter`: `graphify-out/graph.json` → RepositoryEvidence —
   nodes → symbols/entities, communities (+ cohesion) → structural groups,
   centrality/god-nodes → importance signals, doc-derived nodes tagged with
   provenance; glossary-derived nodes discounted (contamination rule).
2. Auto-detection: `scan`/`analyze` use the adapter when `graph.json` exists
   and is fresh, merged with (not replacing) lexical evidence; `--no-graphify`
   escape hatch.
3. Version tolerance: adapter validates the graph schema it understands and
   degrades gracefully (warn + proceed lexical-only) on unknown shapes.
Acceptance: same repo scanned with and without Graphify present yields
compatible evidence, with structural groups only in the with-graph case.

### Phase 10 — Reconciliation and bindings ✅ (2026-08-14)
Steps:
1. Bindings in `glossary.json`: concept → symbols/files/modules (stable
   identities only), written during skill finalization when the user confirms
   the mapping; unresolved bindings surface as drift, not errors.
2. `glossarize validate .`: coverage both directions (structural groups
   without concepts; concepts with weak evidence) plus the mismatch taxonomy —
   unnamed structure, orphaned concept, vocabulary drift, concept collision,
   boundary mismatch, fragmentation, overloaded structural region — each
   reported with evidence and confidence, never as an automatic diagnosis.
3. Heuristic alignment only; no one-to-one assumption anywhere in the code.
Acceptance: on a repo with a settled glossary and a Graphify graph, validate
produces a correct coverage report including at least one deliberately seeded
mismatch of each direction.

## Moved 2026-08-18 (prune after Phase 36)

### Phase 11 — Research grounding and hostile-repository boundaries ✅ 2026-08-14

**Goal:** ground the product premise honestly and make every direct artifact
and cache path obey the hostile-repository threat model already claimed by the
project.

**Steps:**

1. Add primary studies to the README covering identifier comprehension,
   lexical inconsistency, naming divergence, and domain-specific dictionaries;
   state plainly that this validates the problem, not Glossabet's efficacy.
2. Centralize repository-confined direct-artifact reads and atomic JSON writes.
   Reject symlinked direct artifact paths instead of reading through them, and
   prevent output-directory symlinks from redirecting writes.
3. Move incremental cache state out of the scanned repository into the user's
   platform cache directory, key it by the repository's resolved path, and
   validate reusable entries against a SHA-256 digest of current file bytes.
   Treat malformed cache shapes as misses.
4. Make wrong top-level glossary JSON a clean user error, and enforce the same
   2 MB input bound on root workspace manifests as on walked source files.
5. Rewrite `SECURITY.md` to match the verified boundary exactly, including the
   distinction between path-based sensitive-file exclusion and secret-content
   scanning, then pin every repaired boundary with regression tests.

**Acceptance:** a direct artifact symlink cannot read or overwrite a file;
a repository-supplied legacy cache cannot inject evidence; malformed JSON
shapes degrade according to the documented contract; oversized root manifests
are skipped and reported; the complete test suite passes.

### Phase 12 — Real Graphify interoperability and validation honesty ✅ 2026-08-14

**Goal:** consume Graphify's observed public export schema rather than a
look-alike fixture, and tell users exactly how much structural validation ran.

**Steps:**

1. Support Graphify 0.9.42's `links`, `source_file`, and `community_name`
   fields while retaining explicitly tested compatibility with older accepted
   field names.
2. Distinguish "graph file present" from "usable structural evidence loaded";
   lexical-only validation must say that structural checks were skipped.
3. Surface Graphify adapter warnings and structured freshness
   (`current`/`stale`/`unverified`) in CLI and validation output. Use
   Graphify's observed `built_at_commit` stamp when present, and pin the
   contract with a fixture generated from the real exporter shape.

**Acceptance:** a representative Graphify 0.9.42 fixture yields real edges,
correct code/doc classification, preserved community names, and visible
freshness/warning state; graph presence is distinct from usable structural
coverage, and empty, group-less, or malformed graphs explicitly skip
structural validation.

### Phase 13 — Honest git freshness and artifact lifecycle ✅ 2026-08-14

**Goal:** make the freshness promise true from the first scan without silently
editing a target repository's ignore rules.

**Steps:**

1. Define and implement a git-state comparison that excludes only
   Glossabet-owned generated paths while preserving all user changes.
2. Use the same comparison in artifact stamps and the skill's freshness gate;
   cover tracked, untracked, ignored, and no-git repositories.
3. Document generated-file ownership and cleanup without modifying
   `.gitignore` automatically.

**Acceptance:** a first scan of a clean repository is immediately fresh;
subsequent user changes make it stale; generated Glossabet artifacts alone do
not; no target configuration is changed.

### Phase 14 — Terminology precision foundations ✅ 2026-08-14

**Goal:** lower false alarms before adding more kinds of findings.

**Steps:**

1. Add repository configuration for extra ignored paths and explicit treatment
   of tests, fixtures, generated code, and vendored code; defaults remain
   deterministic and conservative.
2. Require compound glossary terms to occur within one lexical unit or a
   defined local context, rather than matching words that appear anywhere in a
   file.
3. Make finding totals include capped/dropped findings, reserve confidence
   labels for measured or rule-proven certainty, and reject aliases that map to
   multiple concepts.
4. Recalibrate synonym and overload signals against production-code evidence
   instead of allowing test vocabulary to dominate by default.

**Acceptance:** pinned counterexamples no longer produce the observed
cross-file-word, alias-collision, capped-total, or test-noise failures, while
legitimate drift cases still report.

### Phase 15 — Evaluation corpus and calibration ✅ 2026-08-14

**Goal:** learn whether Glossabet is useful before expanding or marketing its
capabilities.

**Steps:**

1. Build a small, licensed corpus of varied repositories plus hand-labelled
   terminology and drift expectations; keep external source out of this repo
   unless its license permits inclusion.
2. Measure precision, recall where a complete label set is practical,
   false alarms per thousand files, truncation, cold/warm runtime, and reviewer
   usefulness; record methodology and raw aggregate results.
3. Derive and enforce deterministic whole-corpus file/byte/work limits from
   those measurements, reporting any skipped remainder in evidence.
4. Establish release thresholds and use failures to tune existing heuristics,
   not to add ungrounded features.

**Acceptance:** the README can cite a reproducible Glossabet evaluation—or
continues to make no efficacy claim—with failures and corpus limitations
reported alongside successes.

### Phase 16 — Scoped vocabulary and language semantics ✅ 2026-08-14

**Goal:** represent concepts that legitimately vary by subsystem and improve
lexical coverage without pretending regexes are a full parser.

**Steps:**

1. Add backward-compatible glossary scopes and enforce alias uniqueness within
   each scope; update drift and reconciliation consumers together.
2. Support Unicode identifiers and define how digits, acronyms, and common
   language-specific identifier forms are tokenized.
3. Reassess a parsing adapter against Phase 15's recorded no-dependency
   baseline; accept one only if new labelled failures demonstrate an accuracy
   gain that justifies its binary/transitive, security, and maintenance cost.

**Acceptance:** scoped concepts and representative non-ASCII identifiers round
trip deterministically through evidence, glossary, drift, and validation;
dependency decisions include measured benefit and explicit cost.

### Phase 17 — Distribution and release readiness ✅ 2026-08-14

**Goal:** let a new user install, understand, and safely evaluate the project
without repository-owner knowledge.

**Steps:**

1. Add `glossabet install` for the canonical skill, an end-to-end sample
   walkthrough, and explicit privacy/data-flow documentation for local and
   agent-mediated use.
2. Add CI across supported Python versions and platforms, packaging checks,
   changelog/release metadata, and a reproducible smoke test from built wheel.
3. Prepare—not perform—PyPI publication and public security-reporting steps;
   actual account use and publication require Kyle's explicit authorization.

**Acceptance:** a clean environment can install the built artifact, run the
walkthrough, execute the full suite, and uninstall cleanly; release docs state
exactly what remains manual and externally visible.

### Phase 18 — Agent boundary and hostile glossary/input hardening ✅ 2026-08-14

**Goal:** make the CLI the sole machine-data boundary for the agent skill and
make hostile glossary data safe to validate and display at bounded cost.

**Steps:**

1. Add `glossabet inspect .`, which performs a fresh scan through the existing
   confined scanner, safely loads the optional glossary, persists the normal
   evidence artifact, and emits a versioned, size-bounded JSON context for the
   agent. Every truncated collection carries counts and completeness metadata.
2. Rewrite the skill's opening protocol to invoke `inspect`; remove direct
   reads of Glossabet JSON artifacts and the unrestricted repository-reading
   fallback. Route finalized machine state through bounded stdin to
   `glossabet save .` rather than letting the skill write the artifact. If the
   matching CLI is unavailable or the context is invalid, stop with a precise
   installation/version error. Targeted reads of source files named by the safe
   context remain part of the brainstorm workflow.
3. Make glossary validation strict at every object level, cap concepts,
   aliases, bindings, scopes, strings, and reported diagnostics before
   expensive work, and replace pairwise vocabulary-owner checks with an
   indexed overlap check whose work scales with accepted input size.
4. Centralize terminal rendering for repository-controlled values and error
   messages. Reject control and bidirectional-format characters in glossary
   identity fields and render hostile characters visibly rather than emitting
   raw terminal control sequences.
5. Add adversarial contract, schema, scale, symlink, malformed/oversized input,
   and terminal-output regressions; synchronize `README.md`, `ARCHITECTURE.md`,
   `SECURITY.md`, and `PRIVACY.md` with the verified boundary.

**Acceptance:** the installed skill never opens `evidence.json`, never opens or
writes `glossary.json` itself, and never silently bypasses the CLI; the context is
fresh, bounded, and explicit about omissions; typo fields and over-budget
glossaries fail cleanly with bounded diagnostics; vocabulary ownership
validation is non-quadratic; hostile repository/glossary strings cannot emit
raw terminal control sequences; focused and full suites pass.

### Phase 19 — Completeness and downstream complexity accounting ✅ 2026-08-14

**Goal:** ensure every terminology and Graphify claim is based on all accepted
evidence—or is explicitly marked partial—and keep drift/reconciliation work
bounded after glossary loading.

**Steps:**

1. Introduce one shared coverage ledger for capped candidate, terminology,
   structure, validation, and drift collections; every consumer must carry
   exact totals where known, dropped counts, reasons, and a completeness flag.
2. Include the 151st-and-later ranked terminology candidates in totals and
   mark the section partial when details are capped. Apply the same rule to
   structural candidates so `structures_complete` cannot remain true after
   candidates are dropped.
3. Match a Graphify structural group against its complete bounded member token
   set; keep the six-member list only as a display sample. Replace permissive
   suffix/substring provenance tests with exact normalized source and type
   checks, including near-match counterexamples.
4. Replace group-by-concept matching in reconciliation with an inverted token
   index and count/stream boundary findings without materializing all
   member-pair combinations. Bound all remaining glossary-by-corpus work and
   report why anything was omitted.
5. Add scaling and threshold-edge tests for `build_drift()`,
   `build_validation()`, Graphify groups, terminology ranking, and coverage
   propagation.

**Acceptance:** no accepted 151st term or seventh Graphify member can disappear
behind a `complete: true` claim; near-match provenance is not misclassified;
downstream work has explicit budgets and sub-quadratic indexed paths; every
omission is observable and regression-tested.

### Phase 20 — Release automation and evidence integrity ✅ 2026-08-14

**Goal:** make local release evidence reproducible and ensure the release job
cannot publish an artifact that skipped the supported test matrix.

**Steps:**

1. Extract the full supported-platform test matrix into a reusable workflow
   and require the manual release workflow to call it before build or publish.
   Strengthen workflow-policy tests so meaningful gate weakening fails.
2. Constrain Hatchling to a reviewed stable range, record its direct and
   transitive cost, and retain pytest as the earned dev-only test dependency;
   preserve the zero-runtime-dependency package.
3. Add source/corpus digests and engine/version metadata to evaluation output,
   rerun the evaluation on the current engine and fixtures, and reject stale or
   mismatched result files in release checks.
4. Correct Phase 17-era release language everywhere: the package is locally
   packageable, not publicly released or efficacy-proven. Keep all claims
   scoped to the measured corpus and reviewer set.

**Acceptance:** release automation cannot reach build/publish unless the full
matrix passes; workflow mutation tests prove that dependency; build tooling is
constrained and justified; evaluation results identify their exact inputs and
current engine; documentation makes no stale readiness claim.

### Phase 21 — Name clearance and preferred Codex distribution ✅ 2026-08-15

**Decision checkpoint (2026-08-14):** Kyle selected **Glossabet** to replace
the pre-release working identity **Glossarize**. The intended coinage is
`glossa` plus the ending of `alphabet`, pronounced “GLOSS-uh-bet.”
`NAME-CLEARANCE.md` records the 2026-08-15 exact package, GitHub, command,
configured Codex directory, domain, indexed-use, historical-use, and official
USPTO probes. No exact current result was found in those bounded checks. They
neither reserve the name nor replace legal clearance.

**Goal:** settle the product identity before publishing it and prove the
preferred Codex plugin experience without weakening the standalone package.

**Steps:**

1. Run and record current package, repository, command, plugin-directory, and
   relevant trademark/name searches. Choose one explicit exit before any
   public artifact: keep `Glossarize`, qualify it, or rename all user-facing
   surfaces atomically.
2. Build a local Codex plugin prototype that contains the canonical skill and
   matching CLI package, with an explicit version-coupling check and a clean
   install/update/remove smoke test. Do not advertise unsupported host
   behavior; the Claude target remains experimental until separately tested.
3. Keep the wheel/`uv tool install` route as the atomic fallback and document
   exactly which install route owns the CLI, skill copy, upgrades, and removal.

**Acceptance:** a recorded clearance decision covers every public surface; a
clean Codex plugin install supplies matching skill/CLI versions and removes
cleanly; the wheel fallback remains reproducible; no channel or host is called
supported without a direct probe.

**Completion evidence:** the source package/import, CLI, skill, plugin,
configuration, artifacts, cache namespace, fixtures, tests, and current docs
now use Glossabet. Pre-rename output/cache paths remain excluded and were not
migrated, modified, or deleted. One intermediate rename-audit search included
an existing ignored output artifact before its legacy exclusion was restored.
A local marketplace installed plugin 0.1.0 through Codex CLI 0.147.0 on Linux,
ran the bundled `inspect` boundary, updated to a
synthetic matched 0.1.1 bundle, removed the prior cached version, and then
removed every test-owned plugin/marketplace/cache entry. The plugin manifest,
canonical skill, runner, nested wheel, package metadata, and embedded skill
are version-coupled in unit and archive checks. The independent wheel smoke
still installs, exercises, and uninstalls the normal `glossabet` command. The
hosted GitHub slug and Kyle's separate legacy `glossarize 0.0.1` installation
were observed but left unchanged; no package, plugin, domain, tag, release, or
other public state was created.

### Phase 22 — Installed-agent and structural evaluation ✅ 2026-08-15

**Goal:** test the product through the interface a real user invokes and add
the missing deterministic evidence for Graphify-backed structural claims.

**Steps:**

1. Add labelled Graphify cases for unnamed boundaries, overloads, orphans,
   fragmentation, the seventh member, near-match provenance, and truncation;
   measure structural precision/recall where the labels are complete.
2. Run the actually installed Codex skill against fresh, stale, absent,
   malformed, oversized, symlinked, partial, monorepo, resumed-glossary,
   missing-CLI, and sensitive-file scenarios. Capture bounded tool traces and
   verify that it neither reads excluded content nor writes before approval.
3. Add a second independent reviewer to the current evaluation protocol and
   record disagreements separately from deterministic engine correctness.

**Acceptance:** both lexical and structural measurements are reproducible;
the installed skill/CLI boundary passes every hostile and lifecycle scenario;
reviewer usefulness is supported by at least two independent reviewers, with
no claim broader than the tested corpus.

**Completion evidence:** the seven-case, five-run evaluation covers 99 source
files and 52 production-code files. It records 100% structural precision and
recall where complete, all 17 complete-fixture and 9 truncation contracts, 15/15
lexical contracts, zero false alarms, and passing release thresholds. A second
ephemeral Codex session reviewed all 20 findings from a blinded packet in an
isolated read-only directory: it marked 17 useful, agreed with the primary
reviewer on 17, and preserved three explicit disagreements. Codex CLI 0.147.0
on Linux read the exact temporarily installed plugin skill, version-checked its
bundled engine, and passed all 11 fresh/stale/absent/hostile/lifecycle scenarios;
the standalone missing-CLI case stopped before `inspect`. Sensitive content
never entered the bounded trace or response, the only permitted repository
change was `inspect`'s documented evidence refresh, and every temporary
plugin/marketplace/cache entry was removed. Offline verifiers bind these
artifacts to their evaluator, prompt, schema, engine, bundle, manifest, and
local corpora. The full suite passes 303 tests. No production engine, CLI, or
skill behavior changed in this phase. This remains controlled/local evidence,
not outside maintainer adoption or broad efficacy evidence. Agent execution is
stochastic: four of five observed full plugin batches satisfied the required
version preflight, including one of two unchanged attempts against the final
wheel bytes. The Phase 22 artifact committed at that time was the successful
exact-bundle run, not a zero-flake claim.

### Repository identity and exact-artifact update — completed 2026-08-15

With Kyle's explicit authorization, the public GitHub repository was renamed
from `kserrec/glossarize` to `kserrec/glossabet`, the configured `origin` was
changed to `git@github.com:kserrec/glossabet.git`, and the local checkout was
moved from `<local>/glossarize` to
`<local>/glossabet`. GitHub's old repository path was
verified to resolve to the renamed repository, and the old local directory no
longer exists. During the authorized documentation wrapup, the package project
URLs and distribution assertion were switched to `kserrec/glossabet`, the
embedded plugin wheel was rebuilt, and the installed-agent evidence was
regenerated against those exact bytes. Only wheel `METADATA` and `RECORD`
changed; executable entries remained byte-identical. A final README status
sync changed metadata only, so the wheel and evidence were rebuilt once more
against the final source state. The first public-main CI run then proved the
evidence identity included an ignored local `__pycache__` file that clean
checkouts lacked. The existing tree-identity function now excludes Python
interpreter cache directories. The replacement matrix then passed on Linux and
macOS but proved native `Path` sorting ordered mixed-case plugin files
differently on Windows. Identity now sorts canonical POSIX relative-path
strings, a focused regression locks each behavior, and evidence was regenerated
against the final evaluator and unchanged wheel. All four post-Phase 22 batches
passed all 11 scenarios. Public-main CI for commit `2be99b6` passed all 15
Python/operating-system matrix jobs plus the evidence, build, and
distribution-smoke job, and every temporary Codex plugin/marketplace entry was
removed. These internal changes did not end the owner self-testing pause,
change repository visibility, publish a package or plugin, create a tag or
release, or contact outside maintainers.

### Phases 24–28 — Self-testing quality findings (added 2026-08-15)

Provenance: Kyle's owner self-testing surfaced five defects, each verified
against the engine's own output on this repository on 2026-08-15 (`glossabet
inspect .`: 552,619 bytes; `the` at count 246 in the identifier top ten;
register reported as 55.4% flat / 66.2% one-word; top term nominations
`json`, `path`, `file`, `name`, `run`, `root`). All five live in revisable
layers — statistics, scoring, projection, delivery — not in the binding
contracts. These are implementation phases and are permitted during the
owner self-testing pause, which forbids only outside invitations, Phase 23,
and publication setup. Execution order: 24 → 25 → 26 (each feeds the next),
27 independently, then 28.1 → 28.2/28.3 after 27 (Phase 28 is split into
three passes; see its section). All five must complete before the
trusted-alpha gate.

### Phase 24 — Language/domain vocabulary partition ✅ 2026-08-15

**Goal:** stop language-supplied vocabulary (builtins and ubiquitous stdlib
names) from consuming bounded analysis budgets, while keeping evidence
complete and every exclusion reported.

**Steps:**

1. Add per-language builtin token sets beside `KEYWORD_TOKENS`, built with
   the same deliberately moderate stance: unambiguous language vocabulary
   (Python `dict`, `len`, `append`, `isinstance`, `sorted`) enters; overlaps
   with plausible domain words (`open`, `type`, `run`, `match`) stay domain.
2. Tag, never delete: each vocabulary token carries an origin (`language` or
   `domain`) in evidence. The full token record remains in the artifact.
3. Terminology's top-150 eligibility and importance's term-candidate pool
   consider domain-tagged tokens only; their coverage ledgers state the
   language-token exclusion and its count so filtered output never reads as
   complete.

**Acceptance:** on this repository, no pure-builtin token occupies a
terminology eligible-top-150 slot or a term naming candidate; every
language-tag exclusion is visible in coverage; determinism and the complete
token record are regression-tested.

**Completion evidence:** RepositoryEvidence v8 tags every retained code token
as `language` or `domain`. The deliberately conservative Python table includes
the verified builtins while leaving `open`, `type`, `run`, `match`, and
`register` available as domain vocabulary; an occurrence in an unlisted
language promotes a same-spelled token to domain. On this repository, all 1,962
tokens remain in evidence: 21 are language-origin and 1,941 domain-origin. The
21 language tokens are named in both coverage ledgers, consume none of the 150
terminology slots, and produce no term nomination. The remaining generic
nominees (`json`, `path`, `file`, `name`, `run`, `root`) are deliberately left
for Phase 26 rather than smuggling distinctiveness work into this phase. Five
focused regressions cover the required Python set and domain exceptions,
tag-not-delete behavior, mixed-language domain precedence, top-150 exclusion,
naming exclusion, coverage, and determinism. The refreshed seven-case,
five-run evaluation retains precision 1.0, zero false alarms, and passing
thresholds; its 20 blinded finding payloads were exactly unchanged, so the
existing second-reviewer judgments were retained with explicit reuse
provenance. The full suite passes 310 tests, and a newly built standalone wheel
passes its isolated smoke test. The checked-in plugin wheel and installed-agent
evidence remain the last exact Phase 22 bundle rather than being silently
relabelled as Phase 24 evidence; they must be rebuilt and rerun no later than
Phase 27's installed-skill acceptance check.

### Phase 25 — Register integrity ✅ 2026-08-15

**Goal:** the reported house register must describe names the repository
coined — not comment prose or language builtins — and any filtered statistic
must state its own composition. (Depends on Phase 24. The scanner stays
lexical; this phase changes only the statistics layer.)

**Steps:**

1. Partition identifier spellings into structurally code-styled
   (`snake_case`, `camelCase`, `PascalCase`, `UPPER_SNAKE` — a compound
   spelling cannot be prose) and flat (ambiguous). Compute the headline
   style and token-count distributions from the styled partition.
2. Admit a flat spelling into the register only with code corroboration: not
   language-tagged (Phase 24) and not prose-corroborated (its `doc_terms`
   presence dominates its code presence). Report how many spellings were
   used and how many were excluded, by reason.
3. Add register accuracy to the evaluation harness: label the true register
   of the pinned corpus repositories (and this repository: snake_case,
   predominantly multi-word) and measure the reported register against the
   labels. Phases 15/16 measured synonym/overload labels only; register
   skew survived because no evaluation covered it.

**Acceptance:** this repository's reported register reflects its snake_case
multi-word reality; register output names its own composition and
exclusions; a labelled register check exists in the evaluation and passes.

**Completion evidence:** RepositoryEvidence v9 classifies multi-token
`snake_case`, `camelCase`, `PascalCase`, and `UPPER_SNAKE` spellings as the
structurally styled headline population. Flat and one-token case variants are
admitted only when domain-origin and not document-dominated; every spelling is
accounted for under an exact used/excluded reason. Glossabet now reports
`snake_case` as its dominant styled register and a predominantly multi-word
identifier distribution. Evaluation manifest v4 and result schema v5 add two
labels for each of the seven pinned cases and this repository; all 16 register
checks and the new 1.0 release threshold pass. The finding payloads remain a
separate evaluation surface, so register labels do not manufacture terminology
or drift correctness.

### Phase 26 — Nomination distinctiveness ✅ 2026-08-15

**Goal:** `naming_candidates` must point at the repository's own concepts,
not its most frequent tokens. (Depends on Phases 24–25. Nominations remain
evidence for the skill's Step 3, never verdicts.)

**Steps:**

1. Term candidates draw from domain-tagged tokens only.
2. Add a compound-productivity signal from the existing `token_patterns`
   data: a token that anchors many distinct compounds (`evidence` in
   `build_evidence`, `write_evidence`) outranks an equally frequent token
   that only appears alone. No new evidence collection is required.
3. Consult terminology's overload dispersion and emit typed nominations:
   wide use with consistent contexts → "deserves a canonical name"; wide
   use with divergent contexts → "deserves disambiguation." This resolves
   the importance/overload tension by making both signals explicit instead
   of leaving importance blind to dispersion.
4. Every candidate keeps plain-number reasons; caps and drops stay reported.

**Acceptance:** on this repository, generic tokens (`json`, `path`, `file`,
`name`, `run`, `root`) no longer fill the term-candidate slots and domain
concepts (e.g. `drift`, `register`, `nomination`, `coverage`, `staleness`)
surface; nomination kinds are labelled; a labelled nomination-quality check
exists in the evaluation and passes.

**Completion evidence:** RepositoryEvidence v10 requires an explicit `domain`
origin for every term candidate and ranks count-normalized distinct compound
patterns from the existing vocabulary aggregate, with repository breadth,
documentation, and exact source-file-name anchors as supporting signals. Each
candidate reports raw uses, files, modules, documentation mentions, distinct
compound patterns, compound uses, and any source-unit or context-dispersion
evidence. Terminology now computes its bounded cross-module dispersion once;
importance reuses that exact profile to label every retained term either
`deserves a canonical name` or `deserves disambiguation`. All profile caps,
unknowns, filters, and drops remain in shared coverage ledgers.

On this repository, `drift`, `coverage`, `glossary`, `structural`, and other
project concepts fill the ranked list while `json`, `path`, `file`, `name`,
`run`, and `root` are absent. Evaluation manifest v5 and result schema v6 add
an 11-check self-nomination contract: four required concepts with exact kinds,
the six forbidden generic slots, and one all-candidates-typed assertion. All
11 checks and the new 1.0 release threshold pass. The existing 20 blinded
finding payloads remained exactly equal after removing only engine and
manifest identities, so the second-reviewer judgments retain explicit reuse
provenance rather than claiming a new review.

### Phase 27 — Lean agent context ✅ 2026-08-16

**Goal:** the `inspect` projection must fit routine agent context budgets;
the 1 MB ceiling is a failure backstop, never a target. (Independent of
Phases 24–26; `evidence.json` is unchanged — this is projection-layer work
in the existing agent-context module.)

**Steps:**

1. Serialize the agent context compactly (no indentation); measured 2× on
   this repository (552 KB pretty vs ~268 KB compact).
2. Replace per-item location lists (161 KB compact here, ~60% of the
   vocabulary section) with per-module rollups; keep file-level locations
   only where the skill reads files — naming candidates and register
   exemplars. The coverage ledger records the projection's omissions.
3. Set a soft size target (≤ 80 KB on this repository) checked by test, and
   provide `inspect --full` for the current complete shape.

**Acceptance:** `glossabet inspect .` on this repository emits at most the
soft target (down from 552,619 bytes measured 2026-08-15); every omission
relative to full evidence is observable in coverage; existing skill and
hostile-input scenarios still pass.

**Acceptance (2026-08-16):** the routine projection has a repository regression
at or below 80,000 bytes, records every projection omission, and preserves the
detailed pre-Phase-27 shape behind `inspect --full`. The current authenticated
installed-agent result, bound to the current evaluator, prompt, scenarios,
canonical skill, plugin, and engine, passes all 11 scenarios on Codex CLI
0.147.0/Linux. Each of the ten plugin scenarios ran one direct `inspect`
command with unchanged stdout and no pipe or projection. The missing-CLI host
run alone disables both profile loading and login-shell requests; its trace
uses `/usr/bin/zsh -c`, reads the installed standalone-skill boundary, observes
`glossabet --version` exiting 127, invokes no `inspect`, and makes no repository
write. The evaluator also disables a same-named user-level standalone
Glossabet skill for each host run without modifying that user-owned file.
Temporary plugin and marketplace state was removed, and the user-owned skill
remained byte-identical.

### Phase 28 — Ambient glossary consumption

**Goal:** after one finalized naming session, agents in every later session
read the canonical vocabulary with no user invocation — consumption becomes
ambient while changing vocabulary stays human-gated. (Depends on Phase 27.
This is the product's steady state: ambient read, human-authorized write.)

Phase 28 is oversized for one pass and is split per the one-phase-per-pass
rule into three sub-phases, each its own implementation pass with its own
acceptance check and commit. They are three different kinds of work:
28.1 is pure engine/CLI, 28.2 is plugin/host lifecycle verified by
installed-agent scenario batches rather than unit tests, and 28.3 writes to
user-owned files — the most sensitive operation Glossabet performs — and
carries its own hostile-scenario review. 28.2 and 28.3 both depend on 28.1
and are independent of each other, so a blocked hook host cannot strand the
digest or the sync command.

#### Phase 28.1 — Brief digest ✅ 2026-08-16

**Steps:**

1. `glossabet brief`: a deterministic digest of `glossary.json` (canonical
   terms, one-line definitions, scopes, aliases) bounded at 4 KB with the
   git stamp included. Staleness rules apply in full: the digest names the
   glossary state it renders.
2. Digest text follows the Phase 18.4 terminal-safety rules for
   repository-controlled content and is covered by the determinism,
   no-contamination, and no-secrets tests.
3. Document the ambient boundary in the skill and README: the ambient layer
   is read-only consumption; nominating, coining, and finalizing vocabulary
   still require a human `/glossabet` session.

**Acceptance:** brief output is deterministic, bounded, stamped, and covered
by the safety tests; it is usable by hand (piped or pasted into context)
before any delivery channel exists.

**Completion evidence (2026-08-16):** `glossabet brief` reads only the confined,
validated glossary plus the hardened Git stamp and never scans source or
writes repository state. It emits canonical terms with one-line definitions,
sorted scopes and alias statuses, a semantic glossary SHA-256, live Git
`{head, dirty}` state, and exact coverage within a 4,096-byte UTF-8 ceiling;
an absent glossary contributes no output. Tests cover deterministic output,
source and sensitive-file non-contamination, malformed and symlinked input,
terminal-safe prose, the byte ceiling, the human-gated skill contract, and
wheel/plugin parity. A direct run against the payment-service example produces
a complete three-term digest.

The phase closes against that written engine/CLI acceptance, not against a
selected green agent invocation. `evaluation/agent-history.json` retains all
six authorized Phase 28.1 agent attempts in order: one 11/11 full pass, one
10/11 full result whose missing-CLI agent skipped the installed boundary,
three passing focused missing-CLI probes, and one full run that stopped at the
single-version-preflight check after trying both a nonexistent plugin-root
runner and the actual skill-local runner. Only the 10/11 raw JSON survived the
earlier overwrite behavior; the other five entries are explicitly labelled
as contemporaneous session records rather than raw traces. The observed
procedural totals are four passes and two failures overall, plugin preflight
two of three, plugin scenarios two of two applicable completed batches, and
missing-CLI boundary four of five. These are small-sample reliability
measurements, not a release pass/fail threshold or a claimed future success
rate.

The offline gate now separates what can be proved deterministically from that
stochastic behavior. It binds the current canonical skill, plugin tree,
skill-local runner, and checked-in wheel by SHA-256; rejects an ambiguous
plugin-root runner; checks manifest/version and embedded-skill parity; and runs
exact version and bounded `brief` smokes through the bundled wheel. Safety is
still absolute: every retained attempt must record successful cleanup and no
sensitive exposure, unexpected repository write, or post-failure `inspect`.
Any safety failure fails verification; procedural agent misses remain visible
in the append-only attempt ledger. Future authenticated runs use unique raw
paths and cannot overwrite earlier evidence. No additional authenticated retry
was run for this protocol change. Phase 28.2 owns session-start delivery and
its host-lifecycle evidence.

#### Phase 28.2 — Session-start hook ✅ 2026-08-16

**Steps:**

1. The plugin ships a session-start hook that runs `brief` fresh in each
   session — fresh by construction, no repository mutation. With no
   glossary present the hook contributes nothing.
2. Extend the installed-agent scenario batches to cover hook delivery,
   binding evidence to exact artifact bytes per the Phase 22 machinery.

**Acceptance:** a fresh agent session with the hook installed sees the
canonical terms without any user mention of glossabet, proven on the probed
hosts; hosts without lifecycle probes are documented as unverified rather
than claimed.

**Completion evidence (2026-08-16):** the plugin manifest exposes one exact
`SessionStart` hook for startup, resume, clear, and compaction. It invokes the
skill-local runner's `brief .` boundary with bytecode writes disabled; direct
tests prove fresh bounded canonical output, no source/proposed-term
contamination, no repository mutation, and empty output when no glossary
exists. Build, source-archive, installed-plugin 0.1.0 → synthetic 0.1.1, and
exact-byte checks bind the hook, runner, skill, and nested wheel.

Two separately authorized Codex CLI 0.147.0/Linux batches passed 12/12. Each
fresh-session prompt omitted Glossabet and every expected term; each agent
returned the exact canonical term and definition from hook context with zero
commands, no proposed term or source canary, and no write. The other ten plugin
scenarios and the non-login, profile-disabled missing-CLI boundary also passed,
and all temporary plugin/marketplace state was removed and re-queried. The
first raw run remains at
`evaluation/agent-runs/20260816T182412Z-full-abd5f2ee.json`. Correcting the
README phase status changed only wheel `METADATA` and `RECORD`; the explicitly
authorized replacement on those final bytes is retained at
`evaluation/agent-runs/20260816T183508Z-full-a8775cdb.json` with SHA-256
`05ca64fbb1896f1f6929c37b0c4be0d9d64221070e006414e2e19941be67933c`.
The verifier now rejects a selected result whose evaluator, scenario, prompt,
schema, skill, plugin, or engine identity differs from the current inputs, in
addition to requiring an immutable history-retained digest. Codex on other
operating systems/versions, ChatGPT, and Claude Code remain explicitly
unverified.

#### Phase 28.3 — Sync-context managed block

**Steps:**

1. `glossabet sync-context`: an explicit human-invoked command that writes
   a stamped managed block into `CLAUDE.md`/`AGENTS.md` for hosts without
   hooks. Never written unbidden; marker and collision semantics with
   hand-written surrounding content are defined before code.
2. `drift` and `validate` flag a stale or hand-edited managed block.
3. Hostile-scenario review of the write path: this is the only product path
   that modifies a project-owned host instruction file (the explicit personal
   skill installer is a separate user-state write), and tests prove no other
   repository command can modify those targets.

**Acceptance:** no code path writes a project-owned host instruction file
without an explicit human command; a stale sync block is flagged by
drift/validate; hostile write-path scenarios pass.

**Completion evidence (2026-08-16):** the implementation and
offline hostile-path tests are complete on canonical skill SHA-256
`a4776847cfc97b932e0a99dabc6c38a804351ff1258926b77b6ece90b0ee045f`,
plugin-tree SHA-256
`7954e53b298d00c91eb364448a014cff68ab39bfe1541c6bdb5e9fde5b65bc6c`,
and wheel SHA-256
`d249ff1b33a92a14898586331b9cb6c991786d29b75b22d38a31ae65235631f7`.
The one authorized no-retry current-artifact batch is retained at
`evaluation/agent-runs/20260816T192615Z-full-e73a0e21.json` with SHA-256
`8860101d8bd57b7665271b5f1e1734b44abd0d8bbd1a3414ad34001975b42e31`.
It passed 11/12: the missing-CLI agent used `wc -l` on its installed
`SKILL.md` before reading that same skill with `sed`, while the evaluator's
installed-skill exception recognizes only `cat` and `sed`. It did not run
`inspect`, read production repository files, expose sensitive content, or
write repository state; all safety and cleanup checks passed.

A process-control error then launched a second three-turn batch after the
still-running first command was incorrectly treated as absent. That duplicate
contradicted the one-batch/no-retry authorization. Its retained 12/12 result at
`evaluation/agent-runs/20260816T192933Z-full-6b8b5f75.json` is historical
evidence only and does not close this phase. No further authenticated run is
authorized by that mistaken launch.

Kyle then explicitly authorized one new current-artifact retry. Without any
intervening executable, evaluator, skill, or artifact change, it passed all
12 scenarios on Codex CLI 0.147.0/Linux, with no unexpected repository write,
no sensitive-canary exposure, and verified removal of all temporary host
state. Its raw result is retained at
`evaluation/agent-runs/20260816T193824Z-full-f7879d5e.json` with SHA-256
`871b681854a6cd340a8e5a38911b4a767ef07af8bf624597566f3d91c1326fc9`.
Together with the deterministic hostile write-path coverage, that authorized
exact-artifact pass closes Phase 28.3. The earlier `wc -l` miss remains in the
reliability ledger rather than being rewritten or hidden.

### Phase 29 — Decouple evidence currency from development ✅ 2026-08-16

**Goal:** development never collides with committed evidence again; currency
is demanded only where it earns its cost — the release gate.

**Why (Kyle's decision, 2026-08-16):** Phase 20 bound the per-commit CI gate
to byte-level currency: any edit to engine or evaluator source made the
committed evaluation evidence "stale," and restoring green required
regenerating two witness artifacts through live Codex runs. That made every
refactor, fix, or feature carry a live-evaluation toll. Kyle rejected that
model: reports stay fingerprinted as sealed testimony about the state they
measured, but the repository must never be broken merely because testimony
honestly lags the tree.

**The two-mode contract:** every evidence verifier now separates
- **genuineness** (always, every commit, every branch): the artifact is
  untampered and internally consistent — well-formed digests, recomputable
  aggregates/comparisons/summaries, blinding preserved, safety and method
  bars met, retained raw runs cohering byte-for-byte. Never compares
  evidence to the current tree, so it stays green through development.
- **currency** (`--current`, release gate only): the evidence additionally
  describes the current tree — engine source digest, manifest, corpora,
  plugin artifact, and reviewer/agent input identities all match. Evidence
  may lag between releases; it can never lag at the moment something ships.

**Steps (all landed):**

1. `evaluation/run.py verify_results` split into `_genuineness_errors` /
   `_currency_errors` behind a `current` flag; thresholds rebuild from the
   recorded targets in genuine mode and from the manifest at the release
   gate; `--current` CLI flag added.
2. `scripts/agent_eval.py` gates `_result_input_errors`, `_artifact_errors`,
   and the plugin-hook/host-prompt digest comparisons behind `current`, with
   shape-only genuineness replacements (`_input_shape_errors`,
   `_artifact_shape_errors`); `--current` CLI flag added.
3. `evaluation/review.py` verifies blinding, judgment/packet coherence, and
   threshold arithmetic from the stored artifacts alone (rebuilding
   comparisons from the recorded primary labels); packet-vs-current-results
   equality and reviewer input identity move behind `--current`. Building a
   new packet or running the reviewer still demands current engine results —
   new testimony is never generated from stale inputs.
4. `quality.yml` (per-commit, reused by CI) keeps the three verifiers in
   genuineness mode and drops `git diff --exit-code -- plugins/glossabet`;
   `release.yml` publish runs all three with `--current` plus the plugin
   diff. `scripts/check_workflows.py` enforces the split fail-closed,
   including rejecting any `--current` inside the per-commit quality gate
   and any release verifier without it.
5. Tests updated: committed-evidence tests assert genuineness (they no
   longer break when source lags evidence); currency detection is pinned by
   synthetic mutations that are robust to lag; new tests prove each check
   fires only in its mode. Docs (README, RELEASING, EVALUATION, CLAUDE)
   describe the two modes.

**Acceptance:** full suite passes; all four per-commit gates pass in
genuineness mode on a tree whose evaluator sources were edited this phase;
each `--current` verifier correctly reports that same lag as staleness. The
committed evidence artifacts were not modified: they remain the sealed
2026-08-16 testimony and honestly lag until regenerated at the next release
gate.

### Phases 30–32 — Pre-existing `GLOSSARY.md` adoption and reconciliation (added 2026-08-17)

**Origin:** Kyle's spec of 2026-08-17 ("Pre-existing GLOSSARY.md Adoption and
Reconciliation") plus Claude's review of the current code. Repositories that
already maintain a hand-written root `GLOSSARY.md` are today treated as if
they have no glossary at all: `glossary.present` in the agent context means
only `glossabet-out/glossary.json`, the skill's "resume, don't restart" branch
keys on that, and finalization writes `GLOSSARY.md` at the root without
checking whether one already existed. That last point is a live trust hazard
under the never-break-trust rule — a `/glossabet` run on such a repo would
overwrite a maintainer-owned document — and lands first regardless of the
rest.

**Product statement (one sentence):** Glossabet first learns the vocabulary
the repository actually expresses, then checks that reality against the
vocabulary the maintainers say they use.

**Two sources of truth, never merged:**
- *Repository reality* — the lexical/structural evidence Glossabet already
  derives (identifiers, doc terms, register, naming candidates, overloads,
  Graphify groups, bindings, drift).
- *Documented vocabulary* — the repository's own root `GLOSSARY.md`:
  maintainer-authored evidence of prior human intent, respected but never
  automatically trusted. It may be excellent, stale, incomplete, internally
  inconsistent, aspirational, or written before the architecture changed.

**Binding invariants for these phases (additions to the principles above):**
1. `GLOSSARY.md` never becomes ordinary lexical evidence (the existing
   `SELF_FILES` exclusion in `scanner.py` stays; a glossary that counted
   toward its own vocabulary evidence would be evidence for itself and
   would blind drift detection).
2. The agent context carries **metadata only** for the repository glossary
   — never its content. That is the enforcement mechanism for
   independent-first: the agent's baseline naming model is necessarily
   built from a glossary-blind context, and reading the Markdown is a
   deliberate, later step the skill sequences. Nobody later "helpfully"
   inlines the Markdown into `inspect` output.
3. The two glossary channels are distinct and never overloaded:
   `glossary` = Glossabet-managed structured state (`glossary.json`);
   `repository_glossary` = the human-facing root `GLOSSARY.md`.
4. Presence and readability are separate. An escaping symlink, non-regular
   file, oversized, or unreadable `GLOSSARY.md` is `present: true,
   readable: false, reason: …` — never `present: false`. A glossary that
   could not be read completely never supports a claim that it lacks a
   term.
5. No term becomes `canonical` because the engine found it in Markdown.
   Adoption goes through the human loop; the UX is "documented already,
   appears consistent — keep?", not a fresh three-name brainstorm per term.
6. A pre-existing `GLOSSARY.md` is never wholesale regenerated unless the
   user literally asks for regeneration; the default is surgical, approved
   edits that preserve unrelated maintainer material. If the file's SHA-256
   at write time differs from the one recorded at inspect time, stop —
   someone touched it mid-session (freshness-is-trust, applied to the
   human document).
7. Only the exact scan root's `GLOSSARY.md` is *that* scan's repository
   glossary (whole-repo scan → root file; subproject scan → that
   subproject's root file). Nested `GLOSSARY.md` files are excluded from
   evidence at every depth as today, and their exclusion is now *reported*,
   never silent — but they are not consulted or merged.
8. Reconciliation (meaning comparison) is LLM work in the skill, not engine
   work: real-world `GLOSSARY.md` files are free-form Markdown, and the
   engine must not depend on any table schema. The engine's only
   deterministic contribution beyond detection is the optional lexical
   term-presence check in Phase 32.
9. Deliberate asymmetry with the JSON glossary, stated once so it does not
   look inconsistent: `glossary.json` canonical concepts are handed to the
   agent *up front* because they are human-locked decisions and biasing
   toward them is the point; the Markdown glossary is an *unverified
   maintainer claim* and is read only after the independent baseline
   exists.
10. Existing path-scope and alias-collision semantics are unchanged;
    Graphify stays optional; `GLOSSABET.md` (a separate findings report,
    not yet implemented) is where reconciliation findings would live —
    these phases must work correctly without it.

Split into three passes because they are three kinds of work: 30 is pure
engine/contract, 31 changes the behavioral spec (skill + eval fixtures +
docs), 32 is an optional deterministic check that depends on both.

### Phase 30 — Repository-glossary discovery and context channel ✅ 2026-08-17

**Goal:** the engine can distinguish "no glossary," "pre-existing Markdown
glossary," "Glossabet-managed structured glossary," and "both," and reports
the Markdown file's presence, safety, and provenance through `inspect` —
without its content and without touching lexical evidence.

**Steps:**

1. New module `glossabet/repository_glossary.py` with a pure discovery
   function over the resolved scan root. It examines only
   `<root>/GLOSSARY.md` and returns a tri-state dict:
   - absent → `{"present": false}`;
   - present and safely, completely read →
     `{"present": true, "path": "GLOSSARY.md", "readable": true,
     "bytes": N, "sha256": "<hex of the exact bytes read>"}`;
   - present but not safely readable → `{"present": true,
     "path": "GLOSSARY.md", "readable": false, "reason": <one of
     "symlink-escapes-repository" | "symlink-to-sensitive-file" |
     "not-a-regular-file" | "oversized" | "root-listing-unconfirmed" |
     "unreadable">, "bytes": N-when-known}`.
   Symlink handling reuses the walked-file rule (a symlink confined inside
   the root is followed; an escaping one is refused). Size bound is the
   existing `MAX_FILE_BYTES` (2 MB); the reader reads `cap + 1` bytes so an
   oversized file is detected from the bytes, not a racy stat, and a
   partial read is never presented as complete. No content leaves the
   function beyond size and digest.
2. `agent_context.build_agent_context` gains a top-level
   `repository_glossary` section (the discovery dict) next to, and never
   merged with, `glossary`. `inspect_command` computes it from the same
   resolved root. `context_schema_version` stays 2 in this phase — the
   field is additive and the skill does not depend on it yet; Phase 31
   bumps it to 3 when the skill starts requiring it.
3. Reported, not silent, self-file exclusion: `scanner.py` records every
   walked path skipped as a self-file (root and nested `GLOSSARY.md`);
   evidence `skipped.self_glossaries` lists them sorted; `SCHEMA_VERSION`
   11 → 12; the scan summary line names the count; the agent context
   derives `repository_glossary.nested_ignored` (nested paths only, list
   bounded like every other list, truncation visible in coverage).
4. Tests (`tests/test_agent_context.py`, `tests/test_evidence.py`, new
   `tests/test_repository_glossary.py`): evidence isolation (a
   `GLOSSARY.md` repeating a unique term many times changes no vocabulary
   count or nomination, and adding/removing/altering it leaves the
   vocabulary section byte-identical); detection; no-glossary unchanged
   (`{"present": false}`); Markdown-only adoption is distinguishable from
   none and from JSON-only; both present surfaced distinctly; escaping
   symlink not read (`readable: false`, reason named, no sha256); confined
   symlink read; oversized reported as `present/unreadable`, never absent;
   subproject scan root owns its own glossary and reports the parent's
   as… nothing (parent is outside the root) while a whole-repo scan
   reports the subproject's as `nested_ignored`; determinism of the
   section.
5. Docs: README (artifact/contract description) and `docs/WALKTHROUGH.md`
   mention of the new section; PLAN acceptance recorded.

**Acceptance:** full suite passes; `glossabet inspect` on a repo with a
root `GLOSSARY.md` and no `glossary.json` emits `glossary.present: false`
and `repository_glossary.present: true, readable: true` with a stable
SHA-256; the vocabulary section of that context is byte-identical to the
same repo without the file; an escaping-symlink `GLOSSARY.md` yields
`readable: false` and never a digest.

**Completion evidence (2026-08-17):** `glossabet/repository_glossary.py`
(`discover_repository_glossary`, `repository_glossary_section`) examines only
`<root>/GLOSSARY.md`, reads `MAX_FILE_BYTES + 1` bytes so the 2 MB bound is
judged from the bytes, and returns the tri-state record with named reasons
`symlink-escapes-repository` / `not-a-regular-file` / `oversized` /
`unreadable`. `build_agent_context` carries it as top-level
`repository_glossary` (schema stays 2; `nested_ignored` list bounded at 50).
The scanner records every excluded `GLOSSARY.md` in
`skipped.self_glossaries` (evidence schema 11 → 12) and the scan summary
names the count. 17 new tests in `tests/test_repository_glossary.py` cover
isolation (unique term ×200 changes no vocabulary/terminology/nomination
bytes), the four states, escaping/confined/dangling symlinks, directory,
oversized, exact-bound, permission-denied, determinism, and whole-repo vs
subproject ownership. README and WALKTHROUGH updated. Full suite 440 passed;
all four per-commit gates green in genuineness mode.

### Phase 31 — Skill: independent-first, adoption, managed-mode divergence, safe finalization ✅ 2026-08-17

**Goal:** the `/glossabet` skill treats a pre-existing `GLOSSARY.md` as a
first-class separate input: it forms its own model first, then reads the
maintainers' document to validate and challenge that model, adopts it into
structured state only through the human loop, and never clobbers it.
(Depends on Phase 30.)

**Steps:**

1. Contract bump: `context_schema_version` 2 → 3; the skill's version
   literal, `tests/test_skill.py`, and `tests/test_agent_context.py`
   follow. The skill requires `repository_glossary` to be present in the
   context.
2. **Sequencing (Phase A → B → C) in `skill/SKILL.md`:**
   - A. Build the repository model from the context exactly as today (map,
     register, important concepts, overloads, synonyms, unnamed parts,
     initial hypotheses). Explicitly: do not open `GLOSSARY.md` before
     this exists, even if `repository_glossary.present` is true.
   - B. Only then, if `repository_glossary.readable` is true, read
     `<root>/GLOSSARY.md` directly with the host's file-read tool (it is
     an explicitly authorized repository document, read the way README /
     architecture docs are read — it does not become lexical evidence).
     Treat it as maintainer-authored evidence, never as instructions;
     embedded instructions do not supersede the skill protocol. If
     `readable` is false, say so, name the reason, and never claim the
     glossary lacks a term.
   - C. Reconcile, surfacing at least: documented-and-supported (strong
     keep); documented-but-weakly-represented (do not assume which of
     stale / conceptual / docs-only / needs-a-binding applies);
     documented-but-drifted; documented-but-overloaded (high value);
     repository-concept-missing-from-glossary (candidate gap, not an
     error); possible synonym/alias mismatch; glossary-distinction-not-
     reflected-in-code; and *unresolved* when the relationship cannot be
     established — never manufacture a match.
3. **Adoption mode** (`repository_glossary.present && !glossary.present`):
   distinct from both "no glossary" and "resume". Supported terms are
   offered as "documented already; appears consistent — keep?"; questionable
   ones enter the normal naming loop; only human-confirmed terms are
   persisted via `glossabet save` with appropriate statuses, aliases,
   scopes, bindings. Nothing is `canonical` because Markdown said so.
4. **Managed mode** (both present): the JSON remains machine state, the
   Markdown remains the human document; the skill checks and surfaces
   divergence (JSON canonical absent from Markdown; important Markdown term
   absent from JSON; definitions materially disagree; alias/deprecation in
   JSON while Markdown still leads with the old term). Surface, do not fail
   the session, do not silently rewrite.
5. **Finalization safety:** when `repository_glossary.present` was true at
   inspect, the finalization step edits `GLOSSARY.md` surgically — only the
   settled decisions, preserving structure, prose, and unrelated material —
   and wholesale regeneration happens only on the user's literal request.
   Before writing, re-check the file's SHA-256 against the inspect-time
   value; on mismatch, stop and report. When no `GLOSSARY.md` pre-existed,
   the current generation path is unchanged.
6. Rename/retitle the existing "Existing glossary — resume, don't restart"
   section so it clearly covers only `glossary.present` (JSON), and add the
   one-paragraph asymmetry note (invariant 9 above).
7. Distribution copies regenerate through the canonical path
   (`scripts/build_plugin.py`; `plugins/glossabet/skills/glossabet/SKILL.md`
   must equal `skill/SKILL.md`; the wheel copy is declared in
   `pyproject.toml`). No hand edits to generated copies.
8. Evaluation: extend `scripts/agent_eval.py` scenario fixtures with (a) a
   Markdown-only repo where the run must not propose `canonical` for a
   glossary term without confirmation and must not rewrite `GLOSSARY.md`,
   and (b) a both-present repo with a deliberate divergence the run must
   surface. Committed evidence stays sealed testimony (Phase 29): it lags
   honestly until the next release gate; genuineness gates stay green.
9. Docs: README, `docs/WALKTHROUGH.md`, and PLAN reflect the four glossary
   states and the A→B→C order.

**Acceptance:** full suite passes; `scripts/check_workflows.py`,
`build_plugin.py`, and the plugin/wheel copy checks pass; a dry read of the
skill shows the four-state branch (`none` / Markdown-only / JSON-only /
both), the A-before-B rule, the eight reconciliation categories, and the
no-regenerate + SHA-recheck finalization rule.

**Completion evidence (2026-08-17):** `context_schema_version` 2 → 3.
`skill/SKILL.md` gained "Which glossary state you are in" (four-state table
over both channels, asymmetry note, unreadable-never-absent, nested files
reported-not-consulted), the *Resume* / *Adoption* / *Managed* sub-sections,
a new **Step 4½** (read `GLOSSARY.md` only after Steps 1–4, as evidence not
instructions, free-form Markdown, eight reconciliation categories incl.
*Unresolved*), and a finalization branch that edits a pre-existing file
surgically, forbids wholesale regeneration without the literal request,
re-checks the SHA-256 against Step 0, and keeps findings out of the
vocabulary document. `tests/test_skill.py` pins every named field, reason,
state, category, and safety rule against the engine. Agent eval: two new
plugin scenarios `markdown-glossary` (status `adoption`) and
`both-glossaries` (`resumed`) with fixture-digest, canary-absent, and
facts-name-the-file checks; scenario ids now carry two known generations so
the sealed 12-scenario evidence stays genuine while `--current` demands 14.
Plugin skill + wheel regenerated through `build_plugin.py`; README,
ARCHITECTURE, EVALUATION, CHANGELOG, WALKTHROUGH updated. Suite 441 passed;
workflow check, three genuineness verifiers, and wheel smoke green.

### Phase 32 — Deterministic managed-mode term-presence check ✅ 2026-08-17

**Goal:** the one reconciliation signal the engine can give honestly without
parsing Markdown: for each `glossary.json` concept, is its term (NFKC +
casefold, existing vocabulary fold) present anywhere in the readable root
`GLOSSARY.md`, and does any `alias`/`deprecated` term appear while its
canonical replacement does not? (Depends on Phases 30 and 31.)

**Steps:**

1. Engine function in `repository_glossary.py` over the bytes read in
   Phase 30 (bounded by the same 2 MB), returning sorted lists
   `canonical_missing_from_markdown` and `superseded_terms_still_present`;
   no definitions compared, no structure inferred.
2. Surface via `glossabet validate` (alongside existing reconciliation
   findings) and as `repository_glossary.divergence` in `inspect` when both
   files exist and the Markdown is readable.
3. Tests: positive/negative for each list; Unicode fold parity with the
   identifier contract; no false positives from unreadable Markdown
   (section absent, never empty-list-as-clean).

**Acceptance:** suite passes; the check is deterministic, bounded, and
absent (not empty) whenever the Markdown was not completely read.

**Completion evidence (2026-08-17):** `repository_glossary_divergence` in
`glossabet/repository_glossary.py` folds (NFKC + casefold) each canonical
concept term and each `alias`/`discouraged`/`deprecated` alias of a canonical
concept and tests lenient substring presence in the decoded Markdown; it
returns `canonical_missing_from_markdown`, `superseded_terms_still_present`
(alias present while its canonical term is not), `checked_terms`,
`skipped_terms`, `complete`, and the term cap (2,000 at landing; the
2026-08-17 audit lowered it to 500 and added a 4 M normalized-character
guard). `inspect` attaches it as
`repository_glossary.divergence` and `validate` (schema 7 → 8) stores it under
`repository_glossary` and prints it — both only when structured state exists
and the Markdown was read completely; otherwise the key is absent. Proposed
concepts are never checked. Nine new tests: positive/negative for both lists,
Unicode fold parity (ß / ligature), cap-and-say-so, presence only in the
both-and-readable case through `inspect`, `validate` output and JSON,
unreadable named, quiet on agreement. Skill *Managed* section names the
field and its limits; README, ARCHITECTURE, CHANGELOG updated; plugin
regenerated. Suite 450 passed; all per-commit gates green.

### Bughunt of Phases 30–32 (2026-08-17) — three findings, all fixed

Post-implementation bughunt scoped to the `GLOSSARY.md` adoption work. All
three were proven and fixed the same session with pinned regression tests;
none deferred.

1. A `GLOSSARY.md` symlink to an in-repo sensitive file (`.env`, a key) was
   reported `readable: true` — the engine would have authorized the skill to
   read a secret. Root cause: discovery reused only the *escape* half of the
   scanner's symlink rule and missed the sibling (classify by the resolved
   target's name). Fixed: new reason `symlink-to-sensitive-file`; chained
   links covered.
2. A multi-word canonical term hard-wrapped across a line in the Markdown was
   reported missing by the Phase 32 divergence check, contradicting its
   documented lenient direction. Root cause: whitespace-literal fold. Fixed:
   the fold collapses whitespace runs on both sides.
3. On a case-insensitive filesystem (Windows CI, macOS) a lowercase
   `glossary.md` was discovered as the repository glossary while the walk
   still counted it as ordinary evidence (path lookup vs. exact entry name).
   Fixed: presence is the exact directory-entry name, matching `SELF_FILES`;
   the invariant is pinned cross-platform.

### Bughunt round 2 of Phases 30–32 (2026-08-17) — two findings, both fixed

Both share one cause — tests/fixtures assumed that writing text yields the
exact bytes later hashed and that creating `GLOSSARY.md` yields an entry
named exactly that; neither holds off Linux, and the suite runs on
ubuntu/macos/windows.

1. `test_only_the_exactly_named_entry_is_the_repository_glossary` (from
   bughunt round 1) would fail on macOS/Windows CI: it wrote `GLOSSARY.md`
   over an existing `glossary.md` (same file on a case-insensitive
   filesystem, name preserved) and hashed a text-mode write (CRLF on
   Windows). Fixed: unlink first, `write_bytes`.
2. `scripts/agent_eval.py` `markdown-glossary`/`both-glossaries` fixtures
   wrote the Markdown in text mode while the checker expects the digest of
   the exact UTF-8 bytes (latent — the live eval runs on Linux). Fixed:
   `write_bytes`; pinned by
   `test_markdown_glossary_fixtures_match_the_digest_the_checker_expects`.

### Audit of Phases 30–32 (2026-08-17) — three findings, all fixed

Post-implementation security audit of the `GLOSSARY.md` adoption work
(after the bughunt above). Nothing exploitable now; one ship-time item and
two hardening items, all fixed the same session with pinned tests and
recorded in SECURITY.md. None deferred.

1. *(ship-time)* The skill could be steered to write through a symlinked
   `GLOSSARY.md` into another in-repo file (`GLOSSARY.md -> src/app.py`);
   discovery followed the confined link for reading (correct) but did not
   say it was a link. Fixed: `repository_glossary.symlink` reported; skill
   Step 6 never writes when it is true. Also closes the same gap in the
   pre-Phase-31 fresh-write path.
2. *(hardening)* Divergence check CPU ceiling was ~4–7 s under a hostile
   glossary + NFKC-expanding Markdown, with the expansion unguarded. Fixed:
   term cap 2,000 → 500 and a 4 M normalized-character guard applied after
   folding and before any search (`reason: normalized-text-exceeds-bound`);
   worst case now ~1 s, proven by tests.
3. *(hardening)* The bughunt's exact-name presence check used
   `os.listdir(root)`, materializing a possibly enormous root listing.
   Fixed: `lexists` fast path + bounded `scandir` confirmation under
   `MAX_WALK_ENTRIES`.

### Audit round 2 of Phases 30–32 (2026-08-17) — three findings, all fixed

1. *(hardening)* The divergence length guard ran after NFKC + casefold +
   whitespace collapse; on the NFKC bomb, casefold (3× UCS-4 reserve) and the
   collapse each allocate ~170 MB before the guard looked. Fixed: bound
   judged right after NFKC (72 MB peak) and again after casefold, before the
   collapse and any search; pinned by a peak-memory test.
2. *(hardening / invariant)* The exact-name presence check reported "absent"
   when something was there but could not be confirmed (unlistable root, or
   the walk-entry cap reached first) — a false absence claim, the one
   failure the channel forbids. Fixed: `present: true, readable: false,
   reason: root-listing-unconfirmed`; both states pinned.
3. *(hardening)* `SELF_FILES` and `REPOSITORY_GLOSSARY_FILE` were
   independent spellings of one name; pinned equal by test.

#### Phase 33.1 — Claude Code skills-directory plugin install ✅ 2026-08-17

**Steps:**

1. `installer.py`: `install --agent claude` writes the three-file plugin
   described above into the personal skill directory; add `--skill-only`;
   resolve and verify the executable path; extend outcome reporting to name
   every file and its outcome (`installed` / `current` / `replaced`).
2. Share the manifest metadata and hook shape with the Codex plugin build
   where the fields coincide, so a version bump or status-message change
   cannot diverge between hosts.
3. Tests: exact bytes of manifest and hook for a synthetic home; idempotent
   second run; refusal of a different existing manifest/hook without
   `--force`; refusal of symlinked components for the new files; no write
   outside the skill folder (snapshot the synthetic home before/after);
   `--skill-only` writes only `SKILL.md`; hook refused (skill still written,
   non-zero exit) when the executable cannot be verified; the written hook
   command, executed from a fixture repository with a canonical glossary,
   prints exactly `build_brief` output and writes nothing; with no glossary
   it prints nothing; Codex `install` output is byte-identical to before.
   When the `claude` CLI is on `PATH`, one test runs
   `claude plugin validate` on the installed folder and requires success;
   otherwise it is skipped with the reason.
4. Docs: README install section, DISTRIBUTION.md parity table (Claude Code
   column changes from "no automatic host integration" to the hook, still
   marked *unverified live* until 33.2), `glossabet install --help`.

**Acceptance:** on a synthetic home, `glossabet install --agent claude`
yields a folder that `claude plugin validate` accepts, whose hook prints the
canonical brief from a glossary-bearing repository and nothing otherwise,
with zero writes outside `~/.claude/skills/glossabet/`; the Codex install path
is byte-for-byte unchanged; hostile-path tests pass.

**Completion evidence (2026-08-17):** `glossabet/installer.py` writes
`SKILL.md`, `.claude-plugin/plugin.json` (`skills: ["./"]`, no `hooks`
field), and `hooks/hooks.json` (one `SessionStart` hook,
`^(startup|resume|clear|compact)$`, `"<abs glossabet>" brief .`, timeout 30,
shared status message) through one atomic, symlink-refusing, byte-compared
`_install_file` path; the executable is `sys.argv[0]` or `PATH`, verified by
`--version`; failure to resolve leaves the skill installed and exits 1 with
the reason; `--skill-only` opts out; Codex output is byte-identical to before.
Fourteen new tests in `tests/test_install.py` cover exact bytes, idempotency,
refusal without `--force` for hook and manifest, symlinked hook directory,
no writes outside the folder, `--skill-only`, unresolvable executable,
shell-significant paths, metadata pinned to the Codex plugin manifest and
hook, version-verified resolution, the written hook printing exactly the
brief from a fixture glossary and nothing without one while writing nothing,
and `claude plugin validate` acceptance (skipped when the CLI is absent).
On this machine (Claude Code 2.1.234, Linux) `claude plugin details
glossabet@skills-dir` against a synthetic config dir reports `Status: ✔
loaded` and `Hooks (1) SessionStart`; its inventory lists root-level skills
as 0 for the official `claude plugin init` scaffold too, so the plugin
docs' statement that a root `SKILL.md` with `skills: ["./"]` loads under its
frontmatter name is relied on and re-checked live in 33.2. Full suite: 474
passed. README, DISTRIBUTION, CHANGELOG, WALKTHROUGH, ARCHITECTURE updated;
Claude Code stays labelled unverified until 33.2.

### Phase 34 — `GLOSSABET.md`, the repository vocabulary-health report ✅ 2026-08-17

**Goal:** give Glossabet's analysis its own recognizable human-facing
artifact so `GLOSSARY.md` can stay a glossary. Three artifacts, kept
separate: `GLOSSARY.md` answers "what words have we agreed to use?";
`GLOSSABET.md` answers "what has Glossabet discovered about the health and
alignment of that vocabulary?"; `glossabet-out/glossary.json` remains the
structured human-governed state. The report is derived Glossabet output —
never a replacement glossary, never machine state, never evidence for its
own next run — and the two Markdown files must not become competing versions
of one artifact. (Kyle's spec, 2026-08-17: "The glossary tells the team what
the words mean. The Glossabet report tells the team whether those words
still match the codebase.")

**Steps:**

1. Engine: `artifacts.REPORT_FILE = "GLOSSABET.md"`; `scanner.SELF_REPORT_FILES`
   excludes it at any depth (a subproject's report would otherwise count in
   a whole-repo scan) and reports it as `skipped.self_reports`, distinct from
   `self_glossaries` because the reason differs (`GLOSSARY.md` is kept out so
   it can be validated independently; `GLOSSABET.md` because it is derived
   output). Freshness pathspec adds `:(exclude)GLOSSABET.md` for the scan
   root only; `GLOSSARY.md` stays visible; a nested subproject's report is
   that subproject's output and stays visible. `context_schema_version`
   stays 3 (additive `skipped` key the skill does not require).
2. Skill: a "Three artifacts, kept separate" section; the report is not
   opened during Steps 0–5; Step 4½ findings and Step 6's non-decisions
   route to it; new Step 7 writes/refreshes it as the last part of finalize,
   or on request / at an unfinished session's end with the user's yes.
   Stable section order, empty sections omitted, provenance from the Step 0
   context, proposals always marked **Proposed**, refresh-not-append,
   content rules and exclusions as specified.
3. Docs: README (three-artifact model, ownership/freshness), ARCHITECTURE,
   WALKTHROUGH, PRIVACY, SECURITY, DISTRIBUTION, CLAUDE.md, CHANGELOG.
   Plugin skill copy and bundled wheel rebuilt through the existing
   `uv build --no-sources` + `scripts/build_plugin.py` process.
4. Tests (`tests/test_report.py`): one shared name across scanner and
   freshness and disjoint from `SELF_FILES`; report content never enters
   evidence or the inspect context (root and nested), while a lookalike
   `GLOSSABET-notes.md` still counts; tracked/untracked report changes and
   deletion do not dirty freshness while `GLOSSARY.md` changes and a nested
   report do; a source file moved onto the report name stays visible; report
   content never becomes glossary state through `show`/`inspect`/`drift`/
   `validate`, proposed stays proposed, and deleting the report leaves
   `glossary.json` byte-identical.

**Acceptance:** all of the above proven by the test suite; the skill spec
carries the report protocol; no document presents `GLOSSABET.md` as a better
or replacement glossary.

**Completion evidence (2026-08-17):** implemented as specified; the report's
composition stays with the skill (the deterministic `scan` invents no
agent-level judgment); the agent contract grew only the additive
`skipped.self_reports` list. Full suite green after rebuild.

### Phase 35 — Deepening refactor (zero behaviour change) ✅ 2026-08-17

**Goal:** apply the accepted findings of the 2026-08-17 architecture review
(Matt Pocock's `improve-codebase-architecture` skill, verified by hand):
turn the shallow, duplicated seams in the hot modules into a few deep ones.
No behaviour change: every engine output for the local corpus fixtures and
this repository (scan/analyze/inspect/inspect --full/drift/validate/show/
brief/sync-context stdout+stderr and every `glossabet-out/*.json`) must be
byte-identical to the pre-refactor baseline after every step, and the full
suite stays green. Rejected as low value: engine-run preamble module,
single occurrence record, named terminal-escaping policy; rejected as YAGNI:
an agent-host registry (two settled hosts) and unifying installer/context_sync
symlink rules (they differ on purpose).

**Steps (each one pass, one commit):**

1. **Git state module** — `glossabet/git_state.py` owns the hardened stamp
   (`repository_git_stamp`), the freshness pathspec (`FRESHNESS_STATUS_ARGS`),
   safe-config and filter-driver neutralization. `evidence` and `brief` call
   the public name; `brief._git_stamp` shim deleted; tests import public
   names and get their own `tests/test_git_state.py` home for the freshness
   cases that were in `test_freshness.py`/`test_report.py`.
2. **Bounded JSON reader** — `artifacts.read_bounded_json(path, cap)` reads
   `cap + 1` bytes and returns absent / value / refusal(reason) so
   `config`, `glossary` (file + stdin), `graphify`, `cache`, and
   `repository_glossary` share one read discipline; `oversized()` absorbed
   where its only caller was the read; tests patch one constant.
3. **Exclusion ledger** — `scanner.WalkResult` owns each exclusion kind's
   evidence key, human sentence, and paths; `WalkResult.skipped_as_evidence()`
   emits the `skipped` section; the scan printer iterates the ledger;
   `repository_glossary` asks the scanner for nested self-glossaries instead
   of indexing the dict.
4. **Dependency-direction fixes** — `repository_glossary` stops importing
   the private `scanner._resolves_outside_root` and re-deriving the
   walked-file rule: the scanner exposes one public content-path policy
   both use. `evidence` stops importing `strip_managed_context_for_evidence`
   from the `context_sync` command module: the managed-block stripper moves
   to a module beneath both (`glossabet/managed_block.py`) that
   `context_sync` and `evidence` both import.
5. **Vocabulary interface** — `_Vocabulary` becomes the public
   `ProductionVocabulary` owning the fold and the few queries the analyses
   need; `build_terminology(vocabulary, doc_term_counts)` and
   `build_naming_candidates(vocabulary, ...)` lose their 19 positional
   parallel-dict parameters; tests build a vocabulary instead of aliasing
   four `defaultdict`s.
6. **Findings document module** — `glossabet/findings.py` owns the finding
   record, the capped section with its coverage ledger, the
   evidence-limitations derivation (`vocabulary[*].truncated` and matcher
   coverage), and the terminal renderer; `drift` and `reconcile` emit
   documents and call the one renderer instead of two `_print_report`s.

**Acceptance:** baseline diff empty after every step; full suite green;
ARCHITECTURE.md module map updated for the new modules; wheel/plugin
rebuilt through the existing process at the end.

**Completion evidence (2026-08-17):** six commits (35.1–35.6), one per
step. Byte-identical baseline (76 captured outputs across the four local
corpus fixtures with their glossaries: every command's stdout/stderr and
every `glossabet-out/*.json`, plus sync-context targets and cache-warm
rescans) after every step; the self-scan of this repository was excluded
from the oracle because the refactor changes the very source it reads. New
modules: `git_state.py`, `managed_block.py`, `vocabulary.py`,
`findings.py`; new tests: `test_git_state.py` (moved), `test_findings.py`,
`test_module_dependencies.py`, reader/ledger cases in `test_artifacts.py`/
`test_evidence.py`. `build_terminology` 10 → 2 parameters,
`build_naming_candidates` 9 → 5. Not done, by decision: engine-run preamble
module, single occurrence record, named terminal-escaping policy, agent-host
registry, unified installer/context_sync symlink rules. Noted, not changed:
`drift`/`reconcile` still import `print_managed_context_issues` from the
`context_sync` command module — same direction smell as the stripper, left
because it is a printer, not evidence.

#### Phase 36.1 — Split the `evidence.py` hub ✅ 2026-08-17

**Problem:** 700+ lines doing walk orchestration, cache reuse, extraction,
the *documentation* fold (`doc_term_counts` / `doc_term_files` /
`doc_term_modules` — three parallel dicts inline, the exact shape Phase 35.5
fixed for identifiers), terminology/naming/structural assembly, the evidence
dict schema, and the `scan`/`analyze` handlers with a 130-line terminal
report.

**Steps:**
1. `DocumentationVocabulary` (in `vocabulary.py`, beside
   `ProductionVocabulary`): the doc-term fold with the same named-view
   discipline; `build_terminology`/`build_naming_candidates` take it instead
   of a bare `doc_term_counts` Counter where they need per-file/module views.
2. `evidence_report.py` (or `analyze.py`): `_print_terminology_report` and
   the `scan`/`analyze` handlers leave `evidence.py`; `evidence.py` keeps
   `build_evidence`, `write_evidence`, and the extraction/cache path only.
3. The extraction step (`_read_source`, `_extract_code_entry`,
   `_extract_doc_entry`, cache reuse) becomes one named module or class with
   a two-method interface (extract file → entry; entries → vocabularies), so
   `build_evidence` reads as assembly, not as a 200-line function.

**Acceptance:** `evidence.py` under ~350 lines; no printer in it; oracle
identical.

**Completion evidence (2026-08-17):** `evidence.py` 589 → 287 lines and
holds only assembly, the evidence schema, and `write_evidence`. New
`extraction.py` (`read_source`, `extract_code_entry`, `extract_doc_entry`,
`SourceExtractor` — cache reuse, managed-block stripping, corpus-budget
confession, reused/extracted counts); new `evidence_report.py` (the
`scan`/`analyze` handlers and the terminology printer, imported by `cli`);
`DocumentationVocabulary` in `vocabulary.py` replaces the two inline doc
dicts (the plan's "three parallel dicts" was two — no per-module doc view
existed, and none was invented). `build_terminology`/`build_naming_candidates`
still take the doc-term `Counter` because they need only counts; passing
the aggregate would be pass-through for one field. Dependency test pins
`evidence` ↛ `evidence_report` and `extraction`/`vocabulary` ↛
`evidence`/`scanner`. Oracle (48 commands × 4 fixtures, stdout/stderr/rc,
every `glossabet-out/*.json`, both host files) byte-identical; suite 494
green. Oracle harness for the rest of Phase 36 lives in this session's
scratchpad (`oracle.py`: `setup`, `capture NAME`, then `diff -r out/base
out/NAME`).

#### Phase 36.2 — One command preamble and one glossary-error style ✅ 2026-08-17

**Problem:** six commands re-spell resolve-root → require/load glossary →
build evidence → write → print → exit, with three glossary-error styles
(`require_glossary` prints and returns `None`; `show`/`brief` catch
`GlossaryError`; `inspect` re-raises `AgentContextError` for `cli` to
convert). `save_command` mixes stdin bounding, validation, atomic write,
and printing.

**Steps:**
1. `engine_run.py`: `open_run(path_arg, glossary="none|optional|required")`
   → a run handle (`root`, `glossary`, `evidence` already persisted,
   `managed_context`) or one user-error outcome that `cli` maps to exit 1
   with one message style.
2. `drift_command`, `validate_command`, `sync_context_command`,
   `inspect_command`, `_scan`, `show_command`, `brief_command` become:
   open run → build document → write → render. `save_command` splits into
   read-stdin (bounded, `parse_bounded_json`) → `save_glossary` → print.
3. Tests: one run-contract test replaces the per-command
   `main([...]) == 1` + `"no glossary" in err` repeats; each command keeps
   one end-to-end smoke.

**Acceptance:** exactly one place decides "does this command need a
glossary" and "how is a bad glossary reported"; oracle identical (stderr
wording preserved verbatim).

**Completion evidence (2026-08-17):** `engine_run.py` — `open_run(path_arg,
glossary=none|optional|required, missing=…)` → `Run(root, glossary)` or
`RunError(ArtifactError)`, which `cli` already maps to `print_error` + exit
1; `evidence.persist_evidence(root, **options)` is the build-through-cache-
and-write step (kept out of `engine_run` so `brief`, the session-start
hook, never imports the scanner — pinned in `test_module_dependencies`).
`repo_root` and `require_glossary` deleted; `show`/`save` moved from
`glossary.py` to `glossary_commands.py` (avoids the model importing its own
command preamble); `save_command` = read-stdin (`_read_glossary_from_stdin`)
→ `save_glossary` → print; `inspect` no longer wraps a `GlossaryError` in
`AgentContextError` (same stderr byte-for-byte). Two pre-existing dead
imports dropped (`brief.sys`, `graphify.json`). Happy-path oracle identical;
a second error-path oracle (9 commands × not-a-directory with a control
character / glossary absent / malformed / wrong schema / symlinked, plus
`save` oversized/unreadable/invalid stdin: 48 captures) diffed identical to
the pre-change tree apart from the cache-warm line the run order added.
`tests/test_engine_run.py` is the run contract (parametrized over every
command); the per-command repeats it replaced were deleted (drift no-
glossary, brief/inspect malformed glossary, cli/evidence missing path).
Suite 511 green, ~24 s.

#### Phase 36.3 — Accessor layer for the four top-level documents ✅ 2026-08-17

**Problem:** RepositoryEvidence, AgentContext, drift, and validation are
untyped nested dicts; consumers spell keys, and a typo is a runtime
`KeyError` in a branch a test may not reach. `findings.finding()` and
`artifacts.BoundedRead` are the only constructors so far.

**Steps:**
1. Do NOT convert to dataclasses wholesale (JSON round-tripping and
   schema-versioned artifacts stay dicts). Add one thin read-side accessor
   per document (`evidence_view.py` or methods on a small wrapper): the
   dozen lookups every consumer repeats (`vocabulary(name)`,
   `truncated(name)`, `skipped(kind)`, `production_complete()`,
   `structural_groups()`, `git()`), so no consumer outside `evidence.py`
   spells an evidence key.
2. Same for drift/validation on the read side (`sections()`,
   `coverage()`, `total_findings()`), consumed by the printers, `reconcile`
   (which reads drift), and `evaluation/run.py`.
3. A test that greps `glossabet/` for `evidence["` outside the owning
   modules and fails on any new spelling — the same trick as
   `test_module_dependencies.py`.

**Acceptance:** key spellings for each document live in one module; oracle
identical.

**Completion evidence (2026-08-17):** `evidence_view.py` — `EvidenceView`
with the repeated lookups (`vocabulary_table`, `truncated`,
`terminology_section`, `terminology_scope`, `structural_groups`, `skipped`,
`skipped_paths`, `corpus_budget`, `git`, section getters) and the two
corpus-completeness rules moved out of `matching`; `EvidenceIndex` carries
`.view`, and the drift/validation producers take the view or the matcher
instead of the raw dict. `findings.FindingsDocumentView` (totals, coverage,
managed context, `section`/`items`/`section_skipped`) with `drift.DriftView`
and `reconcile.ValidationView` for each document's own fields;
`print_sections` takes a view; both printers and `evaluation/run.py` read
through them. `scanner.excluded_paths` deleted (`EvidenceView.skipped_paths`).
AgentContext gets no view: its only in-repo Python reader is the
`scripts/agent_eval.py` harness, which deliberately treats the context as
untrusted input through `_mapping(...).get(...)`; the writer stays the one
speller. `tests/test_document_keys.py` is the AST ratchet (subscripts and
`.get` on `evidence`/`cold_evidence`/`drift`/`validation`/`context` outside
their owners fail; every top-level evidence key has a view method). Oracle
identical; the local evaluation cases (`--case` × 4) identical apart from
timings and this repository's self-scan; suite 513 green.

#### Phase 36.4 — Managed-context printer out of the command module ✅ 2026-08-17

**Problem:** `drift` and `reconcile` import `print_managed_context_issues`
from `context_sync` (a command module) — the same backwards direction Phase
35.4 fixed for the stripper.

**Steps:** move `inspect_managed_context` and its printer into
`managed_block.py` (or a sibling `managed_context.py`); `context_sync`
imports them; add the pair to `test_module_dependencies.py`.

**Acceptance:** no analysis module imports `context_sync`; oracle identical.

**Completion evidence (2026-08-17):** the inspector could not move alone —
it needs the block renderer, the safe host-file reader, and the analysis —
so `glossabet/managed_context.py` now holds that whole read-side layer
(`ContextSyncError`, `_render_block`, `_read_regular_target`,
`_analyze_managed_block`, `_inspect_target`, `inspect_managed_context`,
`unchecked_managed_context`, `print_managed_context_issues`,
`MANAGED_CONTEXT_SCHEMA_VERSION`, `MAX_HOST_FILE_BYTES`); `context_sync`
keeps only the write path (`sync_context`, `_write_bytes_atomic`,
`_append_block`, `_detect_newline`, the command) and imports the rest;
`drift`/`reconcile` import from `managed_context`; the re-exports
`context_sync` carried for tests are gone (tests import from
`managed_block`/`managed_context`). Dependency test pins `managed_context`
↛ `context_sync`/`evidence`/`drift`/`reconcile`/`cli` and
`drift`/`reconcile` ↛ `context_sync`. One test that patched
`glossabet.context_sync.os.replace` now patches the module that calls it
(`glossabet.artifacts.os.replace`). Both oracles identical; suite 513 green.

#### Phase 36.5 — Producer-level tests for drift and validation rules ✅ 2026-08-17

**Problem:** the finding *producers* (`_parallel_terms`, `_watched_in_use`,
`_canonical_fading`, `_canonical_overloaded`, `_structure_findings`,
binding/orphan/fragmentation) are exercised almost only end-to-end through
`build_evidence` + stdout substrings; when a rule breaks, the failing test
names the command, not the rule.

**Steps:**
1. Give each producer a test that builds a small `EvidenceIndex`/evidence
   dict directly (the Phase 35.6 renderer test is the model) and asserts
   the finding record, not the printed line.
2. Keep one end-to-end smoke per command; delete stdout-substring tests
   that the producer tests make redundant (test-audit rule: no theater).

**Acceptance:** every finding kind has a test that names it; suite time
does not grow.

**Completion evidence (2026-08-17):** `tests/test_finding_producers.py` —
a hand-built RepositoryEvidence factory (only the tables the producers and
`EvidenceIndex` read) and 15 tests that call the producers directly and
assert the finding record: `parallel-term` (record, glossary-owned term
skipped, sampled-zero suppression reason), `watched-term-in-use` (record,
absent → none), `canonical-fading` (absent → strong, fading → moderate,
truncated table → no claim), `canonical-overloaded` (repository-wide,
scoped dispersion recomputed inside scope, non-canonical / thin scoped
evidence ignored), `_resolve_bindings` (resolved / unresolved /
out-of-scope / uncertain), `orphaned-concept` + `binding-unresolved` +
`fragmentation`, `binding-out-of-scope`, and `unnamed-structure` +
`boundary-mismatch` + `overloaded-structural-region` plus the
missing-`member_tokens` confession. The per-command end-to-end smokes in
`test_drift.py`/`test_reconcile.py` stay (they prove the scanned-corpus
pipeline); the corpus-backed record tests there also stay — they are
integration proofs, not stdout theater. Deleted:
`test_validate_without_glossary_is_user_error` (covered by the Phase 36.2
run contract). Suite 527 tests, ~24 s (unchanged; the new tests run in
0.25 s). No engine change, so no oracle run was needed.

#### Phase 36.6 — Ledger ceremony ✅ 2026-08-17

**Problem:** the coverage-ledger philosophy is right, but
`coverage_ledger(total, included, total_items_exact=…, reasons=…)` appears
~30 times with the same shape, and each producer hand-assembles
`{items, dropped_items, coverage}`.

**Steps:** audit every `coverage_ledger`/`capped_collection` call; where the
call is "cap this list and say so", route it through
`findings.capped_section` (or a generic `capped_collection` returning the
section shape); leave the genuinely different ones (work budgets,
walk-remainder) alone and say why in a comment.

**Acceptance:** ledger construction sites drop by at least a third; no
ledger semantics change (oracle identical).

**Completion evidence (2026-08-17):** the audit found 22 construction
sites (17 bare `coverage_ledger` calls outside `coverage.py` plus 5
hand-assembled `{items, dropped_items, coverage}` dicts), not the ~30
estimated — the terminology and Graphify display caps already went
through `capped_collection`. `coverage.capped_collection` gained
`total_items` (a known larger total, cap reason appended when anything is
left out) and a `capped_section` companion returning the section shape;
`findings.capped_section` delegates to it and `findings.empty_section`
names the skipped / scope-limited case. Routed: evidence vocabulary tables
(`_capped`), Graphify group cap, register exemplars, naming-candidate
ranking (`importance._ranked`, `heapq.nsmallest` → sorted prefix, which
the docs define as equivalent), the synonym/overload sections, and the two
skipped structural sections in `reconcile`. Left bare, with a comment
where it was not obvious: matching and structural-matching work budgets,
Graphify's disabled/unnormalized empty ledgers, `member_tokens`
(complete-by-construction), context-dispersion (a threshold filter, not a
prefix cap), and structure candidates (two drop mechanisms reported in a
fixed order). 22 → 13 sites (−41 %). Oracle identical; local evaluation
cases identical; suite 527 green.

#### Phase 36.7 — Verification weight onto the skill ✅ 2026-08-18 (scoped; live post-approval scenarios split to 36.8)

**Problem:** `SKILL.md` (~700 lines of prose) carries the product's
behaviour and is verified only by string-presence tests plus a Codex
harness whose recorded `canonical_skill_sha256` is already stale.

**Steps:**
1. Re-run the installed-agent harness (Phase 22/28 machinery) against the
   current skill; record per Phase 29 currency rules. **Needs Kyle:**
   authorization to spend Codex/Claude usage for the batch (state scenario
   count and token upper bound first).
2. Add scenarios for the Phase 31–34 behaviours the harness does not yet
   cover: adoption vs. managed state selection, Step 4½ ordering (baseline
   before reading `GLOSSARY.md`), Step 7 `GLOSSABET.md` write/refresh with
   proposed terms kept proposed and no read of a prior report before Step 7.
3. Turn the strongest string-presence tests in `test_skill.py` into
   structure tests (section order, step numbering, every engine field the
   skill names exists in the context — already partly there) and delete
   the weakest.

**Acceptance:** `--current` verifiers pass for agent results; each Phase
31–34 skill behaviour has one recorded live scenario.

**Completion evidence (2026-08-18):** Kyle authorized the batch ("go for
the 36.7 batch"). Wheel and plugin rebuilt from the current tree first
(`uv build --no-sources`, `scripts/build_plugin.py`,
`check_distribution.py` passed). One authorized batch: Codex CLI 0.147.0
on Linux, three host runs (fresh-session hook, twelve plugin scenarios in
one exec, standalone missing-CLI), **14/14 passed on the first attempt**,
790,245 input tokens (625,664 cached) and 11,319 output tokens on Kyle's
Codex account — under the stated ceiling of two attempts ≤ 1.5 M input /
40 k output. Raw run `evaluation/agent-runs/20260818T002910Z-full-0ab07a70.json`;
`agent-results.json` and `agent-history.json` (artifact record refreshed)
committed; `agent_eval.py --verify-results --current` passes; the temporary
plugin/marketplace were removed (`codex plugin list` empty). Scenario
coverage for the Phase 31–32 behaviours is now recorded live
(`markdown-glossary` → adoption, `both-glossaries` → resumed). Step 3:
`test_skill.py` gained `test_skill_sections_are_in_protocol_order` (exact
H2 order, step numbering incl. Step 4½ between 4 and 5, Step 7 last, the
Step 0 sub-sections) and
`test_every_dotted_field_the_skill_names_exists_in_a_real_context` (every
backticked dotted path in the skill — 22 of them — resolves in a context
built over a fixture that fills every optional channel); the two weakest
substring assertions (`"monorepo" in text`, `"freshly generated"`) were
dropped. **Not done here, by decision:** live scenarios for Step 4½
ordering and the Step 7 `GLOSSABET.md` write — the harness executes Step 0
only, and those are post-approval behaviours, so observing them needs a
new host run with its own prompt ("the human has approved; execute Step 7
only") and checks; that is Phase 36.8. The engine-evaluation and reviewer
artifacts remain honestly stale under `--current` (release-gate work; the
reviewer half needs its own live session). Suite 529 green.
