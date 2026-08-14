# Glossarize — Plan

Status: **pre-implementation** (Phase 0 complete, Phase 1 not started).
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
├── glossarize-out/
│   ├── evidence.json     machine evidence (RepositoryEvidence, schema_version, git stamp)
│   ├── glossary.json     machine-readable canonical vocabulary (from Phase 6)
│   └── (analysis outputs as later phases add them)
├── .glossarize/          incremental cache (Phase 8)
└── GLOSSARY.md           human artifact at repo root, format per skill Step 6
```

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

Each phase is sized for one correct pass and ends with its acceptance check
and a commit naming the phase.

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

### Phase 3 — Evidence-aware skill
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

### Phase 4 — Terminology intelligence
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

### Phase 5 — Import edges and importance signals
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

### Phase 6 — Persistent glossary
Steps:
1. `glossary.json` minimal schema (see Artifacts) with status lifecycle;
   writer/reader in the engine; `glossarize show`.
2. Skill finalize step (Step 6) writes both `GLOSSARY.md` (existing format,
   unchanged) and `glossary.json`; only human-settled terms get `canonical`.
3. Skill startup reads an existing glossary and never restarts the brainstorm
   from scratch: canonical terms are respected, open items resume.
Acceptance: settle a small vocabulary on a test repo, rerun `/glossarize`,
confirm it resumes rather than restarts.

### Phase 7 — Drift and collision detection
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

### Phase 8 — Incremental indexing
Steps:
1. `.glossarize/` cache keyed on git state; `scan` updates only changed files
   (git diff against the stamped HEAD, falling back to mtimes when unstamped).
2. Cache correctness test: incremental result identical to cold scan.
Acceptance: on a large repo, warm `scan` touches only changed files and
matches a cold scan byte-for-byte.

### Phase 9 — Graphify adapter
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

### Phase 10 — Reconciliation and bindings
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

### Later / unscheduled
- Graphify pass-2 relabeling guide (instruction-level recipe as a doc);
  upstream `--glossary` contribution to Graphify if welcomed.
- `glossarize install` (skill copier following Graphify's platform pattern).
- Cross-repo / organization-wide vocabulary (design `glossary.json` so a
  shared mode isn't precluded; graphify `merge-graphs` is prior art).
- Additional evidence adapters (LSP, other analyzers).
- PyPI publication.

## Settled decisions (2026-08-14)

1. **Implementation language: Python.** Same distribution story as Graphify
   (`uv tool install`), mature ecosystem if tree-sitter is ever wanted.
2. **Skill source of truth: the repo.** `skill/SKILL.md` is canonical;
   `~/.claude/skills/glossarize/` is an installed copy. The skill itself
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
