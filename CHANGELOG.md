# Changelog

All notable changes to Glossabet are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0 - Unreleased

This first alpha is prepared but has not been published to PyPI.

### Added

- `GLOSSABET.md`, the repository vocabulary-health report: the skill writes
  Glossabet's analysis (gaps, overloads, suspected synonyms, drift,
  glossary/code disagreement, structural findings, proposals, open
  questions, coverage limits) at the scan root as one refreshed report,
  separate from the canonical `GLOSSARY.md` and the structured
  `glossabet-out/glossary.json`. The engine excludes it from lexical
  evidence at any depth (`skipped.self_reports`) and from the freshness
  stamp at the root; `GLOSSARY.md` stays visible to freshness.
- Claude Code ambient parity: `glossabet install --agent claude` makes the
  personal skill folder a skills-directory plugin with a `SessionStart` hook
  that runs `brief .`, writing nothing outside that folder; `--skill-only`
  opts out.
- Deterministic lexical repository evidence with explicit scope, budgets,
  Git freshness, incremental caching, and optional Graphify structure.
- Terminology nominations, persistent human-governed glossaries, vocabulary
  drift checks, scoped concepts, stable bindings, and reconciliation reports.
- Unicode-aware lexical normalization and a reproducible calibration corpus
  with documented limitations and release thresholds.
- Labelled Graphify structural and truncation fixtures, a blinded
  second-reviewer lane, and a 14-scenario installed-Codex boundary harness
  with bounded traces and exact temporary-plugin cleanup.
- Conservative source-language builtin tagging (currently Python) that retains
  complete lexical evidence while reserving terminology and naming budgets for
  project-domain vocabulary.
- Self-accounting house-register statistics that separate structurally styled
  names from corroborated flat spellings, exclude language/prose noise with
  explicit reasons, and carry a labelled dominant-style/multi-word evaluation
  across the pinned corpus and Glossabet itself.
- Distinctive term nominations that require explicit domain tags, reuse the
  existing compound-pattern and bounded context-dispersion evidence, label
  canonical-name versus disambiguation intent, and carry an exact
  repository-level evaluation gate without making naming decisions for the
  human.
- Pre-existing `GLOSSARY.md` adoption: the engine discovers a repository's
  own root `GLOSSARY.md` as a separate metadata-only `repository_glossary`
  context channel (presence, safe-read status with a named reason, size,
  SHA-256, nested files reported but never consulted) while keeping it out
  of lexical evidence at every depth; the skill distinguishes no-glossary /
  adoption / resume / managed states, forms its own naming baseline before
  reading the document, reconciles into named categories, promotes nothing
  to canonical without the human, and never regenerates a maintainer-owned
  `GLOSSARY.md` wholesale (schema-v3 agent context). With both files present,
  `inspect` and `validate` (validation schema 8) add a bounded lexical
  term-presence divergence check — canonical terms absent from the Markdown
  and superseded aliases still present — never a meaning comparison.
- A compact schema-v2 routine agent context with vocabulary module rollups,
  file locations only on nomination/read targets, an 80 KB self-repository
  regression target, explicit projection omissions, and `inspect --full` for
  the former detailed diagnostic shape.
- A deterministic `glossabet brief` command that reads only validated glossary
  state plus the hardened Git stamp and emits at most 4 KB of read-only
  canonical vocabulary with explicit projection coverage.
- An explicit `glossabet sync-context` fallback that persists one
  semantic-glossary-stamped managed block in root `AGENTS.md` (Codex default)
  or root `CLAUDE.md` (explicit Claude target), plus read-only stale/edit checks
  in drift and validation.
- The canonical agent skill and `glossabet install` for current Codex and
  Claude Code personal skill locations.
- A version-coupled Codex plugin prototype carrying the canonical skill and a
  matching dependency-free CLI wheel, plus real install/update/remove smoke
  coverage on Codex CLI 0.147.0 for Linux.
- A Codex `SessionStart` hook that runs the bundled bounded `brief .` command
  at startup, resume, clear, and compaction, contributes nothing without a
  glossary, and keeps all vocabulary changes behind the human-invoked skill.
- A self-contained payment-service walkthrough, privacy/data-flow statement,
  multi-platform CI, distribution validation, and wheel install/uninstall
  smoke test.

### Changed

