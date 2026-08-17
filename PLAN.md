# Glossabet — Plan

Status: **phases 0–22 and Phases 24–32 complete; owner
self-testing pause active before the trusted-alpha gate** as of 2026-08-17.
Phases 18–23 are the complete
post-audit route from the current local package to a defensible trusted alpha.
Phases 24–28 were added 2026-08-15 from Kyle's self-testing findings and run
before the trusted-alpha gate and Phase 23 in execution order, so outside
testers meet the corrected signals rather than re-reporting known defects.
Public release remains a separate, explicit authorization gate after those
phases.
This document is the authoritative roadmap. Provenance: merged from the working
sessions of 2026-08-14 — Claude's loop/reconciliation analysis, ChatGPT's
"Robust Repository Vocabulary System" spec and repo-transition notes, and the
existing `/glossabet` skill, which is the behavioral spec this project serves.

## Purpose

Every substantial codebase develops a conceptual vocabulary whether or not
anyone manages it. Left implicit, different people use different words for the
same thing, one word accumulates several meanings, important architecture goes
unnamed, and docs drift from code. Agents suffer the same way: they
reconstruct what terms mean from raw code on every run.

The empirical basis for treating repository vocabulary as a real
comprehension problem—and the limits of what that research establishes for
this product—is summarized in the README under "Why repository vocabulary
matters."

Glossabet makes a repository's vocabulary **explicit, canonical, inspectable,
and maintainable**. It is a software system whose primary interface is the
`/glossabet` agent skill: deterministic machinery gathers evidence, the LLM
brainstorms and reasons about terminology, and **the human decides**. That
division of labor is the product's central rule and never changes.

