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
- **No secrets ingested.** Sensitive files (`.env` and kin, keys, credentials)
  never enter any artifact; tests prove it.
- **Staleness is a trust problem.** Evidence artifacts carry a git stamp; the
  skill never silently grounds itself on stale evidence.
- **Determinism.** Same repo state → same evidence output.
- **Graphify is optional, and its artifacts are never mutated.** Glossarize
  owns `glossarize-out/`; Graphify owns `graphify-out/`.
- **Dependencies earn their place.** Real use site + one-line cost/reason, or
  it doesn't enter. Stdlib-first.
- **Bounded work with logged truncation.** No unbounded quadratic analysis;
  every cap is stated and every drop reported — capped output never reads as
  complete.
- **Tests protect concrete threats**, not coverage numbers.

## Workflow

- Implement exactly one PLAN phase per pass; split oversized phases in the
  plan before touching code. `$next` selects the first incomplete phase whose
  dependencies are complete, implements, verifies, marks complete, stops.
- Each phase ends with its acceptance check and a commit naming the phase.
- Ambiguous semantic choices stop with the competing options and their
  consequences rather than being decided by convenience.

## Commands

None yet — Phase 1 establishes the package and CLI. This section is updated as
phases land.
