# Glossarize — Plan

Status: **all planned phases (0–10) complete** as of 2026-08-14; remaining
work lives in "Later / unscheduled".
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

All planned phases are complete (2026-08-14), each sized for one correct pass
ending with an acceptance check and a commit naming the phase. Full step
detail and acceptance criteria are archived verbatim in `PLAN-ARCHIVE.md`.

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

### Later / unscheduled
- Graphify pass-2 relabeling guide (instruction-level recipe as a doc);
  upstream `--glossary` contribution to Graphify if welcomed.
- External fact (2026-08-14): Graphify 0.9.42 (latest on PyPI and GitHub
  main) silently ignores OCaml (`.ml`/`.mli` absent from its
  CODE_EXTENSIONS; unknown extensions dropped). Its owner told Kyle OCaml
  "should work now," but no OCaml support exists in any public release,
  branch, PR, or issue as of this date — verify before any combined
  glossarize+graphify run on an OCaml repo.
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
7. **Terminology embeds in `evidence.json`** (Phase 4) — no sibling
   artifact, so the skill's existing evidence protocol covers it with no extra
   skill change; `analyze` = scan + human-readable report.
8. **Cache invalidation: per-file `mtime_ns` + size** (Phase 8) — uniform, not
   git-diff; robust across tracked/untracked/dirty states. Whole-cache
   invalidation on a generator-version change.
