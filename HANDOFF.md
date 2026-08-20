# Session handoff — 2026-08-20

This section records the current stopping point. It becomes stale when the
plain-language documentation review or the newcomer-style product test resumes.

## Current stopping point

Kyle began testing Glossabet as a person encountering it for the first time.
The intended test is the complete Glossabet workflow on one or two of his
repositories. Mirafold had previously been tried with the original skill, but
not with the complete current project. This test did not reach the complete
repository workflow: the introductory documentation and guidance repeatedly
used unexplained Glossabet-specific shorthand, so the session changed to a
documentation-language review before testing continued.

At the first orientation prompt, Kyle summarized Glossabet this way:
Glossabet first follows a deterministic path through the repository's words,
then an agent analyzes the results and proposes names, and humans decide which
names to adopt. He reported nothing unclear at that exact point. The later
problem was the writing itself. In particular, phrases such as
“missing-command failure” compressed an ordinary condition into a label whose
meaning existed only inside this project.

Kyle's ruling is precise:

- Established terms from programming, testing, Git, packaging, and similar
  fields are allowed when they suit the intended reader.
- Glossabet-specific shorthand is allowed only for a recurring concept that
  the project deliberately establishes as a canonical term.
- A project-specific term must be clearly defined before the reader is
  expected to understand it, or the document must explicitly direct the
  reader through an earlier definition.
- The README assumes no previous knowledge of Glossabet. It must define a
  Glossabet-specific term before its first use.
- One-off compressed labels and metaphors are not canonical terminology. They
  must be replaced with a direct description of the actual command,
  condition, or result.

The repository started this work clean on `main`, equal to `origin/main`.
Within the language rewrite, only `README.md` has been edited so far;
`HANDOFF.md` records this pause. The README's opening, source-installation
instructions, first-use walkthrough, generated-file explanation, core term
definitions, Graphify introduction, evaluation summary, command list, and
most of the `inspect` explanation have been rewritten for a new reader. The
rewrite is deliberately unfinished. Starting at the `glossabet brief <repo>`
paragraph, the rest of the README still contains dense project-specific
phrasing. The proposed table of core terms also needs to be reviewed as part
of the complete pass; its presence does not mean Kyle approved every term in
the table.

No other documentation has been rewritten yet. The requested scope is every
documentation and human-facing prose surface in the project, including the
canonical skill and its plugin copy, command help and error text, comments,
docstrings, examples, evaluation instructions, release instructions,
architecture and security documents, planning history, and fixture READMEs.
The durable language rule still needs to be added to the contributor and
maintainer instructions. Do not turn every repeated phrase into a glossary
term merely to preserve it; first ask whether the project actually needs that
named concept.

## Resume here

1. Read this section and inspect the existing `README.md` diff. Preserve the
   completed plain-language opening unless the review finds a concrete problem.
2. Finish the README from `glossabet brief <repo>` onward. Keep the README
   self-contained and define every Glossabet-specific term before using it.
3. Add the durable language rule to `CONTRIBUTING.md` and `CLAUDE.md`, then
   audit every other human-facing prose surface under the scope above.
4. Keep the canonical `skill/SKILL.md` and
   `plugins/glossabet/skills/glossabet/SKILL.md` identical. If the skill
   changes, rebuild and verify the checked-in plugin package through the
   project's existing release scripts.
5. Run the relevant documentation checks, distribution check when applicable,
   and complete test suite. Report documentation, executable code, tests, and
   comments separately.
6. After the documentation is understandable to a first-time reader, restart
   the complete newcomer-style test on Mirafold or another repository. Walk
   Kyle through exactly one action at a time and do not assume knowledge of
   Glossabet's terminology.

No additional live model run, paid evaluation, publication, or release was
authorized in this session.

## Previous handoff — 2026-08-18 (late)

Refreshed after the 2026-08-18 Phase 33.2 first automated attempt and its
offline correction
(Phases 38–44 also done:
config discoverability + skill shortening, layer subpackages, refactor pass,
bughunt rounds 4–6, audit round 5, **test audit round 1**; all rulings that
were open are settled — see PLAN Phase 42/44 and "Rulings"). It becomes stale
when the next phase begins. The session began with `main` = `origin/main` at
`7b636659f39e277fefe2ff1a33333496f95b9b7f`; this wrapup covers the Phase 33.2
evaluator, tests, static evaluation records, PLAN/HANDOFF updates, one retained
failed raw run, and its current-result mirror. The full suite is 644/644 green
(79.43 s final wrapup run); wheel and plugin
remain the builds made after Phase 44,
`glossabet check_distribution dist --tag v0.1.0` passes, the CLI at
`~/.local/bin/glossabet` is the current build. The next Phase 33.2 action needs
fresh authorization for a corrected bounded three-call live batch; no further
Claude call is authorized now. The owner self-testing pause is still active
(never prompt him to test).
Kyle's standing rule from today: no "future bughunts" — a known-needed
bughunt runs now, or as soon as its open questions are settled.

