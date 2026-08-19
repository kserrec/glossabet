# Glossabet — Plan

Status: **Phases 0–22, 24–32, 34–44 complete (36.8, live
post-approval skill scenarios, planned); Phase 33 (Claude Code ambient parity)
in progress at 33.2; owner self-testing pause active before the trusted-alpha
gate** as of 2026-08-18.
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
   proposes and reasons; a term is meant to become canonical only after human
   approval. Glossabet never mass-renames code. **How this is enforced, stated
   honestly:** the rule is a behavioral instruction to the agent — the skill
   is written to persist only human-confirmed terms and to invoke
   `sync-context` only on explicit request — not a mechanical guarantee. The
   CLI's `save` command validates structure and budgets and trusts its caller;
   it cannot tell whether the agent piping to it really obtained approval.
   Docs must therefore say "the skill is instructed to…", never "Glossabet
   cannot…", about human approval (decided 2026-08-17).
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
glossabet cache-clear   remove Glossabet's own user cache          (Phase 37)
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

Completed phases are archived verbatim in `PLAN-ARCHIVE.md` (Phases 0–10 on
2026-08-14; Phases 11–32, 33.1, 34, 35, and 36.1–36.7 on 2026-08-18) and
leave one pointer line each here. Live work keeps its full text.

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

- **Phase 11 — Research grounding and hostile-repository boundaries ✅ 2026-08-14** → archived in PLAN-ARCHIVE.md

- **Phase 12 — Real Graphify interoperability and validation honesty ✅ 2026-08-14** → archived in PLAN-ARCHIVE.md

- **Phase 13 — Honest git freshness and artifact lifecycle ✅ 2026-08-14** → archived in PLAN-ARCHIVE.md

- **Phase 14 — Terminology precision foundations ✅ 2026-08-14** → archived in PLAN-ARCHIVE.md

- **Phase 15 — Evaluation corpus and calibration ✅ 2026-08-14** → archived in PLAN-ARCHIVE.md

- **Phase 16 — Scoped vocabulary and language semantics ✅ 2026-08-14** → archived in PLAN-ARCHIVE.md

- **Phase 17 — Distribution and release readiness ✅ 2026-08-14** → archived in PLAN-ARCHIVE.md

- **Phase 18 — Agent boundary and hostile glossary/input hardening ✅ 2026-08-14** → archived in PLAN-ARCHIVE.md

- **Phase 19 — Completeness and downstream complexity accounting ✅ 2026-08-14** → archived in PLAN-ARCHIVE.md

- **Phase 20 — Release automation and evidence integrity ✅ 2026-08-14** → archived in PLAN-ARCHIVE.md

- **Phase 21 — Name clearance and preferred Codex distribution ✅ 2026-08-15** → archived in PLAN-ARCHIVE.md

- **Phase 22 — Installed-agent and structural evaluation ✅ 2026-08-15** → archived in PLAN-ARCHIVE.md

- **Repository identity and exact-artifact update — completed 2026-08-15 (repo renamed to kserrec/glossabet with authorization; identity function excludes interpreter caches and sorts POSIX paths; four post-Phase 22 batches 11/11)** → archived in PLAN-ARCHIVE.md

- **Phases 24–28 — Self-testing quality findings (added 2026-08-15): the five owner-found defects that Phases 24–28 fixed, with their originating measurements** → archived in PLAN-ARCHIVE.md

- **Phase 24 — Language/domain vocabulary partition ✅ 2026-08-15** → archived in PLAN-ARCHIVE.md

- **Phase 25 — Register integrity ✅ 2026-08-15** → archived in PLAN-ARCHIVE.md

- **Phase 26 — Nomination distinctiveness ✅ 2026-08-15** → archived in PLAN-ARCHIVE.md

- **Phase 27 — Lean agent context ✅ 2026-08-16** → archived in PLAN-ARCHIVE.md

- **Phase 28 — Ambient glossary consumption ✅ 2026-08-16 (28.1 brief digest, 28.2 session-start hook, 28.3 sync-context managed block; the 28.3 exact-artifact retry passed 12/12, raw run `20260816T193824Z-full-f7879d5e.json`; the earlier `wc -l` miss stays in the reliability ledger)** → archived in PLAN-ARCHIVE.md

