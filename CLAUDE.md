# CLAUDE.md

Guidance for coding agents working in this repository.

## What this is

Glossabet is a vocabulary system for codebases: a deterministic engine/CLI
plus the `/glossabet` agent skill as its primary interface. The machinery
gathers evidence, the LLM brainstorms and reasons, and the human decides what
becomes canonical — that division of labor is the product's central rule.

`PLAN.md` is the only authoritative roadmap. Read its principles, non-goals,
and current phase before nontrivial work. The canonical skill at
`skill/SKILL.md` is the behavioral spec; its philosophy is preserved verbatim,
never diluted by machinery.

## Binding rules (digest — full versions in PLAN.md)

- **Human authority.** Never finalize vocabulary unilaterally; never
  mass-rename code. A term is meant to become canonical only after human
  approval — enforced as an instruction to the skill, not mechanically:
  `glossabet save` trusts its caller. Docs say "the skill is instructed
  to…", never "Glossabet cannot…".
- **Lexical-first scanner.** The built-in scanner provides lexical evidence
  and cheap import edges only. It must not grow into a static analyzer or a
  Graphify clone; rich structure comes from optional adapters.
- **No contamination.** Evidence gathering excludes `glossabet-out/`,
  `.glossabet/`, `GLOSSARY.md`, and the derived `GLOSSABET.md` report, always.
- **Three artifacts, kept separate.** `GLOSSARY.md` is the vocabulary humans
  agreed to use; `GLOSSABET.md` is Glossabet's derived vocabulary-health
  report (excluded from evidence and freshness, safe to regenerate, never
  canonical); `glossabet-out/glossary.json` is structured machine state.
  They never duplicate or replace one another.
- **Explicit production scope.** Root `glossabet.json` may add literal ignored
  prefixes or path roles. Tests/fixtures stay inventoried but do not steer
  lexical signals; generated/vendored content is not read. Every effective
  role and exclusion is reported.
- **Explicit concept scope.** Optional glossary `scope.path_prefixes` are
  literal repository-relative subsystem boundaries. Omission is
  repository-wide; aliases inherit scope; vocabulary ownership must be unique
  wherever scopes overlap. Drift and lexical validation enforce the boundary.
- **Unicode lexical contract.** Identifier and glossary terms use NFKC plus
  casefold, with documented acronym/digit and language-form rules. The scanner
  remains lexical, not parser-backed; comments and strings are not syntax-
  excluded.
- **No secrets ingested.** Sensitive files (`.env` and kin, keys, credentials)
  never enter any artifact; tests prove it.
- **Staleness is a trust problem.** Evidence artifacts carry a git stamp; the
  skill never silently grounds itself on stale evidence.
- **Determinism.** Same repo state → same evidence output.
- **Graphify is optional, and its artifacts are never mutated.** Glossabet
  owns `glossabet-out/`; Graphify owns `graphify-out/`.
- **Dependencies earn their place.** Real use site + one-line cost/reason, or
  it doesn't enter. Stdlib-first. Phase 16 measured 15/15 lexical labels and
  rejected a parser adapter with no remaining labelled gain.
- **Bounded work with logged truncation.** No unbounded quadratic analysis;
  every cap is stated and every drop reported — capped output never reads as
  complete. Treat `skipped.corpus_budget.complete: false` as partial evidence,
  never as repository-wide coverage.
- **Tests protect concrete threats**, not coverage numbers.

## Workflow

- Honor any pause recorded at the top of `PLAN.md`. The current owner
  self-testing pause forbids outside maintainer invitations, Phase 23, and
  publication setup until Kyle explicitly ends it.
- Implement exactly one PLAN phase per pass; split oversized phases in the
  plan before touching code. `$next` selects the first incomplete phase whose
  dependencies are complete, implements, verifies, marks complete, stops.
- Each phase ends with its acceptance check and a commit naming the phase.
- Ambiguous semantic choices stop with the competing options and their
  consequences rather than being decided by convenience.

## Fixing bugs and findings (binding — Kyle, 2026-08-18)

Every bughunt/audit round in this repo found gaps in the previous round's
own fixes. The cause each time was structural — a fix shaped by the one
demonstrated input, in a batch too large to verify well, checked by the
same eyes that wrote it — so these are rules, not reminders:

1. **A fix is fix + class-level test + cold review, in one pass.** No fix
   is done, and no fix-carrying commit is made, until a fresh agent that
   did not write the fix has read the diff with the brief "break it: which
   sibling input still gets through, what did the fix change beyond the
   bug, does it contradict its own comment/docstring/SECURITY.md claim",
   and every proven finding from that review is itself fixed. This is not
   an optional later round; it is the last step of the same pass.
2. **Name the wrong assumption before writing code, and the test must
   cover the class.** State the root cause in one sentence that does not
   mention the demonstrated input. The regression test asserts the class —
   the empty and the single-element, the zero and the maximum, the other
   call site, the other encoding — never only the input that proved it. If
   the test only encodes the proof, the fix is not done.
3. **Small batches.** At most ~10 fixes between cold reviews. A 30-fix pass
   is where the regressions came from; split it.
4. **Hunters become tests.** A generator or driver that found something
   (seeded fuzz over a trust boundary, an end-to-end flow on an odd repo)
   is turned into a bounded test in the suite in the same pass, so the
   class stays dead without waiting for the next hunter.

*(Origin: rounds 4–5 and audit round 5. Round-4 fixes: a regression (root
`GLOSSARY.md → docs/GLOSSARY.md` refused) and a coverage hole; audit fixes:
a memory-only budget that left a 192-second in-budget shape, and a workflow
checker with bypasses an hour after being hardened. Each was caught by a
cold review that cost about a fifth of a hunt.)*

## Commands

```bash
uv run pytest                    # test suite
uv tool install . --reinstall    # (re)install the CLI at ~/.local/bin/glossabet
glossabet --version
glossabet install               # install canonical skill for Codex (~/.agents/skills)
glossabet install --agent claude # install for Claude Code (~/.claude/skills)
glossabet scan <repo>           # writes <repo>/glossabet-out/evidence.json
glossabet analyze <repo>        # scan + terminology report (register, overlaps)
glossabet brief <repo>          # bounded read-only canonical vocabulary
glossabet sync-context <repo>   # explicit managed block in root AGENTS.md
glossabet sync-context <repo> --agent claude # explicit root CLAUDE.md target
glossabet show <repo>           # display the current glossary
glossabet drift <repo>          # live vocabulary vs canonical glossary
glossabet validate <repo>       # reconcile glossary vs evidence + graph
glossabet cache-clear           # remove Glossabet's own user cache (never a repo)
uv build --no-sources            # build wheel + source distribution, do not publish
uv run python scripts/build_plugin.py dist
uv run python scripts/check_workflows.py
uv run python evaluation/run.py --verify-results evaluation/results.json
uv run python scripts/agent_eval.py --verify-results evaluation/agent-results.json
uv run python evaluation/review.py --verify-results evaluation/reviewer-results.json
# each verifier checks genuineness; add --current for the release-gate currency check
uv run python scripts/check_distribution.py dist --tag v0.1.0
uv run python scripts/wheel_smoke.py dist
uv run python scripts/plugin_smoke.py dist # temporary local Codex lifecycle probe
```
