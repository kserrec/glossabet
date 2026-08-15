# Changelog

All notable changes to Glossabet are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0 - Unreleased

This first alpha is prepared but has not been published to PyPI.

### Added

- Deterministic lexical repository evidence with explicit scope, budgets,
  Git freshness, incremental caching, and optional Graphify structure.
- Terminology nominations, persistent human-governed glossaries, vocabulary
  drift checks, scoped concepts, stable bindings, and reconciliation reports.
- Unicode-aware lexical normalization and a reproducible calibration corpus
  with documented limitations and release thresholds.
- Labelled Graphify structural and truncation fixtures, a blinded
  second-reviewer lane, and an 11-scenario installed-Codex boundary harness
  with bounded traces and exact temporary-plugin cleanup.
- The canonical agent skill and `glossabet install` for current Codex and
  Claude Code personal skill locations.
- A version-coupled Codex plugin prototype carrying the canonical skill and a
  matching dependency-free CLI wheel, plus real install/update/remove smoke
  coverage on Codex CLI 0.147.0 for Linux.
- A self-contained payment-service walkthrough, privacy/data-flow statement,
  multi-platform CI, distribution validation, and wheel install/uninstall
  smoke test.

### Changed

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
  previous identity could bind ignored local bytecode, and a focused regression
  test now preserves clean-checkout parity.

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