- **Phase 29 — Decouple evidence currency from development ✅ 2026-08-16 (Kyle's decision; the two-mode genuineness/currency contract is Settled decision 13 below)** → archived in PLAN-ARCHIVE.md

- **Phases 30–32 — Pre-existing `GLOSSARY.md` adoption and reconciliation (added 2026-08-17): origin (Kyle's spec), the trust hazard it removed, and the design decisions the three phases implement** → archived in PLAN-ARCHIVE.md

- **Phase 30 — Repository-glossary discovery and context channel ✅ 2026-08-17** → archived in PLAN-ARCHIVE.md

- **Phase 31 — Skill: independent-first, adoption, managed-mode divergence, safe finalization ✅ 2026-08-17** → archived in PLAN-ARCHIVE.md

- **Phase 32 — Deterministic managed-mode term-presence check ✅ 2026-08-17** → archived in PLAN-ARCHIVE.md

- **Bughunt of Phases 30–32 (2026-08-17) — three findings, all fixed** → archived in PLAN-ARCHIVE.md

- **Bughunt round 2 of Phases 30–32 (2026-08-17) — two findings, both fixed** → archived in PLAN-ARCHIVE.md

- **Audit of Phases 30–32 (2026-08-17) — three findings, all fixed** → archived in PLAN-ARCHIVE.md

- **Audit round 2 of Phases 30–32 (2026-08-17) — three findings, all fixed** → archived in PLAN-ARCHIVE.md

### Test-audit proposals for the Phase 30–32 tests (2026-08-17) — await Kyle's ruling

Left in place; none is proven vacuous, so deletion/weakening waits for a
ruling. All three trim runtime or wall-clock fragility, nothing else.

1. Delete `test_divergence_worst_case_is_bounded_in_time` — its cap
   assertions duplicate `test_divergence_caps_its_work_and_says_so`; its
   only unique claim is a `< 10 s` wall-clock ceiling (a constant-factor
   canary that is also the classic CI-noise test).
2. Drop the secondary `elapsed < 5` assertion from
   `test_divergence_guard_fires_before_casefold_and_collapse_allocate`; the
   deterministic `tracemalloc` peak assertion is the proof of the claim.
3. Merge that test with
   `test_divergence_guard_fires_on_nfkc_expansion_before_any_search` (same
   2 MB bomb built twice, ~1 s each; different claims, so a merge not a
   deletion).

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

### Phase 33 — Claude Code ambient parity (added 2026-08-17)

**Goal:** the ambient-consumption steady state of Phase 28 works for Claude
Code exactly as it does for Codex, from the one simple command a user already
runs. After `glossabet install --agent claude`, every later Claude Code
session in a repository with a finalized glossary reads the canonical
vocabulary at startup, resume, clear, and compaction with no user mention of
Glossabet — same `brief` payload, same "no glossary → nothing added" rule,
same human-gated writes. (Depends on Phase 28. Kyle, 2026-08-17: "users
should be able to just run the simple glossabet query for it to work for
both.")

**Why this was a gap, not a decision.** Phase 21 chose the Codex plugin as
the preferred distribution route and Phase 28.2 built the session-start hook
into that plugin's manifest. The "do not advertise unsupported host behavior"
rule then kept Claude Code labelled *unverified*, but no phase ever scheduled
the Claude Code equivalent. The mechanism is not Codex-specific: `brief` is
host-agnostic and Claude Code has the same `SessionStart` lifecycle event.

**Host facts this phase relies on (Claude Code 2.1.234, official docs,
verified 2026-08-17):**

- Any folder under a skills directory that contains
  `.claude-plugin/plugin.json` is loaded as plugin `<name>@skills-dir` on the
  next session — no marketplace, no install step, no copy into a plugin
  cache; deleting the folder removes it. Under `~/.claude/skills/` (personal
  scope) it loads in every project with none of the project-scope trust
  restrictions. `claude plugin init` scaffolds exactly this shape and keeps
  the folder's own root `SKILL.md` as a skill via `"skills": ["./"]`.
- Plugin hooks live at `hooks/hooks.json` under the plugin root (default
  discovery; a manifest `hooks` field pointing at the same file would load it
  twice, so the manifest omits it). `SessionStart` matchers are `startup`,
  `resume`, `clear`, `compact`, `fork`; a command hook's plain stdout on exit
  0 becomes context the model sees; stdout is capped at 10,000 characters
  (`brief` is bounded at 4,096 bytes); `timeout` is in seconds;
  `statusMessage` is supported; `commandWindows` and `additionalContextLimit`
  are Codex fields with no Claude Code meaning. Non-zero exit shows stderr to
  the user as a non-blocking notice and the session proceeds — a broken hook
  is loud, never silent.
- `claude plugin validate <dir>` validates a plugin folder offline.
- SessionStart hooks fire in headless (`claude -p`) sessions, so a live
  probe can be scripted like the Codex batches.

**Design (binding for the sub-phases):**

- The Claude Code personal install directory `~/.claude/skills/glossabet/`
  — already the only user-state path `install --agent claude` writes —
  becomes a skills-directory plugin: `SKILL.md` (unchanged path),
  `.claude-plugin/plugin.json` (`name`, `version` = package version,
  `description`, `skills: ["./"]`, author/homepage/license as in the Codex
  manifest), and `hooks/hooks.json` with one `SessionStart` hook matching
  `^(startup|resume|clear|compact)$` that runs `brief .` with `timeout` 30
  and the same status message as the Codex hook. `fork` is deliberately
  excluded: a fork inherits its parent's context, which already holds the
  brief.
- **Nothing outside that folder is written.** `~/.claude/settings.json` is
  never touched; there is no marketplace and no publication. This keeps the
  Phase 28.3 invariant: the only project-owned host-instruction write remains
  the explicit `sync-context` command, and the only user-state write remains
  the explicit `install` command into its own folder.
- The hook command names the absolute path of the `glossabet` executable
  that ran `install`, resolved at install time and verified by executing
  `<path> --version` and matching the package version — never a bare name
  that depends on the hook shell's `PATH`. If no such executable exists (an
  in-process test, a source checkout without an entry point), the skill is
  still installed and the hook is refused with the reason printed; the
  command exits non-zero so a caller cannot mistake it for a full install.
  A moved or uninstalled CLI produces a loud per-session notice, fixed by
  re-running `install --agent claude`; a user who removes Glossabet is told
  to delete the folder (or `claude plugin disable glossabet@skills-dir`).
- Idempotency and consent follow the existing skill contract: each of the
  three files is compared byte-for-byte; unchanged → `current`; a *different*
  existing file is never replaced without `--force`; symlinked components are
  refused; writes are atomic. `--skill-only` installs `SKILL.md` alone for a
  user who does not want ambient context. The success message states exactly
  which files were written and that a session-start hook will run
  `<path> brief .` in every Claude Code session.
- `install` (Codex default) is unchanged: Codex's ambient route is the
  plugin, and no verified Codex skills-directory hook mechanism exists. The
  message says so plainly rather than implying parity that was not built.
- Windows: no `commandWindows` equivalent exists in Claude Code; the hook
  writes the same absolute-path command and Windows behaviour is documented
  as unverified.

Phase 33 is oversized for one pass and splits into three sub-phases with
their own acceptance and commit: 33.1 is deterministic engine/CLI work
provable offline; 33.2 is host-lifecycle evidence that spends Kyle's Claude
account and needs his explicit authorization; 33.3 flips documentation only
after 33.2 has evidence.

- **Phase 33.1 — Claude Code skills-directory plugin install ✅ 2026-08-17** → archived in PLAN-ARCHIVE.md

#### Phase 33.2 — Live Claude Code session-start evidence

**Revised design (binding after the 2026-08-18 isolated-login attempt):**
retire the temporary `HOME` / `CLAUDE_CONFIG_DIR` authentication approach.
It did not authenticate, and the attempted isolated interactive login did not
present Kyle's normal passkey flow; the cause remains unverified. The
controlled run will use the already signed-in normal Claude Code profile while
isolating repositories, tools, settings sources, session persistence, and
captured evidence. It will never invoke `auth login`, `auth logout`,
`setup-token`, or copy/read authentication files.

**Steps:**

1. **Offline implementation complete 2026-08-18.** Add a separate stdlib-only
   evaluator and focused tests:
   `scripts/claude_eval.py`, `tests/test_claude_evaluation.py`,
   `evaluation/claude-scenarios.json`, and
   `evaluation/claude-response-schema.json`. Its append-only attempt ledger is
   `evaluation/claude-history.json`; the latest completed raw result may be
   mirrored at `evaluation/claude-results.json`, but only when its SHA-256 is
   retained by the ledger. Immutable raw runs are single JSON files named
   `evaluation/agent-runs/<UTC>-claude-<id>.json`. Keep this evidence separate
   from the Codex evaluator and its history.
2. **Live preflight passed 2026-08-18.** Fail closed before a model call.
   `claude --setting-sources user auth status
   --json` must already report a signed-in first-party `claude.ai` subscription;
   retain only the non-identifying status fields. Hash the installed
   `~/.claude/skills/glossabet/` skill, manifest, and hook; require Claude Code
   2.1.235's plugin inventory to show that exact folder as
   `glossabet@skills-dir`; inventory every other enabled plugin and abort if
   another SessionStart hook could contribute context. Never modify plugin,
   settings, or authentication state.
3. **First live batch retained as a pre-model startup miss; corrected batch
   pending fresh authorization.** One batch is exactly three fresh `claude -p`
   calls in uniquely named
   temporary Git repositories under `/tmp`:
   - `ambient-present`: a finalized glossary contains one distinctive
     canonical term and definition, one proposed term, and an unrelated source
     canary. The prompt names none of them and does not name Glossabet. Run with
     `--setting-sources user`, `--disable-slash-commands`, `--tools ""`, an
     empty strict MCP configuration, `--no-chrome`, `--no-session-persistence`,
     structured output, and streamed hook events. Passing requires exactly the
     canonical term and definition from the SessionStart brief, no proposed
     term or source canary, zero model tool calls, and an unchanged repository.
   - `ambient-absent`: the same tool-disabled boundary in a repository with no
     glossary. Passing requires the Glossabet hook to run with no vocabulary
     payload, the model to report that no settled term was supplied, none of
     the fixture terms/canaries, zero model tool calls, and no repository write.
   - `skill-root`: submit the literal `/glossabet` command with skills enabled
     but model tools still disabled. Passing requires the response to reflect
     the installed skill's Step 0 version-check/inspect boundary and to stop
     because tools are unavailable; this records root-skill invocation without
     granting shell or file access. The 2026-08-18 manual smoke test separately
     corroborates a full managed-glossary invocation with tools.
4. **First miss retained and digest-verified; passing lifecycle evidence
   pending.** Capture the Claude Code version, OS, sanitized auth mode,
   installed-plugin
   hashes and inventory, exact prompts, bounded raw event streams, model
   responses, usage reported by the CLI, fixture snapshots, cleanup result,
   and every input SHA-256. Append completed, failed, and preflight-aborted
   attempts; never overwrite or hide a miss. Remove and verify absence of only
   the evaluator-owned `/tmp` tree. `--no-session-persistence` prevents saved
   conversations; ordinary Claude runtime metadata remains outside the
   evaluator's zero-write guarantee and is neither inspected nor deleted.
5. **Offline correction and tests complete 2026-08-18:** 21 evaluator tests and
   all 644 repository tests pass; `--verify-history` reports one genuine
   retained attempt. **Needs from Kyle before another live run:** a fresh
   explicit authorization for three Claude
   Code calls on his existing Max subscription, no retry, estimated at no more
   than 200,000 input and 6,000 output tokens total, with the CLI capped at
   $0.25 per call, plus permission to create and delete the one named `/tmp`
   run directory. The request must say plainly that normal authentication is
   reused and no login flow will occur.

**Acceptance:** the offline evaluator tests pass; one newly authorized,
no-retry three-call batch on Claude Code 2.1.235/Linux records all three
scenarios as passes or visible misses; every fixture-write, canary, tool-call,
hook-inventory, artifact-integrity, and cleanup check is recorded; the raw run
and ledger verify by SHA-256. Only a passing batch permits Phase 33.3 to change
Claude Code's documentation status, and that claim remains limited to the
normal-profile configuration, version, and operating system actually probed.
A batch that stops at local CLI/schema validation before hooks or model use is
retained as a real miss but does not supply the host-lifecycle evidence, so it
does not close Phase 33.2.

**Offline implementation record — 2026-08-18:** the five planned artifacts
now exist. The runner admits live execution only behind its explicit
three-call confirmation phrase; strips API/provider and alternate-profile
environment overrides; refuses login, unsafe auth, unexpected SessionStart
hooks, a stale installed plugin, and weakened host settings before model use;
confines fixtures and cleanup to one evaluator-owned `/tmp` directory; and
writes immutable raw evidence plus a digest-bound append-only history. Its
offline fake host proves the exact three-call command boundary and every
recorded failure class without contacting Claude. The verifier recomputes
scenario meaning and hook/tool/retry observations from the retained event
trace, rejects claimed success that contradicts that trace, checks current
input identity, and detects raw-result tampering. At the end of the offline
implementation pass there was no current result or raw run; the first live
attempt below now supplies both.

**Automated live attempt — 2026-08-18 local / 2026-08-19 UTC (retained
pre-model miss):** Kyle authorized exactly one three-call normal-profile
batch, no retry, at the planned limits. Attempt
`20260819T043823Z-claude-full-25584658` passed Claude Code 2.1.235/Linux auth
and installed-plugin preflight, including the first-party Max status and the
three enabled-plugin hook inventory. All three `claude -p` processes then
exited 1 before SessionStart or model use with the same local validation
error: the response schema declared JSON Schema Draft 2020-12, while Claude
Code's structured-output validator uses Draft 7 and rejects newer declared
versions. The raw result is
`evaluation/agent-runs/20260819T043823Z-claude-full-25584658.json`, SHA-256
`9dbb8bfa4fb29bd5b25e9d1942646ae87aea89cd33655bdf460084f51b6803c5`;
the history retains that digest and the current-result mirror is identical.
Recorded usage is 0 input / 0 output tokens and no reported dollar cost; no
API retry, model tool call, fixture write, proposed-term leak, or source-canary
leak occurred, and the batch-owned temporary directory was removed. The 0/3
result remains visible and Phase 33.3 remains blocked.

The directly supported offline correction removes the newer-draft declaration
and relies on Claude Code's documented Draft 7 default; a regression forbids
reintroducing `$schema`. The history verifier's separate false success message
(`empty` despite one attempt) was also corrected and tested. The focused suite
is now 21/21 and the full suite 644/644. No second live batch was run. A fresh
authorization is required to exercise the corrected schema. Because the
evaluator and schema changed after the retained miss,
`--verify-results evaluation/claude-results.json --current` now correctly
rejects that mirror as both 0/3 and based on prior inputs; history integrity
still verifies.

**Temporary cleanup completed 2026-08-18:** independent verification found
`/tmp/glossabet-claude-eval-6dup075u` was born at 20:31 local, over an hour
before this batch, and contains the superseded isolated design's `home`
layout. The current evaluator cannot create that layout, so it is not the
current batch directory. Kyle separately authorized deletion of that exact
path; it was permanently removed without reading its contents and verified
absent. At wrapup, a names-only sweep found 45 other top-level
`/tmp/glossabet-*` directories and 31 files from earlier project sessions,
with no running process using them. Kyle authorized finishing the temporary
files; all 76 were removed without reading their contents, and a final
names-only check found no top-level `/tmp/glossabet-*` entry.

**Manual owner smoke test — 2026-08-18 (partial evidence; not acceptance):**
Kyle launched the ordinary `claude` command from
`examples/payment-service` using his normal signed-in profile on Claude Code
2.1.235/Linux. An ordinary orientation prompt named neither Glossabet nor the
expected canonical terms. Claude used **Payment Attempt**, **Gateway Client**,
and **Authorization**, and its response explicitly identified the vocabulary
brief as SessionStart-injected context. The same session recognized
`/glossabet`; the skill ran Glossabet 0.1.0, detected the existing managed
glossary, retained all three canonical concepts without re-proposing them,
reported no divergence, and made no file changes. A post-session check found
`main` equal to `origin/main` at
`7b636659f39e277fefe2ff1a33333496f95b9b7f` with a clean tree.

This is useful live-host smoke evidence, but it does **not** satisfy the
acceptance above. The orientation response searched/read project material and
ran a shell command, so it does not isolate the terms to hook context under
the zero-command rule; no no-glossary negative scenario ran; the normal user
profile was not controlled as specified above; and no evaluator-owned raw
transcript, token record, or digest-bound artifact was captured. Two ordinary
interactive Claude responses used Kyle's existing subscription; no token count
or dollar price was captured. An earlier isolated-profile evaluator stopped at
authentication preflight before any model call. Its temporary state was
believed removed at Kyle's direction, but the older residue identified above
proves that claim was too broad. A later temporary isolated login
also did not complete because the passkey flow offered cancellation rather
than Kyle's normal sign-in experience; the cause is unverified. Do not repeat
that login route; the revised design above supersedes it. Phase 33.2
remains open, and the unverified wording required before Phase 33.3 remains
correct.

#### Phase 33.3 — Documentation and status flip

**Steps:**

1. README, DISTRIBUTION.md, CHANGELOG, `docs/`: Claude Code moves from
   "experimental / unverified" to verified for the exact version and OS
   probed; other versions and operating systems stay explicitly unverified.
2. Update Settled decision 12 and the CLI-surface table.

**Acceptance:** no document claims Claude Code ambient behaviour beyond what
33.2 measured; every remaining unverified host is named.

- **Phase 34 — `GLOSSABET.md`, the repository vocabulary-health report ✅ 2026-08-17** → archived in PLAN-ARCHIVE.md

- **Phase 35 — Deepening refactor (zero behaviour change) ✅ 2026-08-17** → archived in PLAN-ARCHIVE.md

### Phase 36 — Good to great: the seven remaining structural debts (added 2026-08-17, in progress)

**Goal:** finish what the Phase 35 review left. Kyle's ask (2026-08-17):
"write into the plan … so this can go from good to great." Each sub-phase
is one pass under the Phase 35 rules — zero behaviour change, byte-identical
fixture baseline (rebuild the command oracle first — recipe in HANDOFF.md;
it lives outside the repo and must be re-captured each session), full suite
green, one commit per sub-phase, ARCHITECTURE.md module map kept current. Order is by payoff and risk;
36.1–36.3 are the ones that change how the codebase feels to work in.

- **Phase 36.1 — Split the `evidence.py` hub ✅ 2026-08-17** → archived in PLAN-ARCHIVE.md

- **Phase 36.2 — One command preamble and one glossary-error style ✅ 2026-08-17** → archived in PLAN-ARCHIVE.md

- **Phase 36.3 — Accessor layer for the four top-level documents ✅ 2026-08-17** → archived in PLAN-ARCHIVE.md

- **Phase 36.4 — Managed-context printer out of the command module ✅ 2026-08-17** → archived in PLAN-ARCHIVE.md

- **Phase 36.5 — Producer-level tests for drift and validation rules ✅ 2026-08-17** → archived in PLAN-ARCHIVE.md

- **Phase 36.6 — Ledger ceremony ✅ 2026-08-17** → archived in PLAN-ARCHIVE.md

- **Phase 36.7 — Verification weight onto the skill ✅ 2026-08-18 (scoped; live post-approval scenarios split to 36.8)** → archived in PLAN-ARCHIVE.md

#### Phase 36.8 — Live post-approval skill scenarios (added 2026-08-18, not started)

**Goal:** the two skill behaviours the Step-0 harness cannot observe get
one recorded live scenario each.

**Steps:**
1. `scripts/agent_eval.py`: a fourth host run, `report-refresh`, over a
   fixture with a finalized structured glossary (one canonical, one
   proposed concept), a hand-written root `GLOSSARY.md`, and a stale prior
   `GLOSSABET.md`. Prompt: the human has already approved; execute Step 7
   only. Checks from the trace and the tree: `GLOSSABET.md` rewritten at
   the root and nowhere else; the proposed concept still `proposed` in
   `glossary.json` (no promotion, no `save`); `GLOSSARY.md` byte-identical;
   no read of the prior `GLOSSABET.md` before the write; no source canary
   in the report.
2. A fifth host run, `baseline-first`, over the `both-glossaries` fixture:
   prompt runs Steps 0–4½ with the user's decisions scripted as "propose
   only, decide nothing"; check that every read of `GLOSSARY.md` in the
   trace comes after the Step 4 baseline is emitted, and that no term
   becomes canonical.
3. Extend `verify_results` for the two new result records; scenario
   manifest, prompt, and schema digests re-bound; **needs Kyle:** a second
   authorization to spend usage (state the count and ceiling first).

**Acceptance:** both scenarios recorded live and passing (or their misses
in the reliability ledger); `--current` agent verification passes.

### Phase 37 — Trust, legal, and provenance review actions ✅ 2026-08-17

**Origin:** Kyle asked, before starting owner testing, for any legal or
ethical considerations not yet thought of and anything else that could come
back to bite. Eleven items were raised; Kyle ruled on each (questions first,
then a single go). Executed in one pass:

1. **Human-approval claims reworded** (Principle 1, CLAUDE.md, README,
   ARCHITECTURE.md, PRIVACY.md, `glossary.py` docstring): the rule is an
   instruction to the skill, not a mechanical guarantee; `save` trusts its
   caller. No machine gate added (Kyle: reword only). Verified the skill
   already invokes `sync-context` only on explicit request.
2. **AI-assisted development disclosed** in README "Provenance and
   affiliation" (Claude via Claude Code; ChatGPT on the initial plan).
3. **DCO adopted, doc-only:** new `CONTRIBUTING.md` (Apache-2.0 inbound,
   `git commit -s`, no CI check, no history rewrite), shipped in the sdist and
   required by `check_distribution.py`. License decision recorded as Kyle's
   (Settled decision 3).
4. **LLM-proposed names vs. trademarks — dropped** as a non-issue: in-house
   names are not use in commerce (Kyle's ruling; Claude agreed).
5. **Not-affiliated line** added (OpenAI, Anthropic, GitHub, Graphify Labs).
6. **`NAME-CLEARANCE.md` corrected** with the true derivation (Amharic
   *bet*, "house"; the *alphabet* echo was noticed afterward), written as a
   dated correction so history is not read as contradictory, plus a note on
   the coincidental proximity to "Alphabet."
7. Eval artifacts contain Codex model outputs — noted, no action.
8. **`brief` first-line origin marker** (`glossabet/brief.py`): live output
   states it was emitted by `glossabet brief .` and that an installed
   `SessionStart` hook injects it automatically; the managed
   `sync-context` block gets its own truthful marker. Existing managed
   blocks stay self-consistent (content hash is declared in-block).
9. **Skill Step 6** now tells the user, every finalize, that
   `glossabet-out/glossary.json` holds decisions that exist nowhere else and
   must be committed (offering the `.gitignore` negation, never editing it).
10. **`RELEASING.md` claims-consistency checklist:** status statements
    agree, name probes rerun, trust statements true, provenance present.
11. **`glossabet cache-clear`** (`cache.py`, `cli.py`): removes only
    Glossabet's own `<root>/<64-hex>/cache.json` layout, never follows
    symlinks, leaves and reports anything unrecognized, so a misconfigured
    `GLOSSABET_CACHE_DIR` can never be wiped. Tests: foreign files, a
    non-hex directory, and a symlinked directory all survive.

**Consequences:** the checked-in plugin wheel was rebuilt from this source;
the installed-agent evidence's `--current` currency lapses (skill, source,
README, and evaluator changed) until the next authorized Codex batch — the
genuineness form still passes. Deterministic and reviewer evidence already
lagged and are regenerated at the release gate as before.

### Phase 38 — `glossabet.json` discoverability and skill WLOS ✅ 2026-08-18

**Origin:** during Kyle's pre-testing review walkthrough, the optional root
`glossabet.json` configuration turned out to be documented in exactly one
README section and nowhere a user or agent would meet it at the moment of
need (no `--help` mention, no runtime hint, and the skill knows only that
the file exists — not its shape). Kyle chose the "engine carries the shape,
skill gets one sentence" design over teaching the skill the schema, to keep
the skill lean, and asked for a WLOS (without loss of substance) shortening
pass on the skill in the same phase.

1. **Engine carries the shape.** `configuration` in `evidence.json` and the
   `inspect` context gains a static `shape` entry (file, location, keys,
   the five roles, the literal-prefix rules, one example) defined next to
   the loader in `config.py`, so the schema has one home and cannot drift.
   Evidence `SCHEMA_VERSION` 12 → 13; context schema stays 3 (additive).
2. **Hint at the point of need.** `scan`/`analyze` print one line naming
   whether roles came from defaults or from `glossabet.json`, and that a
   root `glossabet.json` (`ignore_paths`, `path_roles`) adjusts them.
   `--help` for `scan`/`analyze`/`inspect` mentions the file.
3. **Skill: one sentence.** Step 0's existing "a repository can override…"
   sentence becomes: if roles or exclusions look wrong, say so and offer to
   write a root `glossabet.json` as described by `configuration.shape`;
   write only on the user's yes. `test_skill` dotted-field check covers it.
4. **WLOS pass on `skill/SKILL.md`.** Remove repetition and restatement
   only; every rule, ordering, threshold, and stance survives; the
   `test_skill` structure tests must still pass. Report before/after size.
5. Docs (README, ARCHITECTURE) reflect the new field and hint; wheel and
   plugin rebuilt; suite green; commit naming the phase.

**Outcome:** `config.CONFIG_SHAPE` carried as `configuration.shape`
(evidence schema 13); `evidence_report.configuration_hint` printed by
`scan`/`analyze`; `--help` scope note on `scan`/`analyze`/`inspect`; skill
Step 0 sentence; new test in `test_config.py` (hint text, shape keys, and
the carried example itself loads). WLOS pass: 707 → 693 lines, 39,844 →
38,818 bytes — restatements only (three "never bulk-read" phrasings merged
into one, plugin-engine path note folded into the command paragraph,
Graphify/state/Step 6/Step 7 paragraphs tightened); every pinned phrase and
`test_skill` structure test unchanged. The document is already dense;
further cuts would remove examples or rationale. Suite 532 green; wheel and
plugin rebuilt; installed-agent `--current` currency lapses again until the
next authorized Codex batch. Kyle's review of the codebase itself (nesting,
flat package, module sizes) has not started.

### Phase 39 — Subpackages by layer, zero behavior change ✅ 2026-08-18

**Origin:** Kyle's pre-testing review: the flat 35-module package "has zero
organization" and hides real layer boundaries. He accepted the standard
`glossabet/glossabet/` nesting once explained, declined splitting the six
500+-line files (well-organized big files are fine; only the four longest
functions are a readability cost, left as a separate offer), and said "do
it" to grouping. Every module keeps its name except one, and only import
paths change.

**Layout** (import direction flows downward; package names never repeat a
module name, so no `x/x` doubling):

```
glossabet/
  cli.py, __main__.py, __init__.py, _skill/     entry point
  runtime/   engine_run, artifacts, display, coverage, git_state
  corpus/    scanner, config, extraction, cache, tokenize, imports
  analysis/  evidence, evidence_view, vocabulary, terminology, importance,
             graphify, evidence_report
  glossary/  store (was glossary.py), glossary_commands, repository_glossary,
             matching, findings, drift, reconcile
  agent/     agent_context, brief, managed_block, managed_context, context_sync
  install/   installer, claude_plugin
```

Boundary calls: `tokenize` is the lexical contract every layer uses and sits
lowest (`corpus`); `matching` matches glossary terms against evidence and
imports `glossary`, so it lives with the glossary health checks; `findings`
serves only `drift`/`reconcile`. `glossary.py` → `glossary/store.py` is the
single rename (load/validate/save of `glossary.json`), to avoid
`glossary.glossary`.

**Self-measurements that changed with the layout (Kyle's rulings, 2026-08-18,
"do as you recommend"):**
- `ROUTINE_AGENT_CONTEXT_TARGET_BYTES` 80 000 → 100 000. Glossabet's own
  routine `inspect` context went 78 417 → 87 675 bytes because module
  rollup keys, `files`, and `modules` now carry seven longer package paths.
  The constant is reported in `coverage.context.limits` and used by one
  dogfood test; it shapes no output. README/ARCHITECTURE updated.
- `evaluation/corpus.json` `self_nominations` re-labelled deliberately (the
  dispersion measure is per directory, so identical code in seven packages
  reads as more spread out): `coverage` → `deserves disambiguation` (three
  referents: ledger, corpus completeness, context omissions); `run` removed
  from `forbidden_terms` (`engine_run.Run` is a first-class domain object
  since Phase 36.2; the layered nomination is neither required nor
  forbidden); `structural` removed from `required` (an adjective whose noun
  is `structural_groups`; not nominated now); `drift` keeps `deserves a
  canonical name` and **fails** — 8/9. **Open finding for a heuristic
  phase:** the context-dispersion heuristic reads call-site diversity across
  layer subpackages as meaning diversity. Until resolved, the
  `nomination_quality_min: 1.0` release threshold is legitimately unmet;
  `test_evaluation` asserts exactly this state (`required:drift` the only
  failure). `evaluation/results.json` lags as before (regenerated at the
  release gate).

Steps: (1) oracle baseline — every command × four fixtures with seeded
glossary, `GLOSSARY.md`, host files, `glossabet.json`; stdout/stderr/rc,
every `glossabet-out/*.json`, both host files, plus an error-path set;
captured twice and byte-identical before any move. (2) `git mv` into
subpackages with `__init__.py`; rewrite every `glossabet.<module>` import
and dotted reference in `glossabet/`, `tests/`, `scripts/`, `evaluation/`,
`plugins/`. (3) `test_module_dependencies` and `test_document_keys` follow
the new paths (the ratchet globs recursively). (4) ARCHITECTURE.md module
map, CLAUDE.md, README where paths are named. (5) Oracle byte-identical;
suite green; wheel/plugin rebuilt; `check_distribution` passes; commit.

**Outcome:** done as planned. Oracle: 18 commands × 4 fixtures + 9 error
paths, every artifact and host file — byte-identical except the twelve
`inspect` outputs, which differ only in the reported
`routine_target_bytes` (80000 → 100000). `installer.canonical_skill_text`
source-checkout fallback path fixed for the deeper module; dependency and
document-key ratchets made layout-aware (the latter had been globbing
non-recursively — fixed); `check_distribution`/`test_plugin` wheel path
lists updated; `wheel_smoke` passes. Suite 532 green.

### Phase 40 — Bughunt round 4 (whole project) ✅ 2026-08-18

Five close-read hunters (corpus, analysis+runtime, glossary, agent+install+cli,
scripts+evaluation) after Phases 38–39 and the refactor round; every finding
re-run first-hand before fixing; each fix landed serially with a pinned
regression test. Fixed (30 confirmed/latent-proven + 3 settled Likely):

- **Engine honesty:** innocently named symlinks laundered excluded content
  (GLOSSARY.md, GLOSSABET.md, glossabet-out, sensitive dirs, hidden,
  ignored, generated, vendored) into evidence — the shared content rule now
  classifies the target's full path (`symlink-to-excluded-content`; root
  GLOSSARY.md discovery inherits it); silent walk drops (escaping/confined
  directory symlinks, dangling links, unlistable directories) now ledgered
  (`symlinked_directories`, `unreadable`, `walk_remainder` inexact); non-UTF-8
  text confessed as `not-utf-8` instead of decoded into invented words;
  `oversized_identifiers` counts spellings; combining marks (Devanagari, Thai,
  niqqud) stay inside identifiers/doc words via a static Mn/Mc/Me table
  (`corpus/unicode_marks.py`, `scripts/gen_unicode_marks.py`); relative
  imports of non-code no longer fabricate modules; Rust `crate::`/`self::`/
  `super::` resolve intra-crate; slug matching indexed (103 s → 0.14 s at
  2k files × 20 specs); `glossabet.json` trailing slash gets the real reason;
  integer-only `schema_version` (config + glossary); fixture package manifests
  no longer trip the monorepo alert; walk-time byte ledger on reclassify;
  Graphify fallback shape (dup members/ids, empty `links`, empty `label`,
  GLOSSABET.md-sourced nodes discounted); `GIT_DIR`/`GIT_WORK_TREE` never
  inherited; `cache-clear` reports an unlistable entry; kebab-case is a
  structured register style. Evidence schema 13 → 14, cache version 4 → 5.
