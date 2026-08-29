# Glossabet — Current Roadmap

Last updated: 2026-08-28.

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
the same change, and ends at one focused verified diff boundary. The Phase 2–6
rewrite remains unreviewed until all of those phases are done. A user-requested
checkpoint commit does not constitute review or receive Kyle's DCO sign-off;
Kyle begins code review only after the rewrite phases are complete. No Step may
add a runtime dependency, service layer, provider framework, generic
measurement algebra, or unrequested module split. The
existing CLI-to-artifact flow, Graphify adapter boundary, distribution
duplication, bounded imperative builders, and trust protections remain
protected.

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
- [x] **Step 1.2 — platform-semantic CLI and race contracts**
  (2026-08-27). Verified that all four evaluation lanes already return status
  1, leave stdout empty, and lead with a lane-owned diagnostic when a results
  path is missing. The cross-platform contract now creates that missing path
  beneath `tmp_path` and asserts those stable semantics without requiring a
  POSIX absolute-path spelling or the operating system's `OSError` prose.

  Cache and evaluator scratch race tests now require the external canary to
  remain untouched, the swapped entry not to be followed, and the reported
  cleanup result to match whether the owned entry remains. They no longer
  require Windows and POSIX to leave the same final symlink directory entry.
  No production behavior, security boundary, schema, dependency, or artifact
  changed. Focused tests passed; the complete local suite is 805 passed and one
  Windows-only junction test skipped on Linux. Ruff, product mypy, and workflow
  policy passed. Actual Windows execution remains for Step 1.4.
- [x] **Step 1.3 — deterministic bounded-read verification**
  (2026-08-27). Verified that the production reader already grows requests
  from 64 KiB to a 1 MiB ceiling and judges the limit from returned bytes. The
  interpreter-sensitive `tracemalloc` peak assertion is replaced by a reader
  wrapper that records every requested size and returned byte count.

  The tests now prove that a two-byte file under a 64 MB cap never receives a
  cap-sized or unbounded request; every request is positive and no larger than
  1 MiB; an exact-boundary file succeeds after reading its content and proving
  EOF; and an oversized file returns exactly `cap + 1` bytes before rejection.
  No production behavior, schema, dependency, or artifact changed. Focused
  tests passed; the complete local suite is 805 passed and one Windows-only
  junction test skipped on Linux. Ruff, product mypy, and workflow policy
  passed. Python 3.14 is not installed locally; its actual execution remains
  part of Step 1.4.