**Addendum — normal Claude Code smoke test, 2026-08-18:** the current
Glossabet 0.1.0 Claude Code skill/plugin is installed at
`~/.claude/skills/glossabet/`. Kyle launched his ordinary `claude` command
from `examples/payment-service` on Claude Code 2.1.235/Linux. An ambient
orientation response used the canonical Payment Attempt, Gateway Client, and
Authorization vocabulary and explicitly identified the SessionStart-injected
brief; `/glossabet` was also invocable and correctly resumed the managed
glossary without re-proposing its three settled concepts or writing files.
The repository remained clean at `7b636659f39e277fefe2ff1a33333496f95b9b7f`
with `main` equal to `origin/main`. This is partial manual smoke evidence, not
Phase 33.2 acceptance: the ambient response used project-reading commands, no
no-glossary scenario ran, the profile was not isolated, and no digest-bound
raw transcript was captured. The earlier isolated evaluator stopped at auth
preflight before a model call; its temporary state was believed removed, but
the later live-evidence checks found one older residue described below. The
subsequent temporary isolated login did not complete because its passkey flow
was unlike Kyle's normal login. The cause is unverified. Do not repeat that
isolated-login route. PLAN Phase 33.2 now carries the replacement design: use
normal signed-in authentication without reading or changing auth state;
isolate the three fixture repositories under `/tmp`; disable model tools,
MCP, and session persistence; capture hook events and digest-bound raw
evidence; abort instead of opening any login flow.

**Addendum — Phase 33.2 offline evaluator, 2026-08-18:**
`scripts/claude_eval.py`, `tests/test_claude_evaluation.py`,
`evaluation/claude-scenarios.json`,
`evaluation/claude-response-schema.json`, and the initially empty
`evaluation/claude-history.json` now implement the replacement design. The
focused fake-host suite was 20/20 green and the full repository suite was
643/643 green. Before the live attempt, `--verify-history` reported an empty
genuine ledger, so the implementation pass itself made no Claude model call.
The fake host proves exact call count and command
confinement, normal-profile environment sanitization, auth/plugin preflight,
failure retention, trace-derived semantic verification, SHA-256 tamper
detection, and owned `/tmp` cleanup.

**Addendum — Phase 33.2 first automated attempt, 2026-08-18 local:** Kyle
authorized one exact three-call normal-profile batch with no retry. Attempt
`20260819T043823Z-claude-full-25584658` passed Claude Code 2.1.235/Linux auth
and plugin preflight, then all three local processes exited before hooks or
model use because `evaluation/claude-response-schema.json` declared Draft
2020-12 while Claude Code's structured-output validator uses Draft 7. The
retained result is 0/3 with exactly zero input/output tokens and no reported
cost. Safety passed: no tools, writes, retry, or canary leaks; current scratch
cleanup passed. The immutable raw run's SHA-256 is
`9dbb8bfa4fb29bd5b25e9d1942646ae87aea89cd33655bdf460084f51b6803c5`;
history retains one attempt and the current-result mirror matches it. The
newer-draft declaration and the verifier's false `empty` message were then
corrected offline; focused tests are 21/21 and the full suite is 644/644. No
second live batch ran, so Phase 33.2 and the documentation flip remain open.
The mirror is intentionally non-current after those corrections: current-input
verification rejects both its prior input identity and its 0/3 result, while
history integrity passes.

Independent cleanup verification also found
`/tmp/glossabet-claude-eval-6dup075u`, born at 20:31 local and shaped as the
old isolated `home` design. It predates the 21:38 normal-profile batch and is
not that batch's removed scratch tree. Its authentication-file contents were
not read. Kyle separately authorized deletion of that exact path; it was
removed and verified absent. The final wrapup then removed the names-only
backlog of 45 other top-level `/tmp/glossabet-*` directories and 31 files from
earlier project sessions after confirming no process used them. No contents
were read, and no top-level `/tmp/glossabet-*` entry remains.

Earlier text below (Phase 36/37 era) is kept for orientation; where it
disagrees with the paragraph above, the paragraph above wins. `PLAN.md` remains the
authoritative durable roadmap; read its status line, the Phase 36 plan, and
the owner self-testing pause before doing anything.

**Project:** Glossabet is a Python CLI, canonical agent skill
(`skill/SKILL.md`), and Codex/Claude Code plugin for making a codebase's
vocabulary explicit, canonical, inspectable, and maintainable. Deterministic
machinery gathers evidence, the LLM reasons, the human decides.

