# CLAUDE.md

Guidance for coding agents working in this repository.

## What this is

Glossarize is a vocabulary system for codebases: a deterministic engine/CLI
plus the `/glossarize` agent skill as its primary interface. The machinery
gathers evidence, the LLM brainstorms and reasons, and the human decides what
becomes canonical — that division of labor is the product's central rule.

`PLAN.md` is the only authoritative roadmap. Read its principles, non-goals,
and current phase before nontrivial work. The existing skill (to live at
`skill/SKILL.md`) is the behavioral spec; its philosophy is preserved
verbatim, never diluted by machinery.

## Binding rules (digest — full versions in PLAN.md)

- **Human authority.** Never finalize vocabulary unilaterally; never
  mass-rename code. Only human approval makes a term canonical.
- **Lexical-first scanner.** The built-in scanner provides lexical evidence
  and cheap import edges only. It must not grow into a static analyzer or a
  Graphify clone; rich structure comes from optional adapters.
- **No contamination.** Evidence gathering excludes `glossarize-out/`,
  `.glossarize/`, and `GLOSSARY.md`, always.
- **Explicit production scope.** Root `glossarize.json` may add literal ignored
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
- **Graphify is optional, and its artifacts are never mutated.** Glossarize
  owns `glossarize-out/`; Graphify owns `graphify-out/`.
- **Dependencies earn their place.** Real use site + one-line cost/reason, or
  it doesn't enter. Stdlib-first. Phase 16 measured 15/15 lexical labels and
  rejected a parser adapter with no remaining labelled gain.
- **Bounded work with logged truncation.** No unbounded quadratic analysis;
  every cap is stated and every drop reported — capped output never reads as
  complete. Treat `skipped.corpus_budget.complete: false` as partial evidence,
  never as repository-wide coverage.
- **Tests protect concrete threats**, not coverage numbers.

## Workflow

- Implement exactly one PLAN phase per pass; split oversized phases in the
  plan before touching code. `$next` selects the first incomplete phase whose
  dependencies are complete, implements, verifies, marks complete, stops.
- Each phase ends with its acceptance check and a commit naming the phase.
- Ambiguous semantic choices stop with the competing options and their
  consequences rather than being decided by convenience.

## Commands

```bash
uv run pytest                    # test suite
uv tool install . --reinstall    # (re)install the CLI at ~/.local/bin/glossarize
glossarize --version
glossarize install               # install canonical skill for Codex (~/.agents/skills)
glossarize install --agent claude # install for Claude Code (~/.claude/skills)
glossarize scan <repo>           # writes <repo>/glossarize-out/evidence.json
glossarize analyze <repo>        # scan + terminology report (register, overlaps)
glossarize show <repo>           # display the current glossary
glossarize drift <repo>          # live vocabulary vs canonical glossary
glossarize validate <repo>       # reconcile glossary vs evidence + graph
uv build --no-sources            # build wheel + source distribution, do not publish
uv run python scripts/check_workflows.py
uv run python evaluation/run.py --verify-results evaluation/results.json
uv run python scripts/check_distribution.py dist --tag v0.1.0
uv run python scripts/wheel_smoke.py dist
```
