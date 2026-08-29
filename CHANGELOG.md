# Changelog

All notable changes to Glossabet are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0 - Unreleased

Glossabet 0.1.0 is an unreleased source alpha under owner self-testing. It has
not been published to PyPI or a public plugin directory.

### Added

- A standard-library `glossabet` CLI with `scan`, `analyze`, `inspect`,
  `brief`, `show`, `save`, `drift`, `validate`, `sync-context`, `cache-clear`,
  and `install` commands.
- Deterministic lexical repository evidence with path-role configuration,
  Unicode-aware identifier tokenization, approximate imports, production and
  documentation vocabulary, naming candidates, terminology signals,
  monorepo detection, hardened Git freshness, explicit work budgets, and
  omission ledgers.
- A user-owned content-digest extraction cache and a conservative cleanup
  command that removes only recognized Glossabet cache entries.
- Optional Graphify adaptation with bounded tolerant normalization, provenance
  discounting, freshness states, structural groups, structural naming
  candidates, and lexical-only fallback for absent or unusable input.
- A validated human-governed structured glossary with scoped concepts,
  aliases, bindings, semantic hashes, atomic persistence, drift reports, and
  glossary/evidence/structure reconciliation.
- Safe discovery of a maintainer-owned root `GLOSSARY.md`. It remains outside
  lexical evidence and is surfaced to the skill as metadata; validation can
  report bounded lexical term-presence divergence without comparing meaning.
- A derived root `GLOSSABET.md` vocabulary-health report written by the skill
  and excluded from future evidence so its proposals cannot support
  themselves.
- A bounded schema-v6 agent context with lean and full projections. Its
  coverage separates source completeness, projection completeness,
  intentional protocol exclusions, source omissions, limit-driven
  truncations, and the limits actually applied. A separate deterministic 4
  KiB `brief` contains canonical vocabulary only.
- Explicit managed-context synchronization into one marked block in root
  `AGENTS.md` or `CLAUDE.md`, with read-only stale/edit detection in drift and
  validation.
- The canonical `/glossabet` / `$glossabet` skill: deterministic evidence and
  relevant production files ground a three-ranked-name brainstorm, while the
  human decides what becomes canonical. The engine validates saved data but
  cannot verify that approval occurred.
- Standalone Codex/Claude skill installation and a Claude skills-directory
  plugin option with a SessionStart brief hook; differing existing files are
  preserved unless `--force` is explicit.
- A version-coupled Codex plugin containing the canonical skill, bounded
  SessionStart hook, digest-checking runner, and one dependency-free wheel.
- Reproducible deterministic, installed-agent, Claude-host, and blinded
  reviewer evidence with digest-bound results and append-only live-attempt
  histories.
- A labelled calibration corpus, multilingual lexical fixture, complete and
  truncating structural fixtures, generated scale benchmarks, user
  walkthrough, supported Python 3.10–3.14 operating-system matrix, and
  distribution/wheel/plugin smoke checks.
- Apache-2.0 licensing, DCO contribution terms, privacy and threat-model
  documentation, provenance disclosure, and explicit non-affiliation with
  OpenAI, Anthropic, GitHub, and Graphify Labs.

### Changed

- Internal architecture now uses feature-oriented packages and an honest
  infrastructure boundary. Command orchestration lives in
  `glossabet.command_run`; the dependency-free managed-block format lives in
  `glossabet.managed_block`; runtime modules import no domain features.
- Typed evidence documents are read directly. Only compatibility-tolerant and
  derived evidence meaning remains in `analysis.evidence_facts`, and the
  dynamic finding-section view remains where it supplies real narrowing.
- Graphify input normalization crosses into group construction through one
  frozen `GraphInput` result. Reconciliation consumes named `BindingFindings`,
  `StructuralValidation`, and `GraphStatus` results instead of long positional
  tuples or private sibling operations.