- **Glossary layer:** scope-overlap validation now sorts component-wise;
  doc-index absence proves nothing for terms the index cannot hold (`ID`,
  `S3`) and possessives fold (`tenant's` → `tenant`) — no false "fading";
  compound `files_complete` no longer conflated with the display clip; lone
  surrogates refused at `save` (they crashed `brief`/`sync-context`).
- **CLI/agent/install:** `OSError`s (permission denied, disk full) exit 1
  with the OS reason; closed stdout pipe exits 1 silently (`_abandon_stdout`);
  install outside a Claude skills directory no longer promises plugin
  loading; README remedy is `--force`; `--force` help, ARCHITECTURE install
  flow and exit contract, `strip_managed_context_for_evidence` docstring
  corrected.
- **Release machinery:** stale `glossabet/brief.py` wheel path (agent lane
  gate could never pass); `--case --output evaluation/results.json` guard
  resolves paths; recall numerators restricted to the measured set
  (`recall_true_positive`, evaluation schema 6 → 7, results regenerated with
  `--fetch --runs 5`: precision 1.0, zero false alarms, nomination 8/9 as
  recorded); null-safe agent verifiers; `passed`-vs-`failures` consistency
  in both verifiers; home-path guard without trailing slash; reviewer `..`
  check is a path-segment check; commented `uses:` ignored.
