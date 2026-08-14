# Changelog

All notable changes to Glossarize are recorded here. The format follows
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
- The canonical agent skill and `glossarize install` for current Codex and
  Claude Code personal skill locations.
- A self-contained payment-service walkthrough, privacy/data-flow statement,
  multi-platform CI, distribution validation, and wheel install/uninstall
  smoke test.

### Security

- Repository-controlled reads and writes are bounded and symlink-safe;
  sensitive paths are excluded without claiming content-level secret
  scanning; target Git configuration cannot name executable hooks or monitors.
- Skill installation preserves a differing existing file unless `--force` is
  explicit and refuses symlinked destination components.