- Removed unused JSON/runtime wrappers, trivial document views, source-shape
  key ratchets, obsolete type-contract tests, and construction-phase comments.
  Persisted schemas and command behavior remain unchanged.
- Workflow policy now uses PyYAML 6.0.3 for real YAML parsing, actionlint
  1.7.12 for standard GitHub Actions validation, and a smaller checker for
  Glossabet-specific matrix, dependency, permission, pin, credential, and
  release invariants.
- Performance coverage separates fast default smoke measurements from
  generated opt-in scale cases. No production optimization was made without a
  measured bottleneck.
- Concept scope paths now use one NFC identity across validation,
  duplicate/overlap ownership checks, lookup, semantic hashing, load, and
  deterministic persistence. Existing schema-1 files remain accepted and are
  normalized in memory without a schema migration.
- Command boundaries now keep successful JSON parsing separate from input
  failure, require confirmed exact host-file names before `sync-context`
  writes, and recognize `glossabet-out` ownership from exact regular current
  artifacts. Differently cased preserved output names additionally require
  matching non-symlink directory identity; unrelated similarly named ancestors,
  lowercase symlink aliases, and artifact-shaped special entries remain
  ordinary paths. Exact-entry lookup errors remain explicit uncertainty, while
  disagreement with an earlier managed-host observation is a detected change,
  not absence or a filename collision. An existing host file whose portable
  identity is unavailable is uninspectable rather than assumed unchanged.
- Numeric occurrence facts now pair `count`, `files`, and `modules` with
  literal `count_exact`, `files_exact`, and `modules_exact` flags. Exact global
  identifier module totals survive bounded location samples, while
  `locations_truncated` describes only the displayed locations. Repository
  evidence, drift, validation, and agent-context schemas advance together.
- Drift and validation now share one unproven-zero rule across corpus, table,
  scope-location, matching-work, and term-limit omissions. Fragmentation uses
  `modules_exact` identically for simple and compound terms: an above-threshold
  lower bound is reported as “at least,” while an inexact below-threshold
  result is suppressed and recorded as incomplete. Fragmentation findings now
  persist `module_spread_exact`, advancing the derived validation schema to 10.
- Graph state now uses the same always-present `present`, `usable`, `freshness`,
  and `warnings` fields in evidence, agent context, and validation. Validation
  separately records which finding checks ran and whether their produced total
  is exact; the duplicate `graph_available` and ambiguous validation
  `total_findings_complete` fields are removed. Evidence, context, validation,
  and deterministic-evaluation schemas advance together.
- Active documentation now describes the current artifact. Completed plans,
  refactor specifications, and stale handoffs are preserved and clearly
  labelled under `docs/history/`.
- The pre-publication working identity was renamed from Glossarize to
  Glossabet. Current package, command, artifact, cache, configuration, plugin,
  repository, and documentation surfaces use Glossabet; historical records
  may retain the former name.

### Security

- Repository code is treated as hostile static text and is never imported or
  executed. Production contains no network capability or shell invocation.
- Repository-controlled reads and writes are root-confined, bounded, and
  symlink-aware; direct control/artifact paths reject symlink components;
  writes use same-directory atomic replacement.
- Sensitive-path exclusions cover dotenv variants and common credential/key
  names without claiming content-level secret scanning.
- Corpus, vocabulary, matching, Graphify, finding, brief, and context limits
  expose coverage ledgers, reasons, and lower-bound semantics.
- Repository-controlled terminal text is escaped; glossary strings reject
  terminal controls, bidirectional formatting, invisible format characters,
  and lone surrogates.
- Git freshness disables repository hooks, monitors, and content filters,
  removes repository-selection environment overrides, disables prompts, and
  uses a timeout.
- Managed host files and installed skill/plugin files preserve differing or
  ambiguous state, detect ordinary concurrent changes where documented, and
  never follow an existing final-target symlink. An indeterminate exact-name
  lookup is uninspectable and authorizes no host-file write.
