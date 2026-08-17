# Session handoff — 2026-08-17

Refreshed at the end of the 2026-08-17 session (Phases 34 and 35). It
becomes stale when the next phase begins. `PLAN.md` remains the
authoritative durable roadmap; read its status line, the Phase 36 plan, and
the owner self-testing pause before doing anything.

**Project:** Glossabet is a Python CLI, canonical agent skill
(`skill/SKILL.md`), and Codex/Claude Code plugin for making a codebase's
vocabulary explicit, canonical, inspectable, and maintainable. Deterministic
machinery gathers evidence, the LLM reasons, the human decides.

**State on disk:** `dev` and `main` carry the same commits; the working tree
is clean; the full suite (493 tests) is green; wheel and plugin were rebuilt
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
- **Phase 36 planned, not started** — the seven remaining structural debts
  from the post-refactor review (evidence.py hub split, one command
  preamble, document accessors, managed-context printer direction,
  producer-level drift/validation tests, ledger ceremony, verification
  weight onto the skill). Each sub-phase is one pass under Phase 35 rules.

**How to resume**

- `$next` / `/next` → the first incomplete phase whose dependencies are
  complete is Phase 33.2 (needs Kyle's authorization to spend usage) or
  Phase 36.1 (no external needs). Both honour the owner self-testing pause.
- Before any Phase 36 sub-phase, rebuild the byte-identical oracle: copy the
  four local fixtures from `evaluation/corpus.json` (`path` sources) to a
  scratch dir, `glossabet save` each source's `glossary`, run every command
  (`scan`, `analyze`, `inspect [--full] [--no-graphify]`, `drift`,
  `validate`, `show`, `brief`, `sync-context [--agent claude]`, cache-warm
  `scan`) with `GLOSSABET_CACHE_DIR` pointed at scratch, capture
  stdout/stderr and every `glossabet-out/*.json`, and diff after each step.
  Do not include a scan of this repository itself in the oracle — the
  refactor changes the source it reads.
- The evaluation `--current` verifiers for agent/reviewer results are
  expected to be stale (skill hash moved in Phases 31–34); Phase 33.2 /
  36.7 own re-running them.

**Open items that need Kyle**

- Phase 33.2: explicit go to spend usage on one bounded Claude Code / Codex
  batch (scenario count and token ceiling stated before the run).
- Ending the owner self-testing pause (only Kyle's explicit instruction).
- Test-audit rulings recorded in `PLAN.md` (Phase 30–32 test-audit
  proposals; test-audit round 1 deferred items).
