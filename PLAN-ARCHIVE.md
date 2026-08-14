# Glossarize — Plan Archive

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
