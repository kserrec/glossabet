# Architecture

This document is for a developer taking ownership of Glossarize. It explains
what the pieces are, how they fit together, and the invariants that constrain
every change. For the product pitch and command list, see `README.md`; for the
roadmap and the binding principles behind design decisions, see `PLAN.md`; for
the threat model and security boundaries, see `SECURITY.md`.

## What Glossarize is, in one paragraph

Glossarize makes a codebase's vocabulary — the names for its subsystems,
entities, boundaries, and concepts — explicit and maintainable. It is a
deterministic command-line engine plus an agent skill (`skill/SKILL.md`). The
engine reads a repository and produces evidence: what files and modules exist,
what identifiers and documentation words appear and how often, which modules
import which, and (optionally) structural groups from a
[Graphify](https://github.com/Graphify-Labs/graphify) graph. The skill reads
that evidence, brainstorms names, and defers to the human, who alone decides
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
        │ brainstorms names from evidence             │ writes GLOSSARY.md +
  /glossarize skill (skill/SKILL.md)                  │ glossary.json when told
        ▲                                             ▼
        │ reads evidence.json (falls back to raw repo if absent/stale)
  ┌─────┴──────────────────────────────────────────────────────┐
  │ glossarize engine / CLI  (this Python package)              │
  │   install · scan · analyze · show · drift · validate        │
  └─────┬───────────────────────────────────────────────────────┘
        │ normalizes every source into one intermediate representation
   ┌────┴─────────┐
   ▼              ▼
 built-in       Graphify graph.json
 lexical        (optional, richer structure)
 scanner
```

The skill is a Markdown behavioral spec, not code in this package. This
document covers the engine; the skill's contract with the engine is that the
evidence fields it names (`repository.git.head`, `vocabulary.tokens`,
`monorepo.detected`, etc.) exist and mean what the skill says —
`tests/test_skill.py` pins exactly that, so schema drift can't silently break
the skill.

## Running it

Prerequisites: Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/). The only
runtime code is the Python standard library; `pytest` is the sole dev
dependency. Nothing is fetched at runtime.

Run the test suite:

```
uv run pytest
```

Install the CLI onto your PATH (`~/.local/bin/glossarize`):

```
uv tool install . --reinstall
```

Install the wheel-bundled canonical skill for Codex (or pass
`--agent claude` for Claude Code):

```
glossarize install
```

Scan this repository with the installed CLI:

```
glossarize analyze .
```

Or run the CLI without installing:

```
uv run glossarize analyze .
```

## The intermediate representation: RepositoryEvidence

Everything the engine produces flows through one dictionary, built by
`build_evidence()` in `glossarize/evidence.py` and written to
`<repo>/glossarize-out/evidence.json`. Both evidence sources (the lexical
scanner and the Graphify adapter) normalize into it, so every consumer above
that boundary — the terminology report, drift, reconciliation, and the skill —
is source-agnostic. Its top-level shape:

| Key | What it holds |
|-----|---------------|
| `schema_version`, `generator` | version stamps |
| `repository.git` | `{head, dirty}` — the filtered Git state the evidence was built from (staleness signal) |
| `configuration` | normalized `glossarize.json` state, or an explicit absent state |
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
  deterministically and the artifact records what was dropped, so a truncated
  output never reads as complete. Scanner work is additionally bounded per
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

## Module map

The package is `glossarize/`. Grouped by role:

**Entry point and shared plumbing**
- `cli.py` — argparse dispatcher. Owns the exit-status contract: `0` success,
  `1` user error (bad usage, missing input, malformed glossary), `2` internal
  defect. A custom parser remaps argparse's own exit-2-on-usage-error to `1`.
- `artifacts.py` — the reserved `glossarize-out/` plumbing shared by every command:
  `OUT_DIR`, `repo_root()` (the "is this a directory" check + resolve),
  `confined_artifact_path()` (direct artifacts may contain no symlink
  component), `write_artifact()` / `write_json_atomic()` (deterministic,
  same-directory atomic JSON replacement), and `oversized()` /
  `MAX_JSON_BYTES` (the size cap that bounds directly-read JSON so a hostile
  artifact cannot be loaded without limit).
- `config.py` — loads the optional root `glossarize.json` under a 1 MB cap and
  no-symlink rule. It validates literal repository-relative prefix rules,
  rejects unknown fields/roles and ambiguous equal-path roles, applies
  ignore-first/most-specific-role precedence, and owns the conservative
  built-in path classification.

**The lexical scanner (evidence source #1)**
- `scanner.py` — `walk_repository()` walks the tree and assigns every included
  code/doc path a `production`, `test`, or `fixture` role. This is where the
  load-bearing exclusions live: sensitive files and directories
  (`is_sensitive`, by pattern — `.env`, keys, anything named secret/credential)
  are never read; Glossarize's own outputs and `GLOSSARY.md` (at any depth) are
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
  and the shared Glossarize-output pathspec — see Security) and the
  `scan`/`analyze` command handlers.

**Analysis over the evidence**
- `imports.py` — best-effort, regex-level import extraction per language
  (`extract_imports`) and a `Resolver` that maps import strings to internal
  modules or external dependencies. Explicitly lossy and tagged `lossy: true`;
  it is never a real dependency graph. RepositoryEvidence imports are
  production-scoped by default.
- `importance.py` — `build_naming_candidates()` combines import fan-in/fan-out,
  file counts, and doc mentions into ranked "likely deserves a name"
  nominations, each carrying its reasons in plain numbers.
- `terminology.py` — `build_terminology()`: house-register statistics
  (naming-style and identifier-length distributions, common prefixes/suffixes),
  code-vs-doc vocabulary layers, and two nomination kinds — synonym candidates
  (parallel vocabulary like Job/Task/WorkItem, via inverse-frequency-weighted
  cosine similarity) and overloaded-term candidates (one term across disjoint
  contexts). Synonym nominations require low cross-term file overlap, at least
  two shared positional identifier patterns, and calibrated context similarity
  so sibling fields are not mistaken for replacements. All inputs are
  production-scoped and all pairwise work is capped to the top-N vocabulary.
- `matching.py` — the shared glossary-to-code occurrence rule. One-token terms
  use the token index; compound terms require an ordered contiguous sequence
  within one identifier. A capped identifier index can prove a hit but cannot
  prove absence, so absence/low-use findings are suppressed when completeness
  is unknown. Scope-aware token, identifier, and documentation occurrence
  helpers filter bounded location evidence by literal path prefix and retain
  explicit completeness metadata.

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
  cannot echo back as fake structural support. Graphify's artifacts are read,
  never written.

**Persistence and the health checks**
- `installer.py` — safe installation of the canonical agent skill. Hatch maps
  the repository source of truth, `skill/SKILL.md`, into the wheel at
  `glossarize/_skill/SKILL.md`; source runs fall back to the repository file.
  The command defaults to Codex's current `~/.agents/skills/glossarize`
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
- `glossary.py` — the persistent glossary (`glossarize-out/glossary.json`):
  schema validation (`validate_glossary`), load/save, the `show` command, and
  `require_glossary()` (the shared load-or-report-error helper). Bindings may
  only target stable identities (`symbol:` / `file:` / `module:`), never graph
  community or node ids, which are not stable across rebuilds. Optional
  `scope.path_prefixes` are literal repository-relative subsystem boundaries;
  aliases inherit the concept scope. NFKC-casefolded vocabulary has one owner
  within overlapping scopes, while disjoint scopes may deliberately reuse it.
- `drift.py` — `build_drift()` compares fresh evidence against the glossary:
  new terms paralleling canonical ones, discouraged/deprecated terms still in
  use, canonical terms fading from code, and canonical terms living in disjoint
  contexts. Rule-proven occurrences carry `certainty: observed`; heuristics
  carry `signal_strength`, never uncalibrated confidence. Section caps retain
  `dropped_items`, and `total_findings` includes displayed and dropped items.
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
  drift's signal/certainty and total-count contracts.

**Evaluation and calibration**
- `evaluation/corpus.json` — pinned source revisions, SPDX licenses,
  evaluation glossaries, hand-labelled terminology/drift expectations, and
  release thresholds. External source is referenced, not vendored.
- `evaluation/run.py` — developer-only, standard-library evaluation harness.
  It can fetch pinned checkouts into a temporary directory, performs cold and
  warm scans without importing or executing target code, scores findings,
  records truncation/runtime/cache behavior, and checks release thresholds.
- `evaluation/results.json` — the raw five-run Phase 15 result, including every
  actual/expected finding key and per-case timing sample, extended in Phase 16
  with 15 exact lexical-contract checks. `EVALUATION.md` documents methodology,
  calibration history, dependency decisions, limitations, and reproduction.

**Distribution and first use**
- `examples/payment-service/` and `scripts/run_walkthrough.py` — an original,
  already-settled sample copied into temporary storage and exercised through
  analyze/show/drift/validate. It proves the machine lifecycle without
  pretending software made the vocabulary decisions.
- `scripts/check_distribution.py` — standard-library checks for archive path
  safety, required source/wheel contents, canonical-skill byte identity,
  metadata, console entry point, license, and the absence of runtime
  dependencies.
- `scripts/wheel_smoke.py` — creates a fresh virtual environment, installs only
  the built wheel, installs its skill into a temporary target, runs the
  walkthrough, uninstalls the package, and proves the import and CLI entry
  point are gone.
- `.github/workflows/ci.yml` — the full CPython 3.10–3.14 × Linux/macOS/Windows
  matrix plus a packaging job. `release.yml` is a separate manual-only,
  tag-and-confirmation-gated PyPI workflow; `RELEASING.md` records the external
  account state that must exist before it can succeed.

## Key flows

**`install`** (`cli.py` → `installer.install_command`). Reads the canonical
skill from package data (or the source-tree fallback), selects the documented
personal directory for Codex or Claude Code unless an explicit destination is
given, preserves different existing content unless `--force` is present, and
atomically writes only `SKILL.md`. It does not inspect a repository or contact
an agent host.

**`scan` / `analyze`** (`cli.py` → `evidence._scan` → `build_evidence`).
`build_evidence` loads `glossarize.json`, walks and role-classifies the repo
(`scanner.walk_repository`), reads each included code/doc file and hashes its
bytes, reuses cached extraction only when that digest matches, folds production
identifiers into `_Vocabulary`, extracts production imports, optionally builds
structural groups from Graphify, computes naming candidates and terminology,
and returns the evidence dict, which is atomically written to
`glossarize-out/evidence.json`. `analyze` additionally prints a human-readable
terminology report (`_print_terminology_report`). Test and fixture paths stay in
the inventory/cache but outside vocabulary signals; generated and vendored
paths are not read. A warm scan still reads every included file to establish
its digest, but avoids tokenization and import/doc extraction for unchanged
content while remaining byte-identical to a cold scan. Any scanner-budget stop
is visible in `skipped.corpus_budget` and on stderr; downstream users must treat
that evidence as partial.

**`drift`** (`cli.py` → `drift.drift_command` → `build_drift`). Requires a
glossary (`require_glossary`, exits `1` if absent). Builds fresh evidence,
indexes the glossary's canonical/watched tokens and ownership scopes, runs the
four checks within those path regions, writes `glossarize-out/drift.json`, and
prints the report.

**`validate`** (`cli.py` → `reconcile.validate_command` → `build_validation`).
Requires a glossary. Builds fresh evidence (with the Graphify graph if present),
matches canonical concepts against structural groups in both directions,
delegates vocabulary-drift and concept-collision detection to `drift.py`, writes
`glossarize-out/validation.json`, and prints the report. Validation embeds the
adapter's presence/usability/freshness/warning state; all structural sections
carry `skipped: true` plus a reason when usable groups were not loaded.
Scoped lexical checks still run, while structural sections disclose partial or
skipped scope coverage because normalized Graphify groups have no path map.

## Git freshness and artifact lifecycle

`_git_stamp()` and the skill use the same live-state definition. They read
`HEAD`, then run porcelain-v1 status with all untracked files, rename detection
disabled, and these scanned-root-relative pathspecs:

```
.
:(exclude)glossarize-out
:(exclude)glossarize-out/**
```

The engine runs Git from the directory being scanned, and the skill runs the
same check from that directory. The exclusions deliberately omit Git's `top`
modifier so a subproject scan inside a larger worktree excludes the
subproject's output rather than an unrelated checkout-root path. They apply
whether output is tracked or untracked. Disabling rename detection ensures a
move across the ownership boundary still reports the changed non-output path.
No other path inside the scanned root is filtered: source, `GLOSSARY.md`,
Graphify output, and the legacy repository-local cache path all retain normal
Git status behavior. Git-ignored files remain invisible under Git's own rules,
and a missing/unreadable `HEAD` or failed status check yields `null` rather than
a false clean claim. The skill calls evidence fresh only when the recorded and
live commits match and both dirty states are explicitly false.

This filtered comparison is not an ignore-file mutation. Glossarize never
creates or edits a target `.gitignore`; it merely reserves the top-level
`glossarize-out/` namespace for its own artifacts. Within it,
`evidence.json`, `drift.json`, and `validation.json` are regenerable reports.
`glossary.json` is different: it persists human-governed vocabulary state and
must be retained unless that state is intentionally discarded or recoverable.
The human-readable `GLOSSARY.md` remains repository-owned state outside the
reserved directory and is never excluded from freshness.

## Security and trust boundaries

Glossarize is pointed at repositories that may be untrusted, so the scanned
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

`PLAN.md` is the authoritative roadmap. Phases 0–17 are complete; public PyPI
publication and enabling GitHub private vulnerability reporting remain
external, explicitly authorized actions rather than an implementation phase.
