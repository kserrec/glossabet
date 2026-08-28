# CLAUDE.md

Guidance for coding agents working in this repository.

## What this is

Glossabet is a vocabulary system for codebases: a deterministic engine/CLI
plus the `/glossabet` agent skill as its primary interface. The machinery
gathers evidence, the LLM brainstorms and reasons, and the human decides what
becomes canonical — that division of labor is the product's central rule.

`PLAN.md` is the authoritative current roadmap and product-boundary summary.
Read its current gates before nontrivial work. The canonical skill at
`skill/SKILL.md` is the behavioral spec; its philosophy is preserved verbatim,
never diluted by machinery.

## Binding rules

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
  A path component named `glossabet-out` is not itself proof of tool ownership;
  repository-root refusal requires an exact regular current Glossabet artifact.
  A differently cased preserved spelling additionally requires available
  matching non-symlink directory identity with the lowercase output lookup,
  and uncertainty in a required check fails closed.
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
  wherever scopes overlap. Scope paths use NFC identity, so canonically
  equivalent Unicode spellings are one boundary. Drift and lexical validation
  enforce the boundary.
- **Unicode lexical contract.** Identifier and glossary terms use NFKC plus
  casefold, with documented acronym/digit and language-form rules. The scanner
  remains lexical, not parser-backed; comments and strings are not syntax-
  excluded.
- **Sensitive paths stay opaque.** Dotenv variants and other configured
  key/credential path families are excluded without reading their contents.
  Ordinary included source can still contain secrets, so outputs are not
  anonymized; `PRIVACY.md` is authoritative.
- **Staleness is a trust problem.** Evidence artifacts carry a git stamp; the
  skill never silently grounds itself on stale evidence.
- **Determinism.** Same repo state → same evidence output.
- **Graphify is optional, and its artifacts are never mutated.** Glossabet
  owns `glossabet-out/`; Graphify owns `graphify-out/`.
- **Dependencies earn their place.** Real use site + one-line cost/reason, or
  it doesn't enter. Stdlib-first. The labelled lexical cases currently leave
  no parser-specific accuracy failure that would justify a parser adapter.
- **Bounded work with logged truncation.** No unbounded quadratic analysis;
  every cap is stated and every drop reported — capped output never reads as
  complete. Treat `skipped.corpus_budget.complete: false` as partial evidence,
  never as repository-wide coverage.
- **Tests protect concrete threats**, not coverage numbers.
- **Project-owned writes require proven identity.** `sync-context` may replace
  only an exactly named regular host file whose identity and bytes remain
  stable; a case collision or indeterminate exact-name lookup is
  uninspectable, never permission to write.

## Workflow

- Honor any pause recorded at the top of `PLAN.md`. The current owner
  self-testing pause forbids outside maintainer invitations,
  release-candidate work, and publication setup until Kyle explicitly ends it.
- Execute one coherent roadmap chunk at a time. Split work before editing when
  it cannot be implemented and verified in one pass. `$next` selects the first
  eligible current item, implements and verifies one chunk, updates the plan,
  and stops.
- Each chunk ends with its acceptance checks and an accurate plan update.
- Ambiguous semantic choices stop with the competing options and their
  consequences rather than being decided by convenience.

## Fixing bugs and findings

Fixes follow the fix-loop rules carried by the `/bughunt`, `/audit`, and
`/test-audit` skills: root cause named before code, the regression test
covers the class not the proof, batches of at most ~10 fixes, a cold review
by a fresh agent as the last step of the same pass, and hunters turned into
suite tests. No fix-carrying commit without that review (Kyle, 2026-08-18).

## Commands

```bash
uv run pytest                    # test suite
uv run ruff check .              # lint gate (also CI's static job)
uv run mypy glossabet            # type gate (also CI's static job)
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
uv run python scripts/benchmark.py   # offline performance baseline (docs/PERFORMANCE.md)
uv run python evaluation/run.py --verify-results evaluation/results.json
uv run python scripts/agent_eval.py --verify-results evaluation/agent-results.json
uv run python evaluation/review.py --verify-results evaluation/reviewer-results.json
# each verifier checks genuineness; add --current for the release-gate currency check
uv run python scripts/check_distribution.py dist --tag v0.1.0
uv run python scripts/wheel_smoke.py dist
uv run python scripts/plugin_smoke.py dist # temporary local Codex lifecycle probe
```