- [x] **Step 1.4 — close the support and distribution gates** (2026-08-27).
  The first hosted run passed static analysis and fourteen of fifteen matrix
  lanes, then failed macOS/Python 3.11 twice unchanged because Git's transient
  `maintenance.lock` vanished between `shutil.rmtree` discovery and unlink.
  Confined disappearance during the exact delete operation is now accepted as
  already cleaned; ownership, identity, marker, symlink/junction, and
  permission-retry protections remain intact. The next run passed all matrix
  lanes but exposed the previously skipped package job's bare-interpreter
  `PyYAML` import failure. Quality and manual-release workflow checks now run
  through the locked development environment, with policy tests rejecting a
  regression to the bare interpreter.

  On implementation commit `d55bc48`, local verification passed
  `uv sync --locked`; 807 tests with one Windows-junction skip on Linux; Ruff;
  mypy over 55 product files; the checksum-verified actionlint 1.7.12 binary;
  workflow policy; all three offline evidence verifiers; isolated wheel,
  sdist, and plugin builds; distribution parity; wheel smoke; and the Codex
  plugin install,
  update, invocation, and removal smoke. The product wheel remained byte
  identical at SHA-256
  `332629479a79e4787106514d3293109b34ebf98e31cfb0f3608fd7150e99a4f7`.

  GitHub run [33133049644](https://github.com/kserrec/glossabet/actions/runs/33133049644)
  passed all fifteen CPython 3.10–3.14 × Ubuntu/macOS/Windows lanes, Ruff,
  mypy, actionlint, and the dependent package job. That package job executed
  and passed workflow policy, all retained-evidence verifiers, build, plugin
  reconstruction, distribution parity, and wheel smoke. No supported
  environment, package metadata, schema, runtime dependency, or architecture
  changed to close the gates.

#### Post-Phase 1 bughunt — complete

- [x] **Whole-project correctness sweep and targeted fixes** (2026-08-27).
  After the declared matrix and distribution gate were green, a separate
  bughunt close-read the product, evaluation, packaging, workflow, and test
  surfaces while leaving the already planned Phase 2–6 findings for their
  coordinated schema and cleanup work.

  The sweep confined `cache-clear` across links, junctions, path replacement,
  and partial operating-system failure; prevented relative imports from
  climbing above Python/Rust/JavaScript/Ruby roots without losing a valid
  Python single-dot import at scan root; bound evaluator scratch creation to
  stable parent/child identities; preserved Codex primary failures through
  cleanup interruption; and made blinded reviewer evidence bind to the exact
  command, workspace, completed status, output, immutable packet bytes, and
  failure-atomic content-addressed retention. Tests and current-invariant docs
  changed with the implementations, and the checked-in plugin wheel was
  rebuilt from the final source.

  The first hosted post-bughunt run exposed one Windows-only portability
  defect: cached `DirEntry.stat()` identity was compared with a post-rename
  `Path.lstat()` identity, so an unchanged cache entry looked replaced on all
  five Windows versions. Both sides now use path-based stat identity, with a
  deterministic divergent-enumeration regression test.

  Final local verification passed 827 tests with three platform-specific
  skips, Ruff, mypy over 55 product files, workflow policy, deterministic,
  installed-agent, reviewer, and Claude-history integrity verification,
  distribution parity, isolated wheel smoke, and the plugin
  install/update/remove smoke. A fresh final cold review found no further
  in-scope defect. No live model host was invoked. The release-only
  `--current` deterministic, installed-agent, and reviewer checks are now
  intentionally stale because governing source identities changed; refreshing
  authenticated evidence still requires separate authorization at the exact
  release-candidate gate. The next targeted-hardening work remains Phase 2,
  Step 2.1.

### Phase 2 — canonical scope and boundary behavior

- [x] **Step 2.1 — one NFC scope identity** (2026-08-28).
  The verified before-state normalized a repository path only during scope
  membership lookup. Duplicate and ancestry validation, direct overlap,
  ownership indexing, semantic hashing, save, and load still used the original
  Unicode spelling, so canonically equivalent paths could become competing
  owners and persist as different state.

  `canonical_scope_path` now defines the scope domain's one NFC identity.
  Validation, duplicate/ancestry detection, the ownership trie, direct
  comparison, concept lookup, scope evidence, semantic hashing, load, and save
  all consume it. Load returns an NFC in-memory document without rewriting the
  file; save writes NFC prefixes in deterministic order. Canonically distinct
  paths remain distinct, and equivalent ancestor/descendant owners are refused
  in either declaration order.

  Glossary schema 1 remains correct: scope membership already defined the two
  Unicode spellings as one path, and existing schema-1 documents are accepted
  and normalized in memory rather than requiring a migration. The canonical
  skill, bundled plugin skill, plugin wheel, architecture, maintainer
  walkthrough, coding-agent rules, and changelog describe the resulting
  contract.

  Four focused NFC scenarios passed; 195 glossary/drift/reconciliation/context
  tests and 48 skill/plugin/install/artifact tests passed. The complete suite
  passed with 831 tests and three platform-specific skips; Ruff, mypy over 55
  product files, workflow policy, all retained offline evidence verifiers,
  source/wheel distribution parity, isolated wheel smoke, and diff checks
  passed. This remains part of the unreviewed Phase 2–6 rewrite; human review
  and DCO-signed commits begin after those phases, not as a per-Step gate.
- [x] **Step 2.2 — deliberate command/filesystem boundaries** (2026-08-28).
  The verified before-state collapsed successfully parsed JSON `null` into the
  same `None` used for stdin failure, so `save` exited 1 without a diagnostic;
  `read_regular_target` refused only a definite exact-name mismatch and let an
  indeterminate bounded lookup authorize a host-file write; and `open_run`
  refused every absolute path containing a component named `glossabet-out`
  without proving tool ownership.

  The stdin reader now returns the input-channel outcome separately from its
  parsed value, so `null` reaches schema validation and reports that the top
  level must be an object. Managed-context reads and writes require a confirmed
  exact target name: a different spelling has its existing collision
  diagnostic, while lookup uncertainty is explicitly uninspectable and leaves
  the bytes untouched. `open_run` recognizes a genuine output ancestor only
  when it contains an exact regular current `evidence.json`, `glossary.json`,
  `drift.json`, or `validation.json` file. An exact lowercase
  `glossabet-out` component already names the path the command addresses; a
  differently cased, case-preserved component additionally needs available
  matching non-symlink directory identity with the lowercase lookup. That
  accepts case-preserved physical names on a case-insensitive filesystem
  without conflating two case-distinct directories or following a lowercase
  symlink alias that the artifact writer itself rejects. An uncertain
  exact-name/file-kind check or required identity fails closed, while an
  unrelated same-named ancestor and artifact-shaped directory/special entry
  remain ordinary paths. This is a narrow four-name ownership check, not a
  directory classifier.

  The first required cold review found that comparing the preserved component
  spelling alone missed a differently cased physical output name on a
  case-insensitive filesystem. A failing filesystem-identity emulation proved
  the command then scanned its own artifact and wrote nested output. Binding
  the lowercase lookup and preserved ancestor by `samestat` closes that gap
  without conflating two case-distinct directories.

  The second required cold review found that an exact artifact-shaped entry
  still needed a regular-file check and that `samestat` treats two unavailable
  zero identities as equal. Both states now have direct regressions: non-files
  prove no ownership, and unavailable identity becomes uncertainty.

  A final root pass then found that checking identity before artifact proof
  made an unrelated same-named ancestor fail closed when its identity was
  unavailable even though it held no Glossabet artifact. Artifact proof now
  comes first, and identity is consulted only for a differently cased,
  artifact-bearing ancestor. A direct regression keeps the no-artifact state
  ordinary when identity is unavailable.

  The first closure review found that both uncertainty causes shared a message
  that blamed an uninspectable artifact name even when the artifact was
  confirmed and only directory identity was unavailable. The refusal behavior
  was already safe; its diagnostic now says that output-directory ownership
  could not be proved from the required artifact and filesystem-identity
  checks. Both uncertainty paths assert the corrected message directly.

  The replacement closure review found that the lowercase identity lookup
  still used `stat`, so a sibling `glossabet-out` symlink could bind an
  ordinary `Glossabet-Out` directory to the tool-owned name even though every
  artifact write rejects symlink path components. Identity comparison now uses
  `lstat` and requires real directories on both spellings; a direct symlink
  regression proves the unrelated repository remains usable.

  The next closure review found that the shared exact-name helper's `lexists`
  fast path swallowed every `lstat` error and returned false, so an
  uninspectable exact artifact could masquerade as absence before the output
  classifier saw it. The helper now uses `lstat` directly: only
  `FileNotFoundError` proves absence, while other lookup failures return its
  documented uncertainty state. A direct regression proves no nested output
  write occurs when a genuine artifact lookup fails.

  Thirteen focused positive, negative, and uncertainty scenarios passed; the 199
  surrounding glossary/context/CLI/run/repository-glossary/artifact tests and
  43 module-dependency/skill/install/artifact tests passed. The complete suite
  passed with 843 tests and three platform-specific skips; Ruff, mypy over 55
  product files, workflow policy, all retained offline evidence verifiers,
  Claude-history integrity, source/wheel distribution parity, isolated wheel
  smoke, and the Codex plugin install/update/invocation/removal smoke passed.
  The rebuilt wheel SHA-256 is
  `1d8b1bccf330c5117c7f9fc20c052f1e5137f69c032e8b6e16e496ca09c696a9`.
  No schema version, runtime dependency, live host, or external account changed.

#### Post-Phase 2 bughunt — fixes verified; fresh cold review clean

The requested delta-plus-interactions sweep close-read every Phase 2 executable
change and traced glossary validation/persistence/matching, command dispatch,
managed-context synchronization, artifact I/O, and the existing race tests. It
found two proved defects; no Likely finding remained unsettled.

First, the shared exact-entry helper treated a successful path lookup followed
by a listing with no matching entry as definite absence or alternate spelling.
An ordinary concurrent disappearance could therefore falsely report a host
filename collision, and the same sibling race could let a disappearing output
artifact authorize a nested `glossabet-out/` write. The helper now requires two
consistent bounded directory-name observations with a requested-path lookup
between them. Exact spelling must appear in both observations; an alternate
spelling must appear in both and bind to the corresponding requested-path
identity. All three callers preserve disagreement or unavailable identity as
uncertainty; stable absence, exact spelling, and alternate spelling retain
their deliberate behavior.

Second, the managed host reader treated three `(device, inode)` pairs containing
inode zero as proof that one file stayed in place. On a filesystem where zero
means portable identity is unavailable, a replacement could therefore be read
as unchanged. Existing targets now fail closed before any bytes are read when
any of the pre-open, opened, or post-open observations lacks identity. This
closes an incomplete sibling of the older Phase 45.14 concurrency proof.

The first required cold review broke the initial repair with the missing
composition: exact `evidence.json` and a differently cased sibling coexisted,
then the exact entry vanished between lookup and listing. Merely seeing the
sibling still returned definite mismatch. The three-observation identity bind
above closes that whole sibling class, and unavailable identity remains
uncertainty. The same review also ran the stronger current-distribution gate
and found that the source archive had been built before the checked-in plugin
was refreshed, so it still bundled the pre-bughunt wheel. The final build now
runs to a fixed point: build the current engine, refresh the plugin, rebuild
the source archive from that refreshed tree, and require
`check_distribution.py dist --current` to pass.

The replacement cold review found that the three-observation identity repair
still confused file identity with directory-entry identity: case-distinct
hardlinks share one inode. It removed the exact link before listing, restored
it afterward, and proved the helper returned alternate spelling even though
the exact entry was current again; `scan` wrote nested output. A second probe
showed that a `DirEntry` can retain an exact name after the entry is renamed.
The two-listing agreement above closes both cases: a restored hardlink changes
the observed name state, and a stale exact `DirEntry` must still resolve by
that spelling before it can count. Both hunters are permanent regressions.

The next cold review found one caller-specific gap after the shared helper was
correct: the managed host reader could observe `AGENTS.md`, lose it before the
helper's first lookup, and interpret the helper's truthful fresh-absence
`False` as a stable alternate spelling. The write already failed closed, but
the diagnostic told the user to rename a nonexistent file. A first `False` is
now provisional for this caller. The reader binds the result to its earlier
file identity, repeats the bounded exact-name decision, and rechecks identity;
only a repeated alternate-spelling result bound to the same known file gets
the collision diagnostic. Disappearance, restoration under the exact name,
replacement, or observation disagreement is a detected change or explicit
uncertainty. Direct regressions cover both continued absence and restoration
of the same inode, so an identity-only repair cannot satisfy the class.

Twelve direct filesystem regression cases cover host disappearance alone and
beside a casefold-equivalent sibling, output-artifact disappearance alone and
beside distinct and hardlinked siblings, stale directory-entry spelling,
stable alternate spelling with available and unavailable identity, and
unavailable host identity with both an unchanged and replaced target, plus the
managed caller's pre-helper disappearance and same-inode restoration windows.
The current-distribution gate is the executable regression for the
source-archive finding. The complete suite passed with 855 tests and three
platform-specific skips; Ruff, mypy over 55 product files, workflow policy,
all retained offline evidence verifiers, Claude-history integrity, current
source/wheel/plugin distribution parity, isolated wheel smoke, and the Codex
plugin install/update/invocation/removal smoke passed. The current wheel SHA-256
is `137233ab11e2df09c6c857d8db4bda5d4745e34370259bb129acb4548ff9fc38`;
the source-distribution SHA-256 is
`4e9968656d17988e2e50c2d89bd474127d406d0819c350d7b66495824102b94c`.
These supersede the pre-bughunt Step 2.2 artifact above. No schema version,
runtime dependency, live model host, external account, or Phase 3 code
changed. This is still part of the unreviewed and uncommitted Phase 2–6
rewrite; human code review begins only after all those phases are complete.

The required final fresh-agent cold review close-read the exact-entry state
machine, all three callers, managed-context synchronization, output ownership,
NFC scope/persistence, stdin boundaries, regressions, documentation claims, and
distribution copies. Its 197 focused Phase 2 tests, diff check, parity check,
and recorded hash checks passed; it found no further in-scope defect. Native
case-insensitive behavior was deterministically emulated on Linux rather than
run on Windows, and mutation after the final relevant filesystem observation
remains the documented unavoidable concurrency limit. The bughunt pass is
clean and complete.

At Kyle's explicit checkpoint request on 2026-08-28, the completed Phase 2
change set was committed as `24ba4a8` and pushed to `origin/main`. That
checkpoint has no DCO sign-off and remains unreviewed; human code review still
begins only after all rewrite phases are complete.

### Phase 3 — exactness, completeness, sampling, and skipped checks

- [x] **Step 3.1 — occurrence exactness contract** (2026-08-28). Migrate
  numeric occurrence facts from ambiguous “complete” names to `count_exact`, `files_exact`, and
  `modules_exact`; retain collection `complete` and display
  `locations_truncated`; persist exact global identifier module counts; and
  distinguish upstream clipping from final display sampling for scoped,
  single-token, and compound occurrences. Update affected schema versions,
  fixtures, serializers, consumers, and documentation together with no parallel
  legacy fields unless the compatibility policy explicitly requires them.

  The verified before-state used `count_complete` and `files_complete`, had no
  `modules_exact`, and did not persist an identifier's global module total.
  `code_identifier_occurrence` reconstructed that total from its bounded
  location display. Scoped lookup clipped its display without recording the
  final clip, while an unscoped single-token lookup could exceed the matcher's
  five-location display cap when evidence was built with a larger cap.

  The named invariant is: every numeric occurrence fact says whether that
  number is exact through `count_exact`, `files_exact`, or `modules_exact`;
  `locations_truncated` describes only the bounded location display. Upstream
  clipping may make a scoped scalar a lower bound, but final display sampling
  never makes an already-computed scalar inexact.

  Evidence now computes each identifier's module total from every accepted
  scanned file before sampling locations. Shared scoped and unscoped occurrence
  builders keep scalar truth separate from the five-location display, and the
  compound path separately tracks upstream location loss and final sampling.
  All current serializers and consumers use only the literal exactness names;
  collection-ledger `complete` and display `locations_truncated` retain their
  distinct meanings. The replaceable schemas advance together: evidence 16,
  agent context 4, drift 7, and validation 9. Historical Codex, Claude, and
  blinded-review records remain immutable evidence from their original engine.

  Four red scenario classes proved the migration: persisted identifier module
  totals survive an upstream location cap; scoped and unscoped single-token
  scalars survive final display sampling; compound file/module totals survive
  final sampling; and upstream compound clipping marks only the facts it can no
  longer prove. The complete suite passed with 858 tests and three
  platform-specific skips. Ruff, mypy over 55 product files, workflow policy,
  deterministic/Codex/reviewer evidence verification, Claude-history
  integrity, current source/wheel/plugin distribution parity, isolated wheel
  smoke, and the Codex plugin install/update/invocation/removal smoke passed.
  Diff checks and active-schema/legacy-name searches passed; the remaining
  `source_files_complete` benchmark field is an unrelated corpus ledger, and
  two old occurrence names appear only in negative assertions proving their
  absence.

  `evaluation/results.json` was regenerated locally from all seven pinned
  deterministic cases with no model or paid service. Its engine identity is
  evidence 16 / drift 7 / validation 9, all integrity and currency checks pass,
  and 14 of 15 configured release thresholds pass. The sole release-mode error
  is represented honestly: distinctive nomination quality is 0.75 against the
  deliberately exact 1.0 target. The wheel SHA-256 is
  `eb2f6d6e9371a9f54f0aa0155d6369d57caf4a8a71ae211162dfeaeb825ce63e`;
  the bundled wheel is byte-identical; the source-distribution SHA-256 is
  `d3b39ae2fb3c6a3701d631b693b2d9c78ece58cb9a556ef96d51289ea91701f9`;
  and deterministic results SHA-256 is
  `1f7748095dc9462dd5544fcb265598f413d153b3ee456f27d862ca52e8cb8e42`.
  No runtime dependency, live model host, external account, or Phase 3.2
  analytical decision changed. This Step remains an unreviewed, uncommitted
  rewrite boundary; the next chunk is Step 3.2.
- [x] **Step 3.2 — epistemically sound analytical decisions** (2026-08-28).
  Apply identical
  fragmentation rules to simple and compound terms: emit a lower-bound count
  already above threshold, suppress an inexact below-threshold negative, and
  record the incomplete reason. Add one “unproven zero” helper and use it for
  parallel/watched/fading/binding and related checks when tables, locations,
  work, term limits, or production corpus coverage make absence unknowable.

  The verified before-state reconstructed analytical certainty in each
  producer. `_sampled_to_zero` recognized only a scoped zero paired with a
  clipped location display, so table truncation, partial production corpus,
  compound-work exhaustion, and unrepresentable terms could suppress absence
  without a producer-level reason. Canonical fading silently skipped inexact
  code counts, symbol and orphan decisions did not record every unproven zero,
  and fragmentation applied a token-only location guard that treated scoped
  simple and compound terms differently and confused display clipping with
  scalar exactness.

  The named invariant is: a positive lower bound may prove a positive
  threshold, but only an exact zero or exact below-threshold total may prove a
  negative. Decisive evidence composes normally: one exact zero disproves a
  positive conjunction even when another zero is unknown, and a positive
  documentation count disproves fading even when a low code count is inexact.

  `matching.is_unproven_zero` now defines one zero as unproven exactly when its
  count is zero and `count_exact` is false. That flag already incorporates
  corpus, table, scoped-location, matching-work, and term-representability
  limits. Parallel-term, watched-term, canonical-fading, symbol-binding, and
  orphan producers use the helper and add a producer-level suppression reason
  only when the unknown fact could change the decision. An unrepresentable
  empty tokenization is explicitly inexact rather than an exact absence.

  Fragmentation now consumes `modules_exact` identically for one-token and
  compound terms. A retained spread of five or more modules emits a finding;
  an inexact spread says “at least” and persists
  `module_spread_exact: false`. An inexact lower bound below five emits no
  negative conclusion and records the suppressed check, while display-only
  sampling leaves an exact scalar alone. The new persisted exactness field
  advances the replaceable validation document to schema 10. Drift remains
  schema 7 because its document shape did not change. Phase 3.3 projection
  semantics were not changed.

  Red producer and end-to-end scenarios cover partial-corpus, truncated-table,
  clipped-location, exhausted-work, term-limit, and unrepresentable-term
  zeros; decisive exact-zero and positive-documentation operands; uncertain
  symbols and orphans; simple/compound spreads below and at the threshold; and
  display-only clipping. The focused drift/reconciliation matrix passed 133
  tests. The complete suite passed 868 tests with three platform-specific
  skips. Ruff, mypy over 55 product files, workflow policy, deterministic,
  installed-agent, reviewer, and Claude-history integrity verification,
  current source/wheel/plugin distribution parity, isolated wheel smoke, and
  the Codex plugin install/update/invocation/removal smoke passed. Diff checks
  and active validation-schema searches passed.

  `evaluation/results.json` was regenerated locally from all seven pinned
  deterministic cases with no model or paid service. Its engine identity is
  evidence 16 / drift 7 / validation 10, all integrity and currency inputs
  match, and 14 of 15 configured release thresholds pass. The strict current
  verifier fails only because distinctive nomination quality remains 0.75
  against the deliberately exact 1.0 target. The wheel SHA-256 is
  `412cbeaa9d0df2da6eb53878019b1c0496d2e208a65f5e0b72771dfa36ef5c37`;
  the bundled wheel is byte-identical; the source-distribution SHA-256 is
  `e8a2f0b2db6bc093be45d3eae3b7731a66f323936c548782dcde44fe43638bf5`;
  and deterministic results SHA-256 is
  `86ad4532585cf36e609c86156705034398b4b28c1ec86bd8dd18302b50e530a8`.
  No runtime dependency, live model host, external account, or Phase 3.3
  projection decision changed. This Step remains an unreviewed, uncommitted
  rewrite boundary; the next chunk is Step 3.3.
- [x] **Step 3.3 — projection semantics** (2026-08-28). Separate selected
  projection, `projection_complete`, `source_complete`, intentional protocol
  exclusions, source omissions, limit-driven truncations, and the limits
  actually applied.

  The verified before-state put intentional import exclusion, lean
  file-location rollups, missing projection sources, list sampling, and string
  truncation into one `omissions` list. Its single `complete` flag was therefore
  false for every ordinary lean context—and even for a full context solely
  because imports are deliberately outside the protocol. The reported `limits`
  also included a soft routine byte target that never rejects output and a
  lean-only exemplar cap in full projections where exemplars do not exist.

  The named invariant is: projection completeness answers only whether the
  selected projection hit one of its own limits; source completeness answers
  whether its required source evidence was available; intentional protocol
  exclusions are disclosed but make neither claim false. Nested collection
  ledgers remain authoritative for their own caps and are not flattened into
  either top-level boolean.

  Agent context schema 5 now names `projection`, `projection_complete`,
  `source_complete`, `intentional_exclusions`, `source_omissions`,
  `truncations`, and `applied_limits`. Designed import exclusion and lean
  location rollups are intentional exclusions. Corpus-budget incompleteness or
  a missing source item makes source completeness false without pretending a
  projection cap fired. Only bounded list or string loss makes projection
  completeness false. Applied limits contain the hard serialized-byte,
  string, default-list, selected per-path list, and coverage-record limits;
  the lean exemplar limit appears only in the lean map. The parallel legacy
  `complete`, `omissions`, aggregate omission fields, and non-applied limits
  were removed.

  The canonical skill now teaches the two independent claims, designed
  exclusions, actual limits, and nested-ledger rule. Installed-agent scenario
  judgments and both benchmark ledgers consume the same schema. Active
  architecture, changelog, evaluation, walkthrough, canonical skill, and
  generated plugin copy describe schema 5; immutable historical host records
  retain the schema they actually observed. Evidence 16, drift 7, and
  validation 10 did not change in this Step.

  Red scenarios first proved all seven old-schema failures. The final tests
  prove that a standard lean context is source- and projection-complete despite
  its intentional exclusions; list and string caps make only the projection
  incomplete; partial corpus or unavailable nomination source makes only the
  source incomplete; lean and full projections report only their applied
  limits; legacy fields are absent; and serialized output remains bounded and
  byte-deterministic. All 15 agent-context tests and the 62-test
  context/skill/evaluator/benchmark boundary passed. The complete suite passed
  870 tests with three platform-specific skips. Ruff, mypy over 55 product
  files, workflow policy, deterministic, installed-agent, blinded-reviewer,
  and Claude-history integrity verification, current source/wheel/plugin
  distribution parity, isolated wheel smoke, and the Codex plugin
  install/update/invocation/removal smoke passed. Diff checks and active
  legacy-schema searches were clean.

  `evaluation/results.json` was regenerated locally from all seven pinned
  deterministic cases with no model or paid service. It is genuine and current
  to engine source SHA-256
  `12de7fd27d3d2270b823b669ff1543437b6046607234198eb6b89e62ecb01334`;
  14 of 15 configured thresholds pass, and strict current verification fails
  only because distinctive nomination quality remains 0.75 against the exact
  1.0 target. The wheel and byte-identical bundled wheel SHA-256 are
  `84f039d3d0c60360a15d85509674ad3b73ef20ce0e7a8d6d5e847de1e725e6d3`;
  the source-distribution SHA-256 is
  `27c729a85792538a9f7f33462a1dd7033048b1821eed3514cd45146ebd28675e`;
  and deterministic results SHA-256 is
  `ab4fef85677c75eb25b476b398988fa0d97b171e0983f6ac70c482da1e79f0e4`.
  No runtime dependency, live model host, external account, or Phase 3.4
  validation/graph decision changed. This Step remains an unreviewed,
  uncommitted rewrite boundary; the next chunk is Step 3.4.
- [x] **Step 3.4 — validation execution and graph state** (2026-08-28).
  Separate all-checks execution/skips from the exact total produced by
  evaluated checks; rationalize externally visible graph state around
  `present`, `usable`, `freshness`, and `warnings`; apply the compatibility
  policy to `graph_available`; and migrate validation schema, evaluation
  scoring, fixtures, docs, and distribution copies in one coherent change.

  The verified before-state summed all eight finding sections into
  `total_findings` and called the total complete whenever every non-skipped
  section had an exact ledger. With Graphify absent, three structural checks
  were skipped but `total_findings_complete` could still be true and the CLI
  printed the result as an unqualified finding count. Structural evidence used
  `available` for normalized-group usability, omitted `freshness` in
  unavailable states, and validation duplicated the same usability fact as
  both `graph.usable` and `graph_available`.

  The named invariant is: `total_findings_exact` describes only the numeric
  total produced by finding checks that actually ran; `finding_checks`
  separately says whether all eight ran and names every skipped check and its
  reason. Graph state always exposes `present`, `usable`, nullable `freshness`,
  and `warnings` together, while its group coverage stays authoritative for
  structural sampling. Presence and usability remain separate facts: a graph
  may be present but unusable, and a disabled adapter reports unknown presence
  rather than pretending the graph is absent.

  Evidence schema 17 and agent-context schema 6 now use `usable` and carry all
  four graph-state fields in usable, present-but-unusable, absent, and disabled
  states. Validation schema 11 serializes that state only inside `graph`, adds
  `finding_checks`, sums only non-skipped sections, and replaces its ambiguous
  `total_findings_complete` with `total_findings_exact`. The CLI qualifies the
  total as coming from evaluated checks whenever a finding check was skipped.
  Evidence, context, and validation are replaceable generated documents, so
  their retired `available`, `graph_available`, and validation-total fields
  were removed rather than kept as parallel compatibility aliases. Drift
  remains schema 7 and retains its independently defined
  `total_findings_complete`; immutable recorded host runs retain the fields
  their original engines actually emitted.

  The deterministic manifest advances to schema 6 and results to schema 8.
  Structural evaluation contracts now pin graph state, validation finding-check
  execution, and evaluated-total exactness. The canonical skill, installed-host
  scenario judgments, benchmark ledgers, architecture, changelog, evaluation
  guide, walkthrough, tests, fixtures, generated plugin skill, and bundled
  wheel all consume the same contract.

  The pre-implementation contract run produced ten expected failures covering
  schema migration, usable, malformed, absent, and disabled graph states,
  all-executed and named-skipped finding checks, exact and inexact evaluated
  totals, CLI qualification, evaluator contracts, and skill field references.
  The complete suite passed 870 tests with three platform-specific skips. Ruff,
  mypy over 55 product files, workflow policy, deterministic, installed-agent,
  blinded-reviewer, and Claude-history integrity verification, current
  source/wheel/plugin distribution parity, isolated wheel smoke, and the Codex
  plugin install/update/invocation/removal smoke passed. `actionlint` remains
  unavailable locally and no workflow changed. Diff checks and active
  legacy-name searches passed; only drift's separate field, negative assertions,
  and immutable historical evidence retain the old names.

  `evaluation/results.json` was regenerated locally from all seven pinned
  deterministic cases with five cold and five warm runs and no model or paid
  service. Its engine source SHA-256 is
  `ed1580b0a3bdeceae23eab68bbd37dcc12897554750be096fb5b9f52c1807163`;
  all integrity and currency inputs match; 14 of 15 configured thresholds pass;
  and strict current verification fails only because distinctive nomination
  quality remains 0.75 against the deliberately exact 1.0 target. The wheel
  and byte-identical bundled wheel SHA-256 are
  `956110dc721f6bafd89982e291140a0e9e329d78c27f1a8b428d6c22d8776460`;
  the source-distribution SHA-256 is
  `dfafb8723291380bc3dbfa573a992ced9cb098d2be9156aeaa0849ba3833b533`;
  and deterministic results SHA-256 is
  `7acaf05385d9714274e9197e36e729a37c5a5ade22a76d09f1b3c540d258c5cb`.
  No runtime dependency, live model host, external account, or Phase 4 work was
  introduced. At Step completion this was an unreviewed, uncommitted rewrite
  boundary; the subsequent Phase 3 correctness review below is authoritative.

**Phase 3 correctness review (2026-08-28): complete and clean.** The bughunt
close-read all 18 Phase 3 executable surfaces, all changed tests, and their
affected callers and contracts; it skimmed the changed explanatory/generated
surfaces and excluded unrelated Phase 4 and older implementation. Seven source
defects were proved with concrete red scenarios before repair: (1) a skipped
structural check could also claim to be partial; (2) binding uncertainty was
not recorded when it did suppress an orphan decision and could qualify checks
it could not change; (3) an inexact occurrence could lose its authoritative
suppression reason beside an uncertain binding; (4) incomplete Graphify
member/label evidence could manufacture an exact unnamed-structure absence;
(5) a character-truncated label could manufacture a positive token and false
boundary/overload findings; (6) the installed-agent context judge accepted
malformed or invented intentional-exclusion records; and (7) its accepted
records could be duplicated or carry an impossible import amount. Every
finding was fixed serially with a class-level regression; none was deferred.

The structural invariant is now explicit in source and skill: retained complete
tokens are sound positive lower bounds, but capped or character-truncated
evidence cannot prove absence, and the unfinished trailing lexical fragment of
a bounded label is discarded. Orphan coverage now names occurrence versus
binding uncertainty according to which fact can actually change the decision.
The installed-agent judge validates the exact allowed exclusion record shapes,
uniqueness, and amounts. The generated plugin wheel was then found to still run
the pre-fix engine; it was rebuilt from the reviewed source, its digest pin was
updated, and the original member-label and group-label failures were replayed
successfully through the shipped wheel.

The required non-author cold review ended with no confirmed, likely, or edge
finding. Its final parity pass compared every bughunt-modified executable module
against the release wheel, checked-in plugin wheel, and source distribution as
applicable; compared every skill and runner copy; and replayed the defect through
the installed artifact. Its source matrix passed 168 tests. The complete suite
passed 881 tests with three platform-specific skips. Ruff, mypy over all 55
product files, workflow policy, diff integrity, current distribution parity,
isolated wheel smoke, the public walkthrough, the benchmark, and the Codex
plugin install/update/invocation/removal smoke all passed. `actionlint` remains
unavailable locally and no workflow changed.

Offline deterministic evidence was regenerated from all seven pinned cases
with five cold and five warm runs and no model or paid service. It reports
precision 1.0 and zero false alarms; 14 of 15 thresholds pass, with the sole
strict-current failure still the deliberate nomination-quality score of 0.75
against 1.0. The default deterministic, installed-agent, blinded-reviewer, and
Claude-history integrity verifiers pass. Release-current installed-agent and
blinded-reviewer evidence is not claimed: the bughunt changed their evaluator
or delivery inputs, and refreshing those immutable host records requires
separately authorized live runs. The engine source SHA-256 is
`8cb63d3f77c0677756fadb6f7aa8572df7dbfcf15b604004236086a79c567ee0`;
deterministic results SHA-256 is
`6bee9da33665fcd54cf29271633d90da965a0b5e367a0834cd8cd21df9fa8c70`;
the release and both bundled wheel copies are byte-identical at
`ab723a9e183535fbee53f3f3c922b85abce3da6a78ddb21a2ef6348642c66e2e`;
and the source-distribution SHA-256 is
`cf3ec8500f31ad7e51e0c459a5fa17de9addf3229ccc5cce03c80f6e3aed5ed1`.
Wrapup synchronized `EVALUATION.md` to the regenerated timing measurements and
rebuilt that final source distribution; executable and wheel bytes did not
change, and current distribution parity passed again.
No runtime dependency, live model/account use, commit, push, or Phase 4 work was
introduced. Phase 3 is a reviewed rewrite boundary; the next implementation
chunk is Step 4.1.

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
