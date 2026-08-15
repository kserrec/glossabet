# Glossabet — Plan

Status: **phases 0–22 complete; phases 24–28 (owner self-testing findings)
are the next implementation work; owner self-testing pause active before the
trusted-alpha gate** as of 2026-08-15. Phases 18–23 are the complete
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
moved from `/home/serrecchia/Projects/glossarize` to
`/home/serrecchia/Projects/glossabet`. GitHub's old repository path was
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
27 independently, 28 after 27. All five must complete before the
trusted-alpha gate.

### Phase 24 — Language/domain vocabulary partition

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

### Phase 25 — Register integrity

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

### Phase 26 — Nomination distinctiveness

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

### Phase 27 — Lean agent context

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

### Phase 28 — Ambient glossary consumption

**Goal:** after one finalized naming session, agents in every later session
read the canonical vocabulary with no user invocation — consumption becomes
ambient while changing vocabulary stays human-gated. (Depends on Phase 27.
This is the product's steady state: ambient read, human-authorized write.)

**Steps:**

1. `glossabet brief`: a deterministic digest of `glossary.json` (canonical
   terms, one-line definitions, scopes, aliases) bounded at 4 KB with the
   git stamp included. Staleness rules apply in full: the digest names the
   glossary state it renders.
2. Primary channel: the plugin ships a session-start hook that runs `brief`
   fresh in each session — fresh by construction, no repository mutation.
3. Fallback channel: `glossabet sync-context`, an explicit human-invoked
   command that writes a stamped managed block into `CLAUDE.md`/`AGENTS.md`
   for hosts without hooks. Never written unbidden; `drift` and `validate`
   flag a stale block.
4. Document the boundary in the skill and README: the ambient layer is
   read-only consumption; nominating, coining, and finalizing vocabulary
   still require a human `/glossabet` session. Rendered digest text follows
   the Phase 18.4 terminal-safety rules for repository-controlled content.

**Acceptance:** a fresh agent session with the hook installed sees the
canonical terms without any user mention of glossabet; no code path writes
to user-owned files without an explicit human command; a stale sync block is
flagged by drift/validate; brief output is deterministic, bounded, and
covered by the no-contamination and no-secrets tests.

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
| The glossary reaches agents only inside `/glossabet` naming sessions; ordinary sessions re-invent vocabulary that lands as drift | Phase 28 |

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

## Settled decisions (through 2026-08-15)

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
    plugin lifecycle and 11-scenario installed-skill probes; other hosts remain
    unverified.
