# Session handoff — 2026-08-18

Refreshed at the end of the 2026-08-17 session (Phases 34 and 35). It
becomes stale when the next phase begins. `PLAN.md` remains the
authoritative durable roadmap; read its status line, the Phase 36 plan, and
the owner self-testing pause before doing anything.

**Project:** Glossabet is a Python CLI, canonical agent skill
(`skill/SKILL.md`), and Codex/Claude Code plugin for making a codebase's
vocabulary explicit, canonical, inspectable, and maintainable. Deterministic
machinery gathers evidence, the LLM reasons, the human decides.

**State on disk:** `dev` is eight commits (Phases 36.1–36.7) ahead of
`main`; the working tree is clean; the full suite (529 tests) is green; wheel and plugin were rebuilt
through `uv build --no-sources` + `scripts/build_plugin.py dist` and
`scripts/check_distribution.py dist --tag v0.1.0` passes; the CLI at
`~/.local/bin/glossabet` is the current build. The installed agent skills
(`~/.claude/skills`, `~/.agents/skills`) are whatever Kyle last installed —
re-run `glossabet install --agent claude` / `glossabet install` if unsure.

**Completed this session**

- **Phase 34 — `GLOSSABET.md`.** Three artifacts kept separate:
  `GLOSSARY.md` (agreed vocabulary), `GLOSSABET.md` (Glossabet's derived
  vocabulary-health report, written by the skill at Step 7 at the scan
  root), `glossabet-out/glossary.json` (structured state). Engine:
  `artifacts.REPORT_FILE`, `scanner.SELF_REPORT_FILES` (excluded at any
  depth, reported as `skipped.self_reports`), freshness pathspec
  `:(exclude)GLOSSABET.md` for the scan root only; `GLOSSARY.md` stays
  visible to freshness. Docs and tests (`tests/test_report.py`) updated.
- **Phase 35 — deepening refactor, zero behaviour change.** Six commits.
  New modules `git_state.py`, `managed_block.py`, `vocabulary.py`
  (`ProductionVocabulary`), `findings.py`; one bounded read discipline in
  `artifacts.py`; scanner `EXCLUSION_KINDS` ledger and
  `symlink_content_refusal()`; `build_terminology` 10 → 2 params,
  `build_naming_candidates` 9 → 5; dependency directions pinned by
  `tests/test_module_dependencies.py`. Every step was verified byte-identical
  against a 76-file oracle of every command's output on the four local
  corpus fixtures with their glossaries.
- **Phase 36 in progress** — the seven remaining structural debts from the
  post-refactor review. **36.1 done:** `evidence.py` split into assembly
  (`evidence.py`, 287 lines), `extraction.py` (`SourceExtractor` + read/
  extract functions), `evidence_report.py` (`scan`/`analyze` handlers and
  printer), plus `DocumentationVocabulary`. **36.2 done:** `engine_run.py`
  (`open_run` → `Run` | `RunError`), `evidence.persist_evidence`,
  `glossary_commands.py` (`show`/`save`), `repo_root`/`require_glossary`
  deleted, `tests/test_engine_run.py` run contract; both oracles (happy
  path and error path) identical. **36.3 done:** `evidence_view.EvidenceView`,
  `findings.FindingsDocumentView` + `drift.DriftView` /
  `reconcile.ValidationView`, `tests/test_document_keys.py` AST ratchet;
  oracle identical, 513 tests green. **36.4 done:** `managed_context.py`
  (render / safe read / analysis / inspector / printer) beneath
  `context_sync`; drift and reconcile no longer import a command module.
  **36.5 done:** `tests/test_finding_producers.py` (15 producer-level
  tests over hand-built evidence, one per finding kind). **36.6 done:**
  `coverage.capped_collection(total_items=…)` + `coverage.capped_section`,
  `findings.empty_section`; ledger construction sites 22 → 13. **36.7
  done (2026-08-18):** wheel/plugin rebuilt, authorized Codex batch 14/14
  on the first attempt (790 k input / 11 k output tokens), agent evidence
  passes `--current`; `test_skill.py` structure tests. Step 4½ / Step 7
  live scenarios split into **Phase 36.8** (needs a new host run and a
  second usage authorization). Each sub-phase is one pass under Phase 35
  rules.

**How to resume**

- `$next` / `/next` → the first incomplete phase whose dependencies are
  complete is Phase 33.2 or Phase 36.8 — both need Kyle's authorization
  to spend usage on a bounded batch (state count and ceiling first), and
  both honour the owner self-testing pause. Phase 36.8 steps 1–2
  (evaluator code) can be written before the authorization; only the run
  needs it.
- Before any Phase 36 sub-phase, rebuild the byte-identical oracle: copy the
  four local fixtures from `evaluation/corpus.json` (`path` sources) to a
  scratch dir, `glossabet save` each source's `glossary`, run every command
  (`scan`, `analyze`, `inspect [--full] [--no-graphify]`, `drift`,
  `validate`, `show`, `brief`, `sync-context [--agent claude]`, cache-warm
  `scan`) with `GLOSSABET_CACHE_DIR` pointed at scratch, capture
  stdout/stderr and every `glossabet-out/*.json`, and diff after each step.
  Do not include a scan of this repository itself in the oracle — the
  refactor changes the source it reads.
- `agent_eval.py --verify-results --current` passes as of 2026-08-18. The
  engine-evaluation (`evaluation/run.py`) and reviewer verifiers are still
  stale under `--current` (self-scan of this repository moved during
  Phase 35–36; reviewer results need a live session) — release-gate work.

**Open items that need Kyle**

- Phase 33.2: explicit go to spend usage on one bounded Claude Code / Codex
  batch (scenario count and token ceiling stated before the run).
- Ending the owner self-testing pause (only Kyle's explicit instruction).
- Test-audit rulings recorded in `PLAN.md` (Phase 30–32 test-audit
  proposals; test-audit round 1 deferred items).