**State on disk:** work happens directly on `main` (Kyle retired the
`dev` branch on 2026-08-17 — "we're not publicly inviting anyone to this
yet"; local and remote `dev` were deleted after fast-forwarding `main`;
recreate a branch only if outside collaboration begins); the working tree is
clean; the full suite (529 tests) is green; wheel and plugin were rebuilt
through `uv build --no-sources` + `scripts/build_plugin.py dist` and
`scripts/check_distribution.py dist --tag v0.1.0` passes; the CLI at
`~/.local/bin/glossabet` is the current build. The Claude Code skill/plugin at
`~/.claude/skills/glossabet/` is installed from that build and has the live
smoke evidence summarized above. The Codex personal skill at
`~/.agents/skills` is whatever Kyle last installed; re-run `glossabet install`
if its currency matters.

**Addendum 2026-08-17 (pre-testing trust/legal review — Phase 37, done):**
before starting owner testing Kyle asked for overlooked legal/ethical/trust
items; eleven were raised, each ruled on by Kyle, then executed in one pass
and committed as Phase 37 (see PLAN.md). Net effect for testing: `glossabet
brief` output now opens with an origin line; `glossabet cache-clear` exists;
the skill's Step 6 tells the user to commit `glossabet-out/glossary.json`;
README/PLAN/CLAUDE.md say human approval is a skill instruction, not a
mechanical guarantee; `CONTRIBUTING.md` (DCO), README "Provenance and
affiliation", `NAME-CLEARANCE.md` correction (Amharic *bet*), RELEASING
claims checklist; Apache-2.0 confirmed as Kyle's own choice. Wheel/plugin
rebuilt; suite 531 green; installed-agent `--current` currency lapses until
the next authorized Codex batch (genuineness still passes). **Reinstall
before testing:** `uv tool install . --reinstall`, then
`glossabet install --agent claude` / `glossabet install`.

**Completed this session**

- Kyle's decisions this session: authorized the Phase 36.7 Codex batch
  ("go for the 36.7 batch", 2026-08-18; spent 790 k input / 11 k output
  tokens, recorded in PLAN-ARCHIVE.md under Phase 36.7); asked for docs
  sync, PLAN prune, and commit + push with `main` fast-forwarded to `dev`.
- Kyle is now taking the build for owner self-testing (reinstall first:
  `uv tool install . --reinstall`, then `glossabet install --agent claude`
  / `glossabet install`).

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

**Kyle's next session: owner self-testing (start here)**

1. Reinstall so the CLI and skill are today's build (the tree moved through
   Phases 36.1–36.7 since the last install; behaviour is intended to be
   identical, which is exactly what the testing checks):
   `uv tool install . --reinstall` → `glossabet --version` prints
   `glossabet 0.1.0`; then `glossabet install --agent claude` (Claude Code)
   and/or `glossabet install` (Codex).
2. Test freely: `scan`/`analyze`/`inspect`/`brief`/`drift`/`validate`/
   `show`/`sync-context` on any repository, and the `/glossabet` skill in the
   agent host. Nothing in Phase 36 was meant to change any output.
3. If something looks off, it can be checked against the pre-refactor
   baseline: the command oracle recipe is under "How to resume" below (the
   scratchpad copies from this session are gone; rebuild takes ~1 minute),
   and the pre-Phase-36 code is commit `0466822` for a side-by-side run.
4. Anything Kyle finds becomes a plan item, not an on-the-spot fix; the
   owner self-testing pause stays active until he explicitly ends it.

**How to resume**

- `$next` / `/next` → the first incomplete phase whose dependencies are
  complete is Phase 33.2 or Phase 36.8. Phase 33.2 now has partial
  normal-profile smoke evidence and a binding authentication-safe replacement
  design. Its first automated batch is a retained pre-model schema miss, its
  Draft 7 correction is offline-tested, and all known Glossabet `/tmp` residue
  is gone. Request fresh authorization for exactly three normal-profile Claude
  Code calls, no retry,
  at the count and limits written in PLAN; without that exact authorization,
  run only the offline verifiers. Both phases honour the owner
  self-testing pause. Phase 36.8 steps 1–2 (evaluator code) can likewise be
  written before authorization; only its run needs it.
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

- Phase 33.2: fresh authorization for exactly three Claude Code calls on
  Kyle's existing Max
  subscription, no retry, at no more than 200,000 input / 6,000 output tokens
  estimated total and a $0.25 CLI cap per call, plus one evaluator-owned `/tmp`
  directory that is deleted and verified absent. Normal authentication is
  reused; no login/logout/setup-token action is allowed. The 2026-08-18 manual
  smoke test is partial evidence and must not be promoted to acceptance.
- Ending the owner self-testing pause (only Kyle's explicit instruction).
- Test-audit rulings recorded in `PLAN.md` (Phase 30–32 test-audit
  proposals; test-audit round 1 deferred items).
