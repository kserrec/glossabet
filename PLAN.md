# Glossarize — Plan

Status: **phases 0–17 complete** as of 2026-08-14.
Phases 11–17 turn the 2026-08-14 deep-dive findings into bounded,
single-pass work.
This document is the authoritative roadmap. Provenance: merged from the working
sessions of 2026-08-14 — Claude's loop/reconciliation analysis, ChatGPT's
"Robust Repository Vocabulary System" spec and repo-transition notes, and the
existing `/glossarize` skill, which is the behavioral spec this project serves.

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

Glossarize makes a repository's vocabulary **explicit, canonical, inspectable,
and maintainable**. It is a software system whose primary interface is the
`/glossarize` agent skill: deterministic machinery gathers evidence, the LLM
brainstorms and reasons about terminology, and **the human decides**. That
division of labor is the product's central rule and never changes.

Optionally, Glossarize consumes [Graphify](https://github.com/Graphify-Labs/graphify)
output as richer structural evidence. Graphify answers "what is connected to
what?"; Glossarize answers "what are these things conceptually, and what should
we call them?" Together they can ask: does the vocabulary we use to understand
this system correspond to the system we built? **Graphify is never required.**

## Product shape

```
┌─────────────────────────────────────────────┐
│  /glossarize agent skill  (the UX)          │
│  nominates, proposes, brainstorms, defers   │
│  to the human; finalizes only when told     │
└───────────────────┬─────────────────────────┘
                    │ reads evidence when present,
                    │ falls back to direct repo reading
┌───────────────────▼─────────────────────────┐
│  glossarize engine / CLI  (deterministic)   │
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

Both evidence sources normalize into one Glossarize-owned intermediate
representation, **RepositoryEvidence**. Everything above that boundary is
source-agnostic; future adapters (LSP, other analyzers) plug in the same way.

## Principles (all binding)

1. **The human names the world.** Machinery nominates and grounds; the LLM
   proposes and reasons; only human approval makes a term canonical. Glossarize
   never mass-renames code and never finalizes unilaterally.
2. **Lexical-first scanner identity.** The built-in scanner is *the lexical
   evidence provider*: files, directories, docs inventory, identifier
   vocabulary, plus cheap best-effort import edges. It never grows into a
   static analyzer or a Graphify clone. When rich structure matters, an
   adapter supplies it. Full symbol extraction (tree-sitter et al.) is
   deferred until real use proves it necessary — it may never be.
3. **No evidence contamination.** The scanner excludes `glossarize-out/`,
   `.glossarize/`, and the repo's `GLOSSARY.md` from evidence gathering, from
   v0.1 on. Otherwise the glossary echoes through the evidence and blinds
   drift detection (canonical terms look "used" because the glossary uses
   them). Adapter-provided evidence tags glossary-derived nodes by provenance
   and discounts them in reconciliation.
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
   it. Never mutate Graphify's artifacts — Glossarize owns
   `glossarize-out/`, Graphify owns `graphify-out/`. Native Graphify support
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
    Glossarize honest on repos of any size.

## Non-goals

Glossarize is not: an automatic renamer, a static analyzer or language server,
a dependency visualizer, a generic architecture-doc generator, a Graphify
clone, or an ontology generator that removes human judgment. Structural
sophistication belongs to adapters, not the core.

## Artifacts

```
<scanned repo>/
├── glossarize.json       optional literal-prefix ignore/path-role configuration
├── glossarize-out/
│   ├── evidence.json     machine evidence (RepositoryEvidence, schema_version, git stamp)
│   ├── glossary.json     machine-readable canonical vocabulary (from Phase 6)
│   └── (analysis outputs as later phases add them)
└── GLOSSARY.md           human artifact at repo root, format per skill Step 6
```

The incremental extraction cache is user-owned state outside the scanned
repository, under the platform cache directory and keyed by the repository's
resolved path. Repository-local `.glossarize/` remains excluded as a legacy
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
glossarize scan .        build/refresh RepositoryEvidence          (Phase 2)
glossarize analyze .     terminology + register analysis           (Phase 4)
glossarize show          display current glossary                  (Phase 6)
glossarize drift .       compare live vocabulary vs canonical      (Phase 7)
glossarize validate .    glossary ↔ evidence/graph reconciliation  (Phase 10)
glossarize install       install canonical agent skill             (Phase 17)
```

Users normally never type these — the skill orchestrates them.

## The Graphify loop (doctrine, not a phase)

- **Pass 1** (`/graphify .`) produces structure with throwaway labels.
- Glossarize consumes it via the adapter; the human settles vocabulary.
- **Reconciliation needs no second Graphify pass** — Glossarize overlays the
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
   state plainly that this validates the problem, not Glossarize's efficacy.
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
   Glossarize-owned generated paths while preserving all user changes.
2. Use the same comparison in artifact stamps and the skill's freshness gate;
   cover tracked, untracked, ignored, and no-git repositories.
3. Document generated-file ownership and cleanup without modifying
   `.gitignore` automatically.

**Acceptance:** a first scan of a clean repository is immediately fresh;
subsequent user changes make it stale; generated Glossarize artifacts alone do
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

**Goal:** learn whether Glossarize is useful before expanding or marketing its
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

**Acceptance:** the README can cite a reproducible Glossarize evaluation—or
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

1. Add `glossarize install` for the canonical skill, an end-to-end sample
   walkthrough, and explicit privacy/data-flow documentation for local and
   agent-mediated use.
2. Add CI across supported Python versions and platforms, packaging checks,
   changelog/release metadata, and a reproducible smoke test from built wheel.
3. Prepare—not perform—PyPI publication and public security-reporting steps;
   actual account use and publication require Kyle's explicit authorization.

**Acceptance:** a clean environment can install the built artifact, run the
walkthrough, execute the full suite, and uninstall cleanly; release docs state
exactly what remains manual and externally visible.

### Later / unscheduled
- Graphify pass-2 relabeling guide (instruction-level recipe as a doc);
  upstream `--glossary` contribution to Graphify if welcomed.
- External fact (2026-08-14): Graphify 0.9.42 (latest on PyPI and GitHub
  main) silently ignores OCaml (`.ml`/`.mli` absent from its
  CODE_EXTENSIONS; unknown extensions dropped). Its owner told Kyle OCaml
  "should work now," but no OCaml support exists in any public release,
  branch, PR, or issue as of this date — verify before any combined
  glossarize+graphify run on an OCaml repo.
- Cross-repo / organization-wide vocabulary (design `glossary.json` so a
  shared mode isn't precluded; graphify `merge-graphs` is prior art).
- Additional evidence adapters (LSP, other analyzers).
- PyPI publication after Phase 17 and explicit authorization.

## Settled decisions (2026-08-14)

1. **Implementation language: Python.** Same distribution story as Graphify
   (`uv tool install`), mature ecosystem if tree-sitter is ever wanted.
2. **Skill source of truth: the repo.** `skill/SKILL.md` is canonical and is
   mapped byte-for-byte into the wheel. `glossarize install` defaults to the
   current Codex personal location `~/.agents/skills/glossarize/`; the
   explicit Claude Code target is `~/.claude/skills/glossarize/`. Both are
   installed copies. The skill itself
   changes only twice, additively: the evidence protocol (Phase 3) and
   glossary resumption (Phase 6). Philosophy untouched.
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
