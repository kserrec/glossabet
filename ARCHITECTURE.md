# Architecture

This document is for a developer taking ownership of Glossabet. It explains
what the pieces are, how they fit together, and the invariants that constrain
every change. For the product pitch and command list, see `README.md`; for the
roadmap and the binding principles behind design decisions, see `PLAN.md`; for
the threat model and security boundaries, see `SECURITY.md`.

## What Glossabet is, in one paragraph

Glossabet makes a codebase's vocabulary — the names for its subsystems,
entities, boundaries, and concepts — explicit and maintainable. It is a
deterministic command-line engine plus an agent skill (`skill/SKILL.md`). The
engine reads a repository and produces evidence: what files and modules exist,
what identifiers and documentation words appear and how often, which modules
import which, and (optionally) structural groups from a
[Graphify](https://github.com/Graphify-Labs/graphify) graph. The skill requests
a fresh, bounded context through the CLI, reads the production files named by
that context, brainstorms names, and defers to the human, who alone decides
what becomes canonical. Once a glossary exists, the engine can detect **drift**
(the code's live vocabulary diverging from the settled glossary) and
**reconcile** the glossary against the evidence and graph.

The central rule, repeated everywhere in the code and the plan: **the machinery
gathers and grounds, the LLM proposes, the human decides.** The engine never
finalizes vocabulary and never renames code.

## The division of labor

```
  human decides ────────────────────────────────────┐
        ▲                                             │
        │ brainstorms names from evidence             │ approves vocabulary;
  /glossabet skill (skill/SKILL.md)                  │ skill writes GLOSSARY.md,
        │                                             │ CLI saves glossary.json
        ▲                                             ▼
        │ runs `glossabet inspect .`; parses bounded JSON stdout
  ┌─────┴──────────────────────────────────────────────────────┐
  │ glossabet engine / CLI  (this Python package)              │
  │ install · inspect · save · scan · analyze · show · drift · validate│
  └─────┬───────────────────────────────────────────────────────┘
        │ normalizes every source into one intermediate representation
   ┌────┴─────────┐
   ▼              ▼
 built-in       Graphify graph.json
 lexical        (optional, richer structure)
 scanner
```

The skill is a Markdown behavioral spec, not code in this package. This
document covers the engine; the skill's contract with it is the
`AgentContext` emitted by `glossabet inspect .`. The skill never opens
repository JSON artifacts itself and has no raw-repository fallback when the
CLI boundary fails. `tests/test_skill.py` and `tests/test_agent_context.py` pin
the versioned fields and failure behavior so schema drift cannot silently
break grounding.

## Running it

Prerequisites: Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/). The only
runtime code is the Python standard library; `pytest` is the sole development
dependency. Hatchling `>=1.32,<1.33` is used only in an isolated build
environment. Nothing is fetched at application runtime.

Run the test suite:

```
uv run pytest
```

The preferred Codex distribution is the version-coupled plugin described in
`DISTRIBUTION.md`; its local source is `plugins/glossabet/` and it is not yet
published in a marketplace. Install the standalone fallback CLI onto your
PATH (`~/.local/bin/glossabet`):

```
uv tool install . --reinstall
```

Install the wheel-bundled canonical skill for Codex (or pass
`--agent claude` for Claude Code):

```
glossabet install
```

Scan this repository with the installed CLI:

```
glossabet analyze .
```

Emit the bounded context consumed by the installed skill:

```
glossabet inspect .
```

Persist a validated glossary JSON document supplied on standard input:

```
glossabet save .
```

Or run the CLI without installing:

```
uv run glossabet analyze .
```

## The intermediate representation: RepositoryEvidence

Deterministic engine analysis flows through one dictionary, built by
`build_evidence()` in `glossabet/evidence.py` and written to
`<repo>/glossabet-out/evidence.json`. Both evidence sources (the lexical
scanner and the Graphify adapter) normalize into it, so the terminology report,
drift, reconciliation, and the agent-context projector are source-agnostic.
The skill does not read this artifact directly. Its top-level shape:

| Key | What it holds |
|-----|---------------|
| `schema_version`, `generator` | version stamps |
| `repository.git` | `{head, dirty}` — the filtered Git state the evidence was built from (staleness signal) |
| `configuration` | normalized `glossabet.json` state, or an explicit absent state |
| `totals` | source/code/doc file, byte, and word counts, including per-role totals |
| `languages`, `modules` | language tally; per-directory module and role inventory |
| `imports` | best-effort internal edges + external dependency tally (lossy, tagged so) |
| `naming_candidates` | ranked "likely deserves a name" nominations (modules, terms, structures) |
| `structural_groups` | Graphify presence, usability, warnings, commit freshness, and normalized groups |
| `files` | code/doc files with their production/test/fixture role |
| `vocabulary` | normalization contract plus production-scoped, capped `tokens`, enriched `identifiers`, and `doc_terms` tables |
| `terminology` | production scope, register stats, code-vs-doc layers, synonym and overload nominations |
| `monorepo` | `{detected, reasons, sub_roots}` |
| `skipped` | sensitive, oversized, escaping-symlink, configured, generated, vendored, and corpus-budget exclusions |

Two invariants govern this structure and are the reason it can be trusted:

- **Determinism.** The same repository state produces byte-identical evidence.
  Achieved by sorting every collection, using stable tie-breaks
  (`(-count, key)` throughout), and recording no timestamps. A warm (cached)
  scan is byte-identical to a cold one by construction, because both go through
  the same aggregation path. `tests/test_cache.py` and the determinism test in
  `tests/test_evidence.py` pin this.
- **Bounded work with logged truncation.** Nothing is unbounded. Every cap
  (top-N tokens, locations per term, candidate pairs, edge counts) is applied
  deterministically. Bounded collections share the `coverage.py` ledger, which
  separates a known evaluated total from whether that total is exhaustive and
  records every known drop and reason, so a truncated output never reads as
  complete. Scanner work is additionally bounded per
  repository at 10,000 included source files, 32 MB of included source, 100,000
  walked entries, and 10,000 entries in one directory. Exceeding any scanner
  ceiling sets `skipped.corpus_budget.complete` false and records exact source
  skips or an explicitly inexact walk remainder. See `PLAN.md` principle 12.
- **Explicit production scope.** Files are classified before extraction.
  Production content drives vocabulary and heuristic analysis; tests and
  fixtures remain inventoried but do not steer those signals; generated and
  vendored content is not read. `configuration`, `files[*].role`, per-role
  totals, `terminology.scope`, and `skipped` make that boundary inspectable.
- **Explicit concept scope.** A glossary concept may optionally own one or
  more literal repository-relative path prefixes. Omission means the original
  repository-wide behavior. Terms and aliases must have one owner wherever
  scopes overlap; reuse is valid only between disjoint scopes. Drift and
  lexical validation filter occurrences and stable bindings by that boundary.

## The agent-facing representation: AgentContext

`glossabet/agent_context.py` projects current `RepositoryEvidence` plus the
strictly validated optional glossary into the JSON printed by
`glossabet inspect .`. The command loads the glossary through
`confined_artifact_path()`, performs a fresh scan, atomically refreshes the
ordinary evidence artifact, and emits no progress text on standard output.

The context has its own `context_schema_version`. Agent-facing collections are
sampled at documented per-field limits, arbitrary nested lists have a smaller
default limit, strings have a character ceiling, omission records are bounded,
and the final UTF-8 JSON is capped at 1 MB. A projection needing more than 100
distinct omission records fails rather than hiding which collection was cut.
`coverage.corpus` preserves scanner
coverage; `coverage.context` separately identifies every agent-projection
omission and whether that projection is complete. If the final object still
cannot fit, the command exits as a user error instead of emitting partial JSON.
This is a model-context boundary, not a replacement for the full deterministic
artifact used by other engine commands.

## Module map

The package is `glossabet/`. Grouped by role:

**Entry point and shared plumbing**
- `cli.py` — argparse dispatcher. Owns the exit-status contract: `0` success,
  `1` user error (bad usage, missing input, malformed glossary), `2` internal
  defect. A custom parser remaps argparse's own exit-2-on-usage-error to `1`.
  Both terminal streams are protected for the entire invocation.
- `display.py` — centralized terminal rendering. C0/C1 controls, DEL, line
  separators, and bidirectional-format characters from repository/user data
  are rendered as visible escape spellings rather than emitted as terminal
  instructions. Glossary identity fields reject them during validation.
- `artifacts.py` — the reserved `glossabet-out/` plumbing shared by every command:
  `OUT_DIR`, `repo_root()` (the "is this a directory" check + resolve),
  `confined_artifact_path()` (direct artifacts may contain no symlink
  component), `write_artifact()` / `write_json_atomic()` (deterministic,
  same-directory atomic JSON replacement), and `oversized()` /
  `MAX_JSON_BYTES` (the size cap that bounds directly-read JSON so a hostile
  artifact cannot be loaded without limit).
- `config.py` — loads the optional root `glossabet.json` under a 1 MB cap and
  no-symlink rule. It validates literal repository-relative prefix rules,
  rejects unknown fields/roles and ambiguous equal-path roles, applies
  ignore-first/most-specific-role precedence, and owns the conservative
  built-in path classification.

**The lexical scanner (evidence source #1)**
- `scanner.py` — `walk_repository()` walks the tree and assigns every included
  code/doc path a `production`, `test`, or `fixture` role. This is where the
  load-bearing exclusions live: sensitive files and directories
  (`is_sensitive`, by pattern — `.env`, keys, anything named secret/credential)
  are never read; Glossabet's own outputs and `GLOSSARY.md` (at any depth) are
  excluded so the glossary can't echo back into evidence (contamination);
  symlinks whose real target escapes the repo root (`_escapes`) are skipped so a
  hostile repo can't read outside files. Root `Cargo.toml` and `package.json`
  workspace probes use that same symlink boundary and 2 MB limit. Configured
  ignores and generated/vendored paths are pruned and reported. Explicit
  production rules can override a default role, including inside a normally
  excluded subtree. The walk is a bounded, deterministic depth-first traversal;
  a directory that exceeds its own entry ceiling is omitted as a whole rather
  than selecting a filesystem-order-dependent subset. Also
  `detect_monorepo()`.
- `tokenize.py` — the Unicode-aware lexical normalizer. It NFKC-normalizes and
  case-folds identifiers, splits camel/Pascal/snake and Clojure kebab forms,
  preserves acronym runs, attaches digit runs to their preceding word, and
  drops standalone numeric hunks. `tokenize_term()` applies the same contract
  to glossary terms; `doc_words()` extracts Unicode prose vocabulary.
  Cross-language keywords and prose stopwords are filtered as deliberate,
  documented noise reduction. The source matcher is still lexical and sees
  identifier-like text in comments/strings; it does not claim parser syntax.

**The aggregation hub**
- `evidence.py` — `build_evidence()` orchestrates everything: walk the repo,
  read each included production/test/fixture file (via the cache when valid),
  fold only production identifiers into the `_Vocabulary` aggregate (token,
  identifier-unit, per-file/per-module, and neighbor views), read production
  docs into the terminology layer, then assemble the evidence dict. Identifier
  entries retain normalized tokens and bounded locations so compound matching
  can prove one lexical unit rather than infer from aggregate words. Also holds
  `_git_stamp()` (runs `git` with the repo's dangerous config keys neutralized
  and the shared Glossabet-output pathspec — see Security) and the
  `scan`/`analyze` command handlers.
- `agent_context.py` — the `inspect` command and versioned skill boundary.
  It loads the optional glossary through the confined validator, builds fresh
  evidence, applies deterministic list/string/output limits, records all
  projection omissions, and prints JSON only.

**Analysis over the evidence**
- `imports.py` — best-effort, regex-level import extraction per language
  (`extract_imports`) and a `Resolver` that maps import strings to internal
  modules or external dependencies. Explicitly lossy and tagged `lossy: true`;
  it is never a real dependency graph. RepositoryEvidence imports are
  production-scoped by default.
- `importance.py` — `build_naming_candidates()` combines import fan-in/fan-out,
  file counts, and doc mentions into ranked "likely deserves a name"
  nominations, each carrying its reasons in plain numbers. It screens the
  complete bounded vocabulary in a streaming top-k pass, so candidates below
  the old frequency pool still enter exact totals without an unbounded list.
- `terminology.py` — `build_terminology()`: house-register statistics
  (naming-style and identifier-length distributions, common prefixes/suffixes),
  code-vs-doc vocabulary layers, and two nomination kinds — synonym candidates
  (parallel vocabulary like Job/Task/WorkItem, via inverse-frequency-weighted
  cosine similarity) and overloaded-term candidates (one term across disjoint
  contexts). Synonym nominations require low cross-term file overlap, at least
  two shared positional identifier patterns, and calibrated context similarity
  so sibling fields are not mistaken for replacements. All inputs are
  production-scoped and all pairwise work is capped to the top-N vocabulary;
  overload dispersion also has an explicit per-term module ceiling. The full
  eligible-token total and every detail/sample/work omission use the shared
  coverage ledger rather than turning a bounded sample into an exhaustive
  claim.
- `coverage.py` — the common bounded-collection ledger. Known totals, retained
  details, known drops, total exactness, completeness, and reasons have one
  shape across evidence, candidates, terminology, Graphify, drift, and
  validation.
- `matching.py` — the shared glossary-to-code occurrence rule and downstream
  `EvidenceIndex`. One-token, symbol, file, module, and doc lookups are indexed;
  all requested compound terms share one bounded trie pass over identifier
  positions. A capped identifier index or exhausted work budget can prove a
  hit but cannot prove absence, so absence/low-use findings are suppressed.
  Scope-aware occurrence helpers retain explicit completeness metadata.

**The optional structural source (evidence source #2)**
- `graphify.py` — `build_structural_groups()` reads `graphify-out/graph.json`
  if present and turns nodes/links/communities into structural groups plus
  importance signals. The primary contract is Graphify 0.9.42's NetworkX
  node-link export (`links`, `source_file`, `file_type`, per-node
  `community_name`, and `built_at_commit`); older `edges`/`source` shapes stay
  explicitly tested. `present` means a graph path was found, while `available`
  means at least one usable community group was normalized. Commit freshness
  is `current`, `stale`, or `unverified` against the evidence Git stamp. This
  compares repository-controlled metadata; it detects ordinary staleness but
  does not authenticate graph content.
  Unrecognized or group-less data degrades to lexical-only with a warning,
  never an error. Glossary-provenance nodes are discounted so vocabulary
  cannot echo back as fake structural support; provenance uses exact normalized
  path components, basenames, and type values. Each group retains a six-label
  display sample plus the complete token set of every accepted member for
  matching. Graphify's artifacts are read, never written.

**Persistence and the health checks**
- `installer.py` — safe installation of the canonical agent skill. Hatch maps
  the repository source of truth, `skill/SKILL.md`, into the wheel at
  `glossabet/_skill/SKILL.md`; source runs fall back to the repository file.
  The command defaults to Codex's current `~/.agents/skills/glossabet`
  directory, supports Claude Code and an explicit destination, writes
  atomically, is idempotent, refuses symlink components, and requires
  `--force` before replacing different content.
- `cache.py` — the user-owned per-file extraction cache. It lives under the
  platform cache directory, outside the scanned repository, in a directory
  keyed by the repository's resolved path. Reuse requires the current file's
  SHA-256 digest plus a valid entry shape; the whole cache invalidates on a
  cache-schema or generator-version change. Cache schema 3 specifically
  invalidates pre-Unicode extraction entries. Any doubt reads as a miss. An
  override that resolves inside the target repository disables caching.
- `glossary.py` — the persistent glossary (`glossabet-out/glossary.json`):
  schema validation (`validate_glossary`), load/save, the `show` command, and
  `require_glossary()` (the shared load-or-report-error helper). Bindings may
  only target stable identities (`symbol:` / `file:` / `module:`), never graph
  community or node ids, which are not stable across rebuilds. Optional
  `scope.path_prefixes` are literal repository-relative subsystem boundaries;
  aliases inherit the concept scope. NFKC-casefolded vocabulary has one owner
  within overlapping scopes, while disjoint scopes may deliberately reuse it.
  Every object rejects unknown fields; accepted concepts, aliases, bindings,
  scope paths, strings, and diagnostics have semantic ceilings. Vocabulary
  ownership uses a per-term path-prefix trie rather than pairwise owner scans.
- `drift.py` — `build_drift()` compares fresh evidence against the glossary:
  new terms paralleling canonical ones, discouraged/deprecated terms still in
  use, canonical terms fading from code, and canonical terms living in disjoint
  contexts. Rule-proven occurrences carry `certainty: observed`; heuristics
  carry `signal_strength`, never uncalibrated confidence. Section caps retain
  legacy `dropped_items` plus the shared coverage ledger, and
  `total_findings` includes displayed and dropped items.
  Every term occurrence, parallel-vocabulary association, fading check, and
  overload check is restricted to its concept's scope and reports that scope.
- `reconcile.py` — `build_validation()`: two-directional coverage plus the
  mismatch taxonomy (unnamed structure, orphaned concept, unresolved binding,
  boundary mismatch, fragmentation, overloaded region) — exact compound
  occurrence checks for lexical evidence, full-term matching inside a
  structural group as its defined local context, and no one-to-one
  community=concept assumption anywhere. Stable bindings, orphan checks, and
  fragmentation are scope-aware. Normalized Graphify groups currently lack
  repository paths, so scoped structural coverage is marked partial and
  potentially false unnamed-structure conclusions are skipped. It shares
  drift's signal/certainty and total-count contracts. Structural matching
  reaches concepts through an inverted token index under an explicit work
  budget; boundary pairs are counted without materializing the full pair set.

**Evaluation and calibration**
- `evaluation/corpus.json` — pinned source revisions, SPDX licenses,
  evaluation glossaries, hand-labelled terminology/drift/structural
  expectations, exact Graphify contracts, and release thresholds. External
  source is referenced, not vendored.
- `evaluation/run.py` — developer-only, standard-library evaluation harness.
  It can fetch pinned checkouts into a temporary directory, performs cold and
  warm scans without importing or executing target code, scores lexical,
  terminology, drift, and structural findings, records
  truncation/runtime/cache behavior, and checks release thresholds. Its
  verification mode recomputes local structural results, aggregates, and
  thresholds and rejects stale engine source, schemas, manifest, corpora,
  source metadata, run count, or Graphify case coverage.
- `evaluation/results.json` — the current seven-case, five-run Phase 22 replay,
  including every actual/expected finding key, per-case timing, structured
  engine/version metadata, and digests for the engine, manifest, and each
  accepted corpus.
- `evaluation/review.py`, `reviewer-packet.json`, and `reviewer-results.json` —
  build a label-blinded packet, run one separate Codex reviewer in an isolated
  read-only temporary directory, retain bounded packet-only trace evidence,
  and record disagreements separately from deterministic correctness.
- `scripts/agent_eval.py` and `evaluation/agent-results.json` — temporarily
  install the actual plugin, run 10 plugin scenarios plus one standalone
  missing-CLI scenario through ephemeral Codex sessions, independently check
  contexts/writes/sensitive canaries, and prove exact plugin cleanup. The
  recorded host is Codex CLI 0.147.0 on Linux.
  `EVALUATION.md` documents methodology, calibration history, dependency
  decisions, limitations, and reproduction.

**Distribution and first use**
- `plugins/glossabet/` — the local Codex plugin prototype. Its manifest,
  canonical skill copy, skill-local runner, and nested pure-Python wheel all
  carry version 0.1.0. The runner imports that exact wheel from the plugin
  cache and never installs a second command or environment.
- `scripts/build_plugin.py` — assembles the plugin from one already-built
  wheel and fails if source, manifest, runner, skill, wheel metadata, or
  embedded skill versions differ.
- `scripts/plugin_smoke.py` — uses an actual local Codex marketplace to
  install the current bundle, run its CLI boundary, update to a synthetic next
  patch, and remove every test-owned plugin/configuration/cache entry. The
  direct Phase 21 probe covers Codex CLI 0.147.0 on Linux only.
- `examples/payment-service/` and `scripts/run_walkthrough.py` — an original,
  already-settled sample copied into temporary storage and exercised through
  analyze/show/drift/validate. It proves the machine lifecycle without
  pretending software made the vocabulary decisions.
- `scripts/check_distribution.py` — standard-library checks for archive path
  safety, required source/wheel/plugin contents, canonical-skill byte identity,
  plugin version coupling, metadata, console entry point, license, and the
  absence of runtime dependencies.
- `scripts/wheel_smoke.py` — creates a fresh virtual environment, installs only
  the built wheel, installs its skill into a temporary target, runs the
  walkthrough, uninstalls the package, and proves the import and CLI entry
  point are gone.
- `scripts/check_workflows.py` — fail-closed, standard-library policy checks
  for the supported matrix and the CI → quality → package / release → quality
  → publish dependency chains. Mutation tests prove the important weakenings
  are rejected without adding a YAML dependency.
- `.github/workflows/quality.yml` — the reusable CPython 3.10–3.14 ×
  Linux/macOS/Windows matrix followed by evidence, build, distribution, and
  wheel checks. Both `ci.yml` and the manual-only, tag-and-confirmation-gated
  `release.yml` call it; publication additionally needs its successful result.
  `RELEASING.md` records the external account state required for publication.

## Key flows

**`install`** (`cli.py` → `installer.install_command`). Reads the canonical
skill from package data (or the source-tree fallback), selects the documented
personal directory for Codex or Claude Code unless an explicit destination is
given, preserves different existing content unless `--force` is present, and
atomically writes only `SKILL.md`. It does not inspect a repository or contact
an agent host.

**`scan` / `analyze`** (`cli.py` → `evidence._scan` → `build_evidence`).
`build_evidence` loads `glossabet.json`, walks and role-classifies the repo
(`scanner.walk_repository`), reads each included code/doc file and hashes its
bytes, reuses cached extraction only when that digest matches, folds production
identifiers into `_Vocabulary`, extracts production imports, optionally builds
structural groups from Graphify, computes naming candidates and terminology,
and returns the evidence dict, which is atomically written to
`glossabet-out/evidence.json`. `analyze` additionally prints a human-readable
terminology report (`_print_terminology_report`). Test and fixture paths stay in
the inventory/cache but outside vocabulary signals; generated and vendored
paths are not read. A warm scan still reads every included file to establish
its digest, but avoids tokenization and import/doc extraction for unchanged
content while remaining byte-identical to a cold scan. Any scanner-budget stop
is visible in `skipped.corpus_budget` and on stderr; downstream users must treat
that evidence as partial.

**`inspect`** (`cli.py` → `agent_context.inspect_command`). Loads and validates
the optional glossary first, builds fresh evidence through the same scanner as
`scan`, refreshes `glossabet-out/evidence.json`, projects the result through
the independent `AgentContext` limits, and emits one JSON document on stdout.
Malformed, oversized, or symlinked glossaries and a context that exceeds its
hard byte ceiling exit `1` without a lower-trust fallback. The installed skill
parses this output and reads only production paths it names.

**`save`** (`cli.py` → `glossary.save_command`). Accepts at most 64 MB from
standard input (reading one additional byte only to detect overflow), parses
exactly one JSON document, applies the strict glossary schema and semantic
budgets, then calls `save_glossary()` for a confined, atomic replacement. The
skill uses this flow after human approval and never writes the machine artifact
directly.

**`drift`** (`cli.py` → `drift.drift_command` → `build_drift`). Requires a
glossary (`require_glossary`, exits `1` if absent). Builds fresh evidence,
indexes the glossary's canonical/watched tokens and ownership scopes, runs the
four checks within those path regions, writes `glossabet-out/drift.json`, and
prints the report.

**`validate`** (`cli.py` → `reconcile.validate_command` → `build_validation`).
Requires a glossary. Builds fresh evidence (with the Graphify graph if present),
matches canonical concepts against structural groups in both directions,
delegates vocabulary-drift and concept-collision detection to `drift.py`, writes
`glossabet-out/validation.json`, and prints the report. Validation embeds the
adapter's presence/usability/freshness/warning state; all structural sections
carry `skipped: true` plus a reason when usable groups were not loaded.
Scoped lexical checks still run, while structural sections disclose partial or
skipped scope coverage because normalized Graphify groups have no path map.

## Git freshness and artifact lifecycle

`_git_stamp()` records the live-state definition used in evidence. It reads
`HEAD`, then run porcelain-v1 status with all untracked files, rename detection
disabled, and these scanned-root-relative pathspecs:

```
.
:(exclude)glossabet-out
:(exclude)glossabet-out/**
```

The engine runs Git from the directory being scanned. The skill no longer runs
Git itself: `inspect` creates its context from the live scan in the same
invocation. The exclusions deliberately omit Git's `top`
modifier so a subproject scan inside a larger worktree excludes the
subproject's output rather than an unrelated checkout-root path. They apply
whether output is tracked or untracked. Disabling rename detection ensures a
move across the ownership boundary still reports the changed non-output path.
No other path inside the scanned root is filtered: source, `GLOSSARY.md`,
Graphify output, and the legacy repository-local cache path all retain normal
Git status behavior. Git-ignored files remain invisible under Git's own rules,
and a missing/unreadable `HEAD` or failed status check yields `null` rather than
a false clean claim. `freshness.status: current` in `AgentContext` means
generated in the current invocation; it is not an atomic-snapshot or
authenticated-content claim.

This filtered comparison is not an ignore-file mutation. Glossabet never
creates or edits a target `.gitignore`; it merely reserves the top-level
`glossabet-out/` namespace for its own artifacts. Within it,
`evidence.json`, `drift.json`, and `validation.json` are regenerable reports.
`glossary.json` is different: it persists human-governed vocabulary state and
must be retained unless that state is intentionally discarded or recoverable.
The human-readable `GLOSSARY.md` remains repository-owned state outside the
reserved directory and is never excluded from freshness.

## Security and trust boundaries

Glossabet is pointed at repositories that may be untrusted, so the scanned
repo's contents are treated as attacker-controllable input. The enforced
boundaries — sensitive-file/directory exclusion, symlink-escape prevention, no
contamination, per-input size caps, neutralizing the scanned repo's git
config so it can't execute code, and catching malformed input cleanly rather
than crashing as a "defect" — are documented with their regression tests in
`SECURITY.md`. Read that file before touching `scanner.py`, `evidence._git_stamp`,
or any of the JSON readers.

## Decisions and constraints

These are settled in `PLAN.md`; the load-bearing ones for a new owner:

- **The lexical scanner stays lexical.** It provides files, modules, identifier
  vocabulary, and cheap regex-level import edges — never full parsing or a
  static analyzer. Rich structure comes from adapters (Graphify today; LSP or
  others later), never from growing the scanner. This is the single most
  important boundary to respect.
- **Stdlib-only runtime.** No runtime dependencies; `pytest` is the only
  dev dependency. A new dependency needs a real use site and a one-line
  cost/reason (`PLAN.md` principle 9). Phase 16 measured the current lexical
  labels at 15/15 and rejected a Tree-sitter adapter because it offered no
  remaining labelled accuracy gain while adding native binaries, runtime
  grammar downloads/cache state, and parser maintenance.
- **Graphify is an adapter, never a dependency.** Detected if present, ignored
  if absent; its artifacts are never mutated.
- **Tests protect concrete threats, not coverage.** Wrong or nondeterministic
  evidence, ingested secrets, contamination, stale artifacts, schema drift,
  broken tokenization — every test names a real failure. Do not add coverage
  filler.

Known limitations, honestly: imports are regex-level and incomplete by design;
legacy Graphify graphs without `built_at_commit` and graphs over dirty
worktrees remain freshness-unverified; and the engine deliberately does
nothing autonomous with vocabulary — it nominates and grounds, and stops.
Identifier extraction remains lexical rather than syntax-aware, and scoped
structural validation is partial until an adapter supplies trustworthy paths.

## Where things stand

`PLAN.md` is the authoritative roadmap. Phases 0–22 are complete. The
trusted-alpha evidence gate, Phase 23, and explicit external authorization
remain before public package or plugin publication.