- Internal restructuring with no behaviour change (every command's output on
  the local corpus fixtures is byte-identical): the hardened Git stamp and
  freshness pathspec live in `glossabet.git_state`; one bounded read
  discipline (`read_bounded_json` / `read_bounded_bytes`, `cap + 1` bytes,
  named outcomes) replaces five stat-then-read copies; the scanner owns an
  exclusion ledger; the managed host-file block lives beneath both its
  users; the production identifier vocabulary is one public aggregate
  (`ProductionVocabulary`) instead of parallel dicts; drift and validation
  share one findings-document module and renderer; the evidence hub is
  split into assembly (`evidence`), per-file extraction with cache reuse
  (`extraction`), and the `scan`/`analyze` handlers and printer
  (`evidence_report`), with production doc words folded into a
  `DocumentationVocabulary`; one command preamble (`engine_run.open_run`)
  decides for every command whether a glossary is needed and reports a
  missing directory or bad/absent glossary in one style, and the `show`/
  `save` commands move out of the glossary model into `glossary_commands`.
- The pre-release working identity was renamed atomically from Glossarize to
  Glossabet across the package, import, command, skill, artifacts,
  configuration, cache, tests, and documentation. Pre-rename output/cache
  directories remain excluded inputs and are never migrated or deleted.
- The hosted repository, configured remote, package project links, and private
  security-report URL now use `kserrec/glossabet`. The version-coupled plugin
  wheel and installed-agent evidence were regenerated against that exact
  metadata; executable wheel entries did not change.
- Installed-agent plugin identity now excludes interpreter-generated
  `__pycache__` directories. A clean GitHub Actions checkout proved that the
  previous identity could bind ignored local bytecode; the replacement matrix
  then proved that sorting native `Path` objects produced a different mixed-case
  file order on Windows. Identity now sorts canonical POSIX relative-path
  strings, with focused regressions for both clean-checkout and cross-platform
  parity. Public-main CI for commit `2be99b6` passed all 15 Python/operating-
  system matrix jobs plus the evidence, build, and distribution-smoke job.
- The checked-in plugin wheel and canonical skill carry the same Phase 28.2
  engine as the standalone source tree. Installed-agent evidence now separates
  a deterministic current-artifact/safety gate from stochastic command-choice
  reliability. The append-only Phase 28.1 ledger retains all six authorized
  attempts—four procedural passes and two failures—instead of selecting a
  green retry; future full runs use unique raw paths and record preflight
  aborts. Result schema v4 also derives the standalone-boundary summary from
  its scenario, correcting the unconditional legacy-v3 field without rewriting
  the retained historical result.
- Installed-agent evidence now archives every new authenticated raw result
  under a unique immutable path and treats `evaluation/agent-results.json` as
  a current-result mirror accepted only when its SHA-256 matches retained
  history and its complete input identity matches the current artifact.
  Phase 28.2 adds a separate fresh-session hook probe before the existing
  plugin and isolated missing-CLI host runs. Both authorized 12/12 batches
  passed on Codex CLI 0.147.0/Linux; the replacement result binds the final
  metadata-only rebuilt wheel, and both removed all temporary host state.

- Bounded analysis collections now share exact coverage ledgers; terminology,
  naming, Graphify, drift, and validation propagate every known omission.
- Graphify reconciliation matches complete member-token sets with exact
  provenance classification, and downstream glossary checks use bounded
  indexes, capped overload-dispersion work, and streamed boundary accounting
  instead of unbounded cross-product scans.
- CI and manual publication now share one full supported-platform quality gate;
  policy mutation tests prevent matrix or dependency-chain weakening.
- Evaluation results now identify the current engine and every corpus by
  digest; release checks recompute local structural evidence, aggregates, and
  thresholds and reject stale or weakened deterministic, installed-agent, or
  second-reviewer evidence.
- Hatchling is constrained to the reviewed 1.32.x build-only line; pytest
  remains the sole development dependency and the wheel remains dependency-free.

### Security

- Repository-controlled reads and writes are bounded and symlink-safe;
  sensitive paths are excluded without claiming content-level secret
  scanning; target Git configuration cannot name executable hooks or monitors.
- Skill installation preserves a differing existing file unless `--force` is
  explicit and refuses symlinked destination components.
- Managed context targets are fixed, regular bounded UTF-8 files; symlinks and
  ambiguous markers are refused, surrounding bytes/mode are preserved,
  atomic failure and detected concurrent edits keep the prior file, and edited
  managed content requires explicit `--force`.
- Synchronized glossary blocks are excluded from lexical evidence, with cache
  schema 4 invalidating pre-exclusion entries so ambient context cannot echo
  canonical words back into drift.