- **Verifier contract change (consequence of the Phase 39 ruling):**
  genuineness now requires threshold checks to *recompute* from recorded
  metrics; *passing* every threshold moved to the release gate
  (`--current`), because the truthfully recorded `required:drift` open
  finding would otherwise make honest evidence read as tampered
  (EVALUATION.md updated). **Confirmed by Kyle 2026-08-18** ("nothing
  needed from me").

**Rulings (2026-08-18):**
- R1 — **ruled "uncertain"; implemented in Phase 44.** A `file:`/`module:`
  binding under a path the scan deliberately did not read (vendored,
  generated, configured-ignore, sensitive, oversized, a link) or — when the
  `validate` command passes the repository root — to a real on-disk path
  the inventory never lists (`Makefile`, `config/settings.toml`) is
  `uncertain`, counted in the unresolved-bindings ledger reason, never a
  drift finding; the disk probe is confined (absolute/`..`/escaping links
  read as absent).
- R2 — `hooks.json` command quoting does not escape backslashes (Windows-style
  or doubled-backslash executable paths under a POSIX shell). **Ruled: leave
  as a documented known limit** (no Windows machine available); revisit with
  the Windows plugin probe (Phase 33.2).

**Deferred with reason:** an aborted Codex attempt records raw stderr in the
attempt history; if that text ever carried the sensitive canary or a home path
the history would fail its own checks. Not reproducible without a live
authorized run; settle at the next Codex batch.

### Phase 41 — Bughunt round 5 (differently aimed) ✅ 2026-08-18

Four lenses on the committed round-4 tree: review-the-fixes, end-to-end
flows on odd repositories, generated adversarial input at the trust
boundaries (2,000 graphs, 1,200 glossaries, 3,000 verifier mutations, 300
configs), and Windows/macOS reasoning with emulation. Fixed, each with a
pinned test:

- **Round-4 siblings/regressions:** the symlink rule was too broad for the
  discovery channel (root `GLOSSARY.md → docs/GLOSSARY.md` refused) — a
  narrower `glossary_link_refusal` (escape / sensitive / Glossabet's own
  output); unstatable real files (EACCES) now charge the corpus budget
  (`complete`/`production_complete` false); a symlinked file takes its
  target's role; root manifests use the link rule; Rust `self::`/`super::`
  item paths retry like `crate::`; one-word bare specs no longer attach to a
  same-named directory anywhere (`import os` vs `tests/os/`); `GIT_INDEX_FILE`
  scrubbed; doc-index lookup keys by doc word (`O'Brien`); `--version` to a
  closed pipe quiet; UTF-8 BOM stripped from source text; ZWNJ/ZWJ continue a
  word; commented list-dash `uses:` ignored; parent-segment regex covers
  shell terminators; mark-table docstring claim corrected.
- **Flows:** `inspect` no longer fails on 100+ long definitions (omission
  records coalesce per pattern, `glossary.concepts.*.definition`);
  subproject `AGENTS.md`/`CLAUDE.md` managed blocks stripped at any depth
  (case-insensitive name); BOM before a block at byte 0 stays current and
  repairable; vocabulary ownership keyed by token sequence (`Alpha Beta` =
  `AlphaBeta` = `alpha_beta`; Settled decision 9 updated); zero-width
  space/word joiner/soft hyphen/BOM refused in glossary strings; divergence
  presence counts code-cased spellings; NFC comparison for scopes and file/
  module bindings; `brief` names `glossary.json`'s own Git state
  (`committed`/`modified`/`untracked`); artifacts written 0o666−umask, not
  0o600; JSON reads tolerate a BOM; scan root inside `glossabet-out/` refused.
- **Adversarial:** astronomically large `cohesion` (int beyond float range,
  1e308) degrades instead of crashing/poisoning scores (`MAX_USABLE_COHESION`);
  node/group labels capped at 512 chars (`label_truncated`), member tokens
  at 2,000 with a ledger (evidence schema 14 → 15); lone surrogates are
  terminal controls (escaped, never `UnicodeEncodeError`); verifiers report
  `OverflowError` as malformed metrics; `glossabet.json` that is a directory
  is an error, not "no configuration".
- **Platform (emulated):** piped stdout under a narrow console encoding
  (cp932/cp1252 on Windows) never raises — the safe stream renders
  unencodable text as escapes; git output decoded as UTF-8 with replacement
  (non-ASCII untracked names under an ASCII/cp1252 locale); cache-dir
  containment by inode (case-insensitive filesystems); host-context files
  found only under a different case are refused (would silently replace
  them); Windows-absolute sdist member names rejected; case-insensitive
  skills-directory check; README notes the plugin hook's `python3`/`py`
  launcher requirement.

**Deferred — Windows-only, cannot be settled here (record what would):**
`sync-context` onto a read-only NTFS file fails and leaves a read-only
`.AGENTS.md.*.tmp` (settle: `attrib +R AGENTS.md; glossabet sync-context .`
on Windows); directory junctions are not `is_symlink()` and can escape the
walk (settle: `mklink /J repo\link C:\Windows; glossabet scan repo`); R2
hook quoting — concrete cases: UNC `\\server\share` collapses to
`\server\share` under bash/sh; drive-letter paths are safe; PowerShell
would need `&`.

**Not bugs (recorded so they are not re-hunted):** `read_source` keeps a
BOM out of content but `write_text` platform newlines are never used for
artifacts; `OSError` → exit 1 is deliberate (documented) and does make the
2 = defect contract unenforceable for that family; `inspect` on a
read-only checkout cannot refresh evidence (documented); untracked
`graphify-out/` legitimately makes Graphify freshness `unverified`; Turkish
`İ` casefolds to `i̇` (Unicode-correct); tabs are already allowed in prose.

### Phase 42 — Security audit round 5 ✅ 2026-08-18

Four auditors (engine trust boundaries; install/plugin/hooks/CLI; repo
hygiene + CI/CD + supply chain; resource exhaustion), every finding
re-verified, all fixed with pinned tests. Highest-value:

- **Repo-shipped `git.exe`/`git.bat` executed on Windows** — `shutil.which`
  searches the current directory first (and a bare name resolves the same
  way); an earlier round used it for exactly this defense. New
  `runtime/executables.which_on_path`: PATH walked ourselves, absolute
  entries only, never `.`/empty, never a hit inside cwd, never a bare name;
  no git on PATH → stamp honestly unverified. Same lookup for the `glossabet`
  the Claude hook persists (a repo-local `glossabet.bat` could otherwise be
  written into every future session's hook); notes printed when the chosen
  executable is inside cwd or a virtualenv.
- **Codex runner isolation:** hook commands are `python3 -I -B` / `py -3 -I -B`
  (no PYTHONPATH/user-site/script-dir); the bundled wheel sits after the
  stdlib and before site-packages.
- **Hostile graph fan-out DoS** (1.3 GB / 32 s from a 55 MB graph):
  `GRAPH_WORK_BUDGET` judged from list lengths before any member is
  materialized; over budget → present-but-unusable, lexical-only (1.8 s).
- **Invisible characters refused as a class** (Default_Ignorable_Code_Point,
  minus ZWNJ/ZWJ) instead of four enumerated code points; TAG-block text
  hidden from the human but readable by a model was the demonstration.
- **CI:** publish job passes the tag via `env:` (was inline `${{ github.ref_name }}`
  in the one job holding the OIDC token; git accepts `$(…)`/backticks in tag
  names); `persist-credentials: false` on the release checkout;
  `check_workflows.py` strips comments first, reads every workflow file, and
  enforces SHA pins / no `pull_request_target` / no untrusted expression in
  `run:` / no `curl|sh` / no `write-all`/stored secret in publish — a crafted
  bypass (all guards in comments + a fourth `backdoor.yml`) had passed the
  old substring checker; `.github/dependabot.yml` added.
- **Distribution scan** covers every release-wheel member and the plugin
  wheel nested in the sdist (it promptly caught the username in a doc line
  written during this very phase); root-manifest link probe uses the
  configured ignore/role rules; `--version` to a full disk exits nonzero.
- Verified clean: no secrets/keys in tree or history; hash-locked `uv.lock`;
  Trusted Publishing; `--fetch` guards; hostile `.git/config` execution
  attempts (`fsmonitor`, `hooksPath`, filter drivers, aliases, pager via
  `include.path`) blocked; symlink families; regex linearity; cache-clear.

**Recorded accepted risk (SECURITY.md):** the maintainer's absolute checkout
path (OS username + layout) is in public git history from 2026-08-15/16
transcripts/docs; not shipped anywhere; removal needs a history rewrite —
**Kyle ruled 2026-08-18: accept the risk, no rewrite** (the name is public
already; the layout tells an attacker nothing).

**Fix-review of the audit code (same day):** a cold review of the round-5
changes found and I fixed: the graph budget bounded memory but not time (an
in-budget dense shape ran 192 s → node labels tokenized once, memoized, plus
`GRAPH_LABEL_CHAR_BUDGET`; now ~5 s); `which_on_path` regressed on an
unreadable PATH entry and did not resolve the candidate file (a PATH-dir
symlink named `git` into the repo) — both fixed; the hardened workflow
checker had new bypasses (`#` inside quotes, `run: |` block scalars,
list/flow/bare `pull_request_target`, `uses:` continuation lines,
uppercase-suffix files, dropped `persist-credentials`/broadened permissions)
— rewritten over logical `key: value` entries with parent tracking, so an
untrusted expression is refused anywhere except an `if:` condition or an
`env:` value; VS15/VS16 and Mongolian FVS tolerated in prose (so "❤️" is
allowed in a definition) but refused in identity fields, with the offending
code point named in the error; runner `_fail` stderr backslash-replaces
under `-I`; nested-wheel scan bounded (64 MB per member, `BadZipFile`
reported). Suite 582 green.

**Deferred (Windows-only, unverifiable here):** the Codex `commandWindows`
launcher `py` is a bare name that `cmd.exe` would resolve through the
current directory (a repo-shipped `py.bat`); a portable absolute-launcher
form needs the Windows plugin probe (Phase 33.2 territory) — recorded as a
known limit in SECURITY.md. R2 (hook quoting of `\`/UNC) unchanged.

### Phase 43 — Test audit round 1 (whole suite) ✅ 2026-08-18

The suite judged, not the product: five auditors ran ~330 product mutations
across all 33 test files (every test added this session falsified) and
checked every documented promise against the suite. Baseline 582 tests,
deterministic across three runs. Repairs and additions landed in seven
batches of ≤10, each cold-reviewed by a fresh agent before the next; every
new or repaired test was falsified against a named product mutation.

- **Repaired (proven worthless / wrong thing / fragile):** the "hostile
  glossary" drift-budget test whose loop never ran and the alias-suppression
  test whose token was never a candidate (both now exercise the loop and the
  scoped rule); the reconcile clip test (unscoped concept short-circuited);
  the 10.6 s stale-evidence test whose four assertions were satisfied by
  lagging committed evidence regardless of mutation (now brought current
  first, `build_evidence` memoized, every detector asserted as an *added*
  error, and — for the first time — proof the currency gate can go green);
  `test_partial_case_runs…` (would have overwritten committed
  `evaluation/results.json` on regression); the plugin runner tests
  (append-after-site-packages passed); the hook-isolation test (ran the
  hook's own command line, not `-I` typed by the test); `_abandon_stdout`
  no-op stub; happy-path-only evaluator tests (every failing side now
  asserted); root-skip `return`s → `pytest.skip`; a Unicode-version check
  that disabled itself; scratch dirs written beside `tmp_path`; brief
  git-state test without git-config isolation.
- **Proven gaps pinned (class-level, ~45):** drift/validate coverage flags
  (orphan under partial corpus, unresolved ledger reason, watched "at least
  N", vocabulary-omission reasons wired, contiguous compound match, compound
  canonical not token-indexed, entry-level clip, ownership order, same-
  concept duplicate alias, `_`/`-` divergence forms, NFC both directions,
  non-canonical concepts excluded, over-long compound reason, ordering under
  the findings cap); config contract (every refusal + caps at the boundary +
  most-specific role wins in either engine order); sensitive-name families
  (unit + end-to-end canaries); git timeout/no-prompt/stall degradation and
  the full env scrub; artifact modes; brief/managed-block "untrusted
  repository input" label; malformed cache entries; one-word bare import
  spec; cased-script combining marks; doc-word NFKC+casefold contract; BOM
  vs first-line import; member-token cap; top-N by frequency; damaged
  managed blocks still stripped; `read_bounded_bytes` requests cap+1; every
  reviewer/agent verifier gate (blinding, trace, usefulness, canary, hook
  evidence, history coherence); run.py currency checks (case order, source
  metadata, local register, threshold targets); distribution scan reaches
  every archive layer; ~16 peripheral workflow-checker rules; relative
  imports resolved in the dependency ratchet.
- **New ratchets:** `tests/test_trust_ratchets.py` — no network module, no
  eval/exec/dynamic import, subprocess only in the two documented modules
  and never `shell=`, no `sys.path` mutation (the trust documents' promises,
  previously enforced by nothing).
- **Hunters → tests:** seeded verifier-mutation family (3 files, 400 cases;
  finds the once-unguarded OverflowError), hostile config / glossary / graph
  families (`tests/test_config.py`, `test_glossary.py`, `test_graphify.py`);
  each ≤2 s.
- **Docs:** SECURITY.md pointed at the real freshness tests.
- Suite: 621 tests, ~60 s (slowest: the stale-evidence test at 6 s, sixteen currency mutations).

**Product findings handed to a bughunt pass (not fixed here):**
`scripts/plugin_smoke.py::_extract_sdist` `NameError` (`name` undefined) —
the sdist smoke probe cannot run; workflow-checker bypasses in the checker
itself (`|| true`, `continue-on-error: true`, `if: false` on a required
step, `toJSON()/format()` wrappers, `curl … | sudo bash`, `secrets.` in a
top-level `env:`); `evaluation/run.py` genuineness does not check
`recall_true_positive ⊆ true_positive` (a phantom recall item with an empty
`false_negative` list verifies clean); `EvidenceIndex.compound_complete` is
index-wide (one over-cap glossary term marks every compound count inexact —
over-conservative, not wrong).

**Pending Kyle's ruling:** `examples/payment-service/glossabet-out/evidence.json`
is a stale schema-7 artifact stamped with the dev repo's git head; nothing
reads it (the walkthrough regenerates); recommend deleting it from the
example (a derived report, not part of the sample).

**Not deleted (proposed only, per the test-audit rule):** the ~6 redundant
pairs listed in the report (cohesion NaN vs overflow; three invisible-
character tests; two confined-symlink tests; two warm-cache tests).

### Phase 44 — Bughunt round 6 (test-audit findings) ✅ 2026-08-18

The four product findings the test audit surfaced, fixed with class-level
tests, plus R1 as ruled:

- `scripts/plugin_smoke.py::_extract_sdist` referenced an undefined name in
  its unsafe-path guard (pasted from the distribution checker), so the sdist
  smoke probe crashed on its first member. Fixed; a synthetic-tarball test
  covers extraction of a well-formed archive and refusal of absolute (POSIX
  and Windows), backslashed, `..`, link/device, and dotenv members.
- `scripts/check_workflows.py`: a required step counted as present while
  inert. Root cause: presence judged by substring, not by "a step whose
  failure fails the job". Now gate jobs (quality test/package, release
  publish) refuse `continue-on-error`, step-level `if:`, and shell softeners
  (`|| true`, `|| exit 0`, `set +e`) in any `run:`; an untrusted expression
  is caught anywhere inside `${{ … }}` (`toJSON(github.event)`, `toJSON(github.event.…)`,
  `format('{0}', inputs.x)`); `curl … | sudo bash` and `env`/`nice`
  prefixes are download-pipes; `secrets.` anywhere in any workflow is
  refused (Trusted Publishing needs none). Every bypass pinned in
  `tests/test_release.py`.
- `evaluation/run.py` genuineness now checks each per-case score block is
  what `_score` produces (true/false positives partition `actual`; recall
  and useful hits ⊆ true positives; nothing both found and missed; sorted
  unique strings) — a phantom recall hit with an empty false-negative list
  previously verified clean. EVALUATION.md updated.
- `EvidenceIndex.compound_complete` was index-wide: one over-cap glossary
  term made every compound term's count inexact. Root cause: a per-term
  property stored as an index flag. Now only the (genuinely index-wide)
  position budget marks counts inexact; the over-cap term alone is
  unmatched.
- R1 as above (`reconcile._path_binding_status`, `_exists_confined`,
  `build_validation(root=…)` from the `validate` command; ARCHITECTURE.md).

Suite: 623 tests green.

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

## Settled decisions (through 2026-08-17)

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
3. **Public, Apache-2.0.** Originally recorded in Phase 0 (2026-08-14) as
   "matching Graphify" — a choice made by inference in a working session,
   not one Kyle had asked for or signed off on; Kyle had assumed the project
   was MIT. On 2026-08-17, after the differences were explained (Apache adds
   an explicit patent grant, §5 default contribution terms, and a trademark
   carve-out; MIT is shorter; matching Graphify was never legally necessary
   because Glossabet only reads its JSON output), **Kyle explicitly chose to
   keep Apache-2.0.** This is now his decision, not a default. Contributions
   are accepted under Apache-2.0 with a Developer Certificate of Origin
   sign-off (`CONTRIBUTING.md`, doc-only, no CI enforcement).
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
   vocabulary ownership must be unique wherever regions overlap — keyed,
   since Phase 41 (2026-08-18), by the term's normalized word sequence
   (before the lexical keyword filter) rather than its NFKC-casefolded
   string, because every consumer compares by words. Drift and lexical reconciliation enforce the same boundary.
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