Optionally, Glossabet consumes [Graphify](https://github.com/Graphify-Labs/graphify)
output as richer structural evidence. Graphify answers "what is connected to
what?"; Glossabet answers "what are these things conceptually, and what should
we call them?" Together they can ask: does the vocabulary we use to understand
this system correspond to the system we built? **Graphify is never required.**

## Product shape

```
┌─────────────────────────────────────────────┐
│  /glossabet agent skill  (the UX)          │
│  nominates, proposes, brainstorms, defers   │
│  to the human; finalizes only when told     │
└───────────────────┬─────────────────────────┘
                    │ requests a fresh, bounded agent context
                    │ through the CLI; reads named source files
┌───────────────────▼─────────────────────────┐
│  glossabet engine / CLI  (deterministic)   │
│  scanning · terminology mining · register   │
│  stats · glossary persistence · drift ·     │
│  reconciliation                             │
└───────────────────┬─────────────────────────┘
              evidence adapters
             ┌──────┴────────┐
             ▼               ▼
     built-in scanner    Graphify graph.json
     (lexical-first)     (optional, richer structure)
```

Both evidence sources normalize into one Glossabet-owned intermediate
representation, **RepositoryEvidence**. Everything above that boundary is
source-agnostic; future adapters (LSP, other analyzers) plug in the same way.

## Principles (all binding)

1. **The human names the world.** Machinery nominates and grounds; the LLM
   proposes and reasons; only human approval makes a term canonical. Glossabet
   never mass-renames code and never finalizes unilaterally.
2. **Lexical-first scanner identity.** The built-in scanner is *the lexical
   evidence provider*: files, directories, docs inventory, identifier
   vocabulary, plus cheap best-effort import edges. It never grows into a
   static analyzer or a Graphify clone. When rich structure matters, an
   adapter supplies it. Full symbol extraction (tree-sitter et al.) is
   deferred until real use proves it necessary — it may never be.
3. **No evidence contamination.** The scanner excludes `glossabet-out/`,
   `.glossabet/`, pre-rename `glossarize-out/` and `.glossarize/`, and the
   repo's `GLOSSARY.md` from evidence gathering, from v0.1 on. Otherwise the
   glossary echoes through the evidence and blinds drift detection (canonical
   terms look "used" because the glossary uses them). Adapter-provided
   evidence tags current and pre-rename glossary nodes by provenance and
   discounts them in reconciliation.
4. **Sensitive-file hygiene.** The scanner walks real repos containing `.env`
   files, keys, and credentials. Sensitive paths are excluded by pattern,
   never ingested into any artifact, and a test proves it. (Graphify's
   `_SENSITIVE_PATTERNS` is prior art.)
5. **Staleness is a trust problem.** Every evidence artifact records the git
   state it was built from (HEAD, dirty flag). The skill checks freshness
   before grounding a brainstorm on it and says so when evidence is stale.
   Silently reasoning from last month's repo is never acceptable.
6. **Determinism.** Same repo state → same evidence artifact, byte-stable
   where feasible. Deterministic machinery is what earns the skill's trust in
   the evidence.
7. **Bindings target stable identity.** Concept-to-code bindings reference
   symbols, files, and modules — never Graphify community numbers or graph
   node ids, which are not stable across rebuilds. An unresolved binding is a
   first-class drift signal, not an error to silence.
8. **Graphify is an adapter, never a dependency.** Detect
   `graphify-out/graph.json`; use it if present, proceed identically without
   it. Never mutate Graphify's artifacts — Glossabet owns
   `glossabet-out/`, Graphify owns `graphify-out/`. Native Graphify support
   for consuming `glossary.json` would be a nice upstream contribution, never
   an architectural dependency.
9. **Dependencies earn their place.** Start stdlib-only where practical; every
   dependency needs a real use site and a one-line cost/reason record.
10. **Tests protect concrete threats** — wrong or nondeterministic evidence,
    ingested secrets, contaminated evidence, silently stale artifacts, schema
    drift, broken tokenization. No coverage filler.
11. **Preserve the skill's philosophy verbatim.** Write for regulars; ground
    every named thing in real code; match the house register; boundary-encoding
    names are worth the most; carry the reasoning into the glossary; the first
    pass is a brainstorm opener, never a verdict.
12. **Bounded work with logged truncation.** Engine work stays linear in repo
    size wherever feasible; nothing quadratic in vocabulary size runs without
    a bound. Any analysis that caps coverage (locations per term, candidate
    pairs, examples) states the cap and reports what was dropped — a
    truncated artifact must never read as complete. This is what keeps
    Glossabet honest on repos of any size.

## Non-goals

Glossabet is not: an automatic renamer, a static analyzer or language server,
a dependency visualizer, a generic architecture-doc generator, a Graphify
clone, or an ontology generator that removes human judgment. Structural
sophistication belongs to adapters, not the core.

## Artifacts

```
<scanned repo>/
├── glossabet.json       optional literal-prefix ignore/path-role configuration
├── glossabet-out/
│   ├── evidence.json     machine evidence (RepositoryEvidence, schema_version, git stamp)
│   ├── glossary.json     machine-readable canonical vocabulary (from Phase 6)
│   └── (analysis outputs as later phases add them)
└── GLOSSARY.md           human artifact at repo root, format per skill Step 6
```

The incremental extraction cache is user-owned state outside the scanned
repository, under the platform cache directory and keyed by the repository's
resolved path. Repository-local `.glossabet/` remains excluded as a legacy
artifact path but is never trusted or loaded.

`GLOSSARY.md` stays the human-readable, reasoning-carrying document the skill
already specifies (house-register line, headline distinctions as prose, detail
tables with a *(was)* column, primary decisions, load-bearing rule).
`glossary.json` starts deliberately minimal — `schema_version`, concepts with
`id`, `term`, `definition`, `status`, `aliases`, `notes` — and grows only when
a consumer (drift, reconciliation) actually needs a field. Status lifecycle
from day one: `canonical · proposed · alias · discouraged · deprecated ·
unknown`. Bindings, scopes, kinds, and concept relationships are deferred to
the reconciliation phase, which is their first real consumer.

## CLI surface (target)

```
glossabet scan .        build/refresh RepositoryEvidence          (Phase 2)
glossabet analyze .     terminology + register analysis           (Phase 4)
glossabet inspect .     emit fresh bounded agent context          (Phase 18)
glossabet brief .       emit bounded read-only vocabulary         (Phase 28.1)
glossabet sync-context . explicitly persist managed host context  (Phase 28.3)
glossabet save .        validate/save glossary JSON from stdin    (Phase 18)
glossabet show          display current glossary                  (Phase 6)
glossabet drift .       compare live vocabulary vs canonical      (Phase 7)
glossabet validate .    glossary ↔ evidence/graph reconciliation  (Phase 10)
glossabet install       install canonical agent skill             (Phase 17)
```

Users normally never type these — the skill orchestrates them.

## The Graphify loop (doctrine, not a phase)

- **Pass 1** (`/graphify .`) produces structure with throwaway labels.
- Glossabet consumes it via the adapter; the human settles vocabulary.
- **Reconciliation needs no second Graphify pass** — Glossabet overlays the
  glossary on the existing graph itself (Phase 10).
- A second Graphify pass has exactly one remaining job: making Graphify's own
  outputs (wiki, HTML, `explain`/`path` queries) speak canonical vocabulary.
  Today that works only at the instruction level (Graphify's naming step is
  agent-driven; direct the agent to name communities from `GLOSSARY.md`,
  inventing names only where no term fits, flagging those). Graphify has no
  `--glossary` flag as of 0.9.42; if one appears upstream, adopt it.
- Reconciliation never assumes one community = one concept. A concept may span
  modules; a module may implement several concepts; a boundary may live in
  edges, not nodes; a community may be an implementation detail deserving no
  name. Mismatch reports are evidence with confidence, not verdicts.

## Phases

Phases 0–10 are complete (2026-08-14). Their full step detail and acceptance
criteria are archived verbatim in `PLAN-ARCHIVE.md`.

- **Phase 0 — Bootstrap** ✅ 2026-08-14 → archived in PLAN-ARCHIVE.md
- **Phase 1 — Package and CLI skeleton** ✅ 2026-08-14 → archived in PLAN-ARCHIVE.md
- **Phase 2 — Lexical scanner and RepositoryEvidence v1** ✅ 2026-08-14 → archived in PLAN-ARCHIVE.md
- **Phase 3 — Evidence-aware skill** ✅ 2026-08-14 → archived in PLAN-ARCHIVE.md
- **Phase 4 — Terminology intelligence** ✅ 2026-08-14 → archived in PLAN-ARCHIVE.md
- **Phase 5 — Import edges and importance signals** ✅ 2026-08-14 → archived in PLAN-ARCHIVE.md
- **Phase 6 — Persistent glossary** ✅ 2026-08-14 → archived in PLAN-ARCHIVE.md
- **Phase 7 — Drift and collision detection** ✅ 2026-08-14 → archived in PLAN-ARCHIVE.md
- **Phase 8 — Incremental indexing** ✅ 2026-08-14 → archived in PLAN-ARCHIVE.md
- **Phase 9 — Graphify adapter** ✅ 2026-08-14 → archived in PLAN-ARCHIVE.md
- **Phase 10 — Reconciliation and bindings** ✅ 2026-08-14 → archived in PLAN-ARCHIVE.md

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
     "symlink-escapes-repository" | "not-a-regular-file" | "oversized" |
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
`skipped_terms`, `complete`, and the 2,000-term cap. `inspect` attaches it as
`repository_glossary.divergence` and `validate` (schema 7 → 8) stores it under
`repository_glossary` and prints it — both only when structured state exists
and the Markdown was read completely; otherwise the key is absent. Proposed
concepts are never checked. Nine new tests: positive/negative for both lists,
Unicode fold parity (ß / ligature), cap-and-say-so, presence only in the
both-and-readable case through `inspect`, `validate` output and JSON,
unreadable named, quiet on agreement. Skill *Managed* section names the
field and its limits; README, ARCHITECTURE, CHANGELOG updated; plugin
regenerated. Suite 450 passed; all per-commit gates green.

### Open bughunt deferrals (2026-08-17)

Three items from the whole-project bughunts were deliberately not fixed;
each names the evidence or ruling that settles it:

1. **Safety-failure permanence needs Kyle's ruling.** One live run whose
   agent leaves a stray file in a disposable scenario fixture records
   `safety_pass: false` in the append-only `evaluation/agent-history.json`,
   which fails `--verify-results` permanently with no supported recovery
   (hand-editing committed history is the only remedy). Procedural failures
   are deliberately retained without gating; whether fixture-scoped safety
   failures should gate forever, gate until a later clean run, or offer an
   explicit supersede path is an intended-behavior question, not a silent
   fix.
2. **Codex `plugin list --json` key schema needs one live observation.**
   The evaluator's guards now match both `name` and `pluginId` spellings
   defensively, but which key the CLI actually emits was not observable
   without an authenticated Codex run; one `codex plugin list --json` with
   a plugin installed settles it.
3. **Multi-turn Codex usage semantics need live evidence.** `_run_codex`
   takes the last `turn.completed` event's usage; if a single exec can emit
   several turns (compaction) and usage is per-turn rather than cumulative,
   totals undercount. Settling requires a live multi-turn JSONL sample;
   guessing a summation risks double-counting cumulative values.

### Bughunt round 3 (2026-08-17) — latent items, judged not-live, not fixed

The plural-acronym tokenizer bug found this round was fixed. These remaining
items are surfaced but were deliberately not fixed because none produces wrong
output today; recorded so a future bughunt does not re-discover them cold:

1. **`importance.py` and `terminology.py` disagree on an untagged token.**
   `importance.py:80` drops a token whose origin is unknown (`!= DOMAIN`),
   while `terminology.py:486` treats an untagged token *as* domain
   (`.get(term, TOKEN_ORIGIN_DOMAIN)`). Currently unreachable: `evidence.py`
   populates `token_origins` in lockstep with `token_counts`, so no token is
   ever untagged. Latent inconsistency, not a live bug. Cheap consistency fix
   available (make importance use the same default) if a future source can
   inject an untagged token.
2. **`totals.source_bytes` vs `totals.source_files` count different
   populations** when a file is reclassified binary mid-read (`evidence.py`
   ~497): `source_files` is an inventory count, `source_bytes` mirrors the
   decremented read-budget. Each is individually correct; only misleads a
   consumer computing bytes-per-file across the two. The doc side and
   `code_bytes` share the pattern. Best addressed by documenting the two
   denominators rather than changing the numbers.

Minor non-bugs also noted and dropped: a dead sub-condition in the
workspace-manifest hidden-file skip (`scanner.py:370`, provably no effect),
and three cosmetic wording nits (install message agent word, empty-file
"appended" vs "created", brief output on a zero-canonical glossary).

### Test-audit round 1 (2026-08-17) — deferred items (await Kyle's ruling)

Two proven gaps were fixed this session (EDGE_CAP/EXTERNAL_CAP truncation
counts now asserted exactly in `test_edge_and_external_caps_report_exact_truncation_counts`;
glob-in-config-path rejection now guarded by
`test_glob_in_a_config_path_is_a_user_error_not_a_literal_prefix`). These
remain open, left in place pending a decision:

1. **`test_parallel_term_scope_checks_are_bounded_against_a_hostile_glossary`
   (test_drift.py:519) is proven vacuous — recommend deletion.** Its fixture
   produces zero synonym candidates, so the scope-overlap path it claims to
   bound is never entered; its only assertion is a loose `< 15s` timer that
   survives disabling the comparison budget entirely. The budget invariant is
   genuinely guarded by `test_parallel_term_budget_charges_prefix_pair_work_not_owner_count`
   (added round 3). Left in place because deleting a test waits for the owner.
2. **`test_glossabet_routine_context_fits_the_soft_target`
   (test_agent_context.py:190) is fragile.** It scans the *live* repository and
   asserts the projection is <= 80,000 bytes, so it is coupled to repo growth
   and will silently start failing as the codebase grows, passing today for
   reasons unrelated to the projection-bounding logic. It doubles as a
   dogfooding check, so it was not changed; pin it to a synthetic fixture repo
   if a pure unit test is wanted.
3. Minor weak assertions left in place (real bound covered elsewhere):
   `test_bounds_are_reported` (test_terminology.py:208, presence-only; the
   151st-token test is the real guard) and `test_scope_shape_rejects_ambiguous_or_nonliteral_paths`
   (test_glossary.py:195, asserts *some* error, not which).

### Owner self-testing pause — active, not an implementation phase

Kyle is keeping the current build to himself while he runs it and performs
additional checks. While this pause is active, do not invite maintainers,
collect outside alpha evidence, begin Phase 23, or perform publication setup.
Only Kyle's explicit instruction to resume outside testing ends the pause.

### Trusted-alpha gate — external evidence, not an implementation phase

Before Phase 23, and only after Phases 24–28 are complete — outside testers
should meet corrected signals, not re-report the known self-testing findings
— invite at least two consenting maintainers to use the exact installed build on enough additional repositories to bring the measured total
to at least five varied repositories. Record opt-in scope, repository traits,
failures, false alarms, usefulness feedback, and the exact build tested; never
copy private repository content into this repository. This gate necessarily
waits on humans and is not treated as a single `$next` implementation pass.

### Phase 23 — Exact-artifact release candidate gate

**Goal:** prove one immutable source state and its built artifacts after the
trusted-alpha gate, without publishing them.

**Steps:**

1. Rerun installed-agent scenarios, deterministic evaluation, the full CI
   matrix, workflow-policy tests, and wheel/sdist smoke tests from one clean
   source commit; record artifact hashes and version coupling.
2. Verify license inclusion, metadata, links, clean install, upgrade,
   uninstall, and plugin fallback behavior against those exact artifacts.
3. Produce a release-candidate report that separates proven local behavior,
   measured alpha evidence, known limitations, and every remaining external
   action.

**Acceptance:** all evidence names the same source commit and artifact hashes;
the source tree is clean; no unresolved critical/high correctness or security
finding remains; the report contains no unmeasured efficacy or availability
claim.

### External publication gate — explicit authorization required

The hosted GitHub repository rename is complete. GitHub private vulnerability
reporting, Dependabot security updates, package registration/upload, Git
tags/releases, and plugin-directory publication remain account or public-state
changes. They are covered work, but are performed only after Phase 23 and only
with Kyle's explicit authorization. Any steps Kyle must perform are presented
one at a time with the account affected, public or irreversible consequence,
exact click/type action, and observable completion state. Publication is not
done merely because local gates pass.

## Post-audit issue closure map

| Verified issue or release gap | Closure |
| --- | --- |
| Skill directly reads/writes artifacts and can bypass the engine | Phase 18.1–18.2 |
| Glossary validation can grow quadratically and diagnostics are unbounded | Phase 18.3; downstream work Phase 19.4 |
| Repository-controlled terminal text can carry control sequences | Phase 18.4 |
| Terminology/structure caps can conceal omitted candidates | Phase 19.1–19.2 |
| Graphify matching ignores members after the six-item sample | Phase 19.3 |
| Graphify provenance uses permissive substring/suffix matching | Phase 19.3 |
| Unknown glossary fields are silently accepted | Phase 18.3 |
| Checked-in evaluation results predate the current engine | Phase 20.3 |
| Release workflow does not depend on the full test matrix | Phase 20.1 |
| Workflow tests protect labels more than gate semantics | Phase 20.1 |
| Actual installed-agent behavior is not end-to-end tested | Phase 22.2 |
| Structural findings lack a labelled evaluation set | Phase 22.1 |
| Outside adopter evidence is too small for broad claims | Trusted-alpha gate |
| Product/package/plugin name needs clearance before publication | Phase 21.1 |
| Preferred Codex plugin distribution and version coupling are unproven | Phase 21.2–21.3 |
| Build backend is unconstrained | Phase 20.2 |
| GitHub private reporting and dependency security updates are disabled | External publication gate |
| Release documentation overstates the current stopping point | Phase 20.4 and Phase 23.3 |
| Healthy foundations—full tests, CI matrix, wheel smoke, license, research links, pytest, and zero runtime dependencies—must not regress | Acceptance gates in Phases 18–23 |

## Self-testing findings closure map (2026-08-15)

Each finding was verified against the engine's own output on this repository.

| Verified finding | Closure |
| --- | --- |
| Language builtins consume terminology's top-150 budget and naming slots | Phase 24 |
| Prose and builtin spellings corrupt the reported house register (55.4% flat / 66.2% one-word on a snake_case multi-word repo); no evaluation measured register accuracy | Phase 25 |
| Naming candidates rank raw frequency: `json`, `path`, `file`, `name`, `run`, `root`; importance never consults overload dispersion | Phase 26 |
| Agent context is 552 KB for 73 files (~90% vocabulary, 161 KB location lists); the 1 MB limit is a ceiling, not a budget | Phase 27 |
| The glossary reaches agents only inside `/glossabet` naming sessions; ordinary sessions re-invent vocabulary that lands as drift | Phase 28.1–28.3 |

### Later / unscheduled
- Graphify pass-2 relabeling guide (instruction-level recipe as a doc);
  upstream `--glossary` contribution to Graphify if welcomed.
- External fact (2026-08-14): Graphify 0.9.42 (latest on PyPI and GitHub
  main) silently ignores OCaml (`.ml`/`.mli` absent from its
  CODE_EXTENSIONS; unknown extensions dropped). Its owner told Kyle OCaml
  "should work now," but no OCaml support exists in any public release,
  branch, PR, or issue as of this date — verify before any combined
  glossabet+graphify run on an OCaml repo.
- Cross-repo / organization-wide vocabulary (design `glossary.json` so a
  shared mode isn't precluded; graphify `merge-graphs` is prior art).
- Additional evidence adapters (LSP, other analyzers).
- Public package/plugin publication only after Phase 23, the trusted-alpha
  gate, and explicit authorization.

## Settled decisions (through 2026-08-16)

1. **Implementation language: Python.** Same distribution story as Graphify
   (`uv tool install`), mature ecosystem if tree-sitter is ever wanted.
2. **Skill source of truth: the repo.** `skill/SKILL.md` is canonical and is
   mapped byte-for-byte into the wheel. `glossabet install` defaults to the
   current Codex personal location `~/.agents/skills/glossabet/`; the
   explicit Claude Code target is `~/.claude/skills/glossabet/`. Both are
   installed copies. The original prediction that the skill would change only
   twice was invalidated by the post-Phase-17 boundary audit: Phase 18 changes
   the evidence transport from direct artifact reads to a required CLI-owned
   context. The philosophy remains untouched.
3. **Public, Apache-2.0** — matching Graphify (verified: Graphify is
   Apache-2.0, not MIT).
4. **Test framework: pytest** (dev-only dependency; cost accepted for
   convention and fixtures).
5. **Runtime dependencies: stdlib-only through Phase 5** (argparse over
   click, no yaml); revisit per-phase under principle 9.
6. **Monorepo handling: alert only.** Detection in the scanner (Phase 2),
   pause-and-ask in the skill (Phase 3). No subagent fan-out.
7. **Terminology embeds in `evidence.json`** (Phase 4) — no sibling
   artifact, so the skill's existing evidence protocol covers it with no extra
   skill change; `analyze` = scan + human-readable report.
8. **Cache invalidation changed after adversarial verification.** Phase 8 used
   per-file `mtime_ns` + size in a repository-local cache. A direct 2026-08-14
   probe proved a hostile repository could pre-seed matching metadata and
   fabricated extraction results. Phase 11 replaces that trust decision with
   a user-owned, repository-keyed cache and current-content digests.
9. **Concept scopes are literal path regions.** An omitted glossary scope is
   repository-wide; `scope.path_prefixes` names one or more literal
   repository-relative subsystem regions. Aliases inherit scope, and
   NFKC-casefolded vocabulary ownership must be unique wherever regions
   overlap. Drift and lexical reconciliation enforce the same boundary.
10. **Unicode remains lexical; no parser dependency.** Phase 16's NFKC,
    casefold, acronym/digit, and language-form implementation passes all 15
    new lexical labels without a parser. The measured Tree-sitter candidate
    adds native wheels, runtime grammar downloads/cache state, and maintenance
    without a remaining labelled accuracy gain, so the runtime stays stdlib-
    only. `EVALUATION.md` records the exact cost snapshot and reconsideration
    rule.
11. **Release automation prepares but does not publish.** CI tests CPython
    3.10–3.14 on Linux, macOS, and Windows and smoke-tests the built wheel.
    The PyPI workflow is manual-only, tag/confirmation/environment gated, and
    uses Trusted Publishing without a stored token. PyPI account setup,
    package upload, Git tags/releases, and enabling GitHub private
    vulnerability reporting remain explicit external actions for Kyle.
12. **Product identity: Glossabet.** Source and executable surfaces use the
    selected coinage; `NAME-CLEARANCE.md` records the bounded checks and their
    legal/availability limits. The Codex plugin is the preferred future Codex
    route and owns its skill plus bundled wheel as one cache entry. The
    standalone wheel owns the normal CLI environment and keeps its separately
    copied skill lifecycle explicit. Only Codex CLI 0.147.0 on Linux has direct
    plugin lifecycle and 12-scenario installed-host probes; other hosts remain
    unverified.
13. **Evidence may lag; it may never lie (Phase 29, Kyle, 2026-08-16).**
    Committed evaluation evidence is sealed, fingerprinted testimony about
    the state it measured. Per-commit gates verify only genuineness
    (untampered, internally consistent); currency against the current tree
    is enforced solely at the release gate via `--current` and the plugin
    `git diff` step. Development — refactors included — never requires
    regenerating witness evidence; releases always do. Extended 2026-08-16
    at Kyle's direction: the checked-in Codex plugin (including its bundled
    wheel) follows the same rule — `check_distribution.py` validates its
    currency only under `--current`, so engine edits no longer require a
    per-commit plugin rebuild; the release gate and `RELEASING.md` demand
    the rebuild instead.
