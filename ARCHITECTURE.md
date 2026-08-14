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
  │   scan · analyze · show · drift · validate                  │
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
| `repository.git` | `{head, dirty}` — the git state the evidence was built from (staleness signal) |
| `totals` | file/byte/word counts |
| `languages`, `modules` | language tally; per-directory module inventory |
| `imports` | best-effort internal edges + external dependency tally (lossy, tagged so) |
| `naming_candidates` | ranked "likely deserves a name" nominations (modules, terms, structures) |
| `structural_groups` | Graphify presence, usability, warnings, commit freshness, and normalized groups |
| `files` | code files (path + language) and doc files |
| `vocabulary` | capped `tokens`, `identifiers`, `doc_terms` frequency tables |
| `terminology` | register stats, code-vs-doc layers, synonym and overload nominations |
| `monorepo` | `{detected, reasons, sub_roots}` |
| `skipped` | `sensitive`, `oversized`, `symlinks_escaping_repo` — never silently dropped |

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
  output never reads as complete. See `PLAN.md` principle 12.

## Module map

The package is `glossarize/`. Grouped by role:

**Entry point and shared plumbing**
- `cli.py` — argparse dispatcher. Owns the exit-status contract: `0` success,
  `1` user error (bad usage, missing input, malformed glossary), `2` internal
  defect. A custom parser remaps argparse's own exit-2-on-usage-error to `1`.
- `artifacts.py` — the `glossarize-out/` plumbing shared by every command:
  `OUT_DIR`, `repo_root()` (the "is this a directory" check + resolve),
  `confined_artifact_path()` (direct artifacts may contain no symlink
  component), `write_artifact()` / `write_json_atomic()` (deterministic,
  same-directory atomic JSON replacement), and `oversized()` /
  `MAX_JSON_BYTES` (the size cap that bounds directly-read JSON so a hostile
  artifact cannot be loaded without limit).

**The lexical scanner (evidence source #1)**
- `scanner.py` — `walk_repository()` walks the tree and classifies files. This
  is where three load-bearing exclusions live: sensitive files and directories
  (`is_sensitive`, by pattern — `.env`, keys, anything named secret/credential)
  are never read; Glossarize's own outputs and `GLOSSARY.md` (at any depth) are
  excluded so the glossary can't echo back into evidence (contamination);
  symlinks whose real target escapes the repo root (`_escapes`) are skipped so a
  hostile repo can't read outside files. Root `Cargo.toml` and `package.json`
  workspace probes use that same symlink boundary and 2 MB limit. Also
  `detect_monorepo()`.
- `tokenize.py` — the normalizer. `tokenize_identifier()` splits
  `PaymentService` / `payment_service` / `paymentService` into shared lowercase
  tokens `["payment", "service"]`; `tokenize_term()` does the same for
  human-written glossary terms; `doc_words()` extracts prose vocabulary.
  Cross-language keywords and prose stopwords are filtered as deliberate,
  documented noise reduction.

**The aggregation hub**
- `evidence.py` — `build_evidence()` orchestrates everything: walk the repo,
  read each file (via the cache when valid), fold identifiers into the
  `_Vocabulary` aggregate (token counts plus per-file / per-module / neighbor
  views), read docs, then call the analysis modules and assemble the evidence
  dict. Also holds `_git_stamp()` (runs `git` with the repo's dangerous config
  keys neutralized — see Security) and the `scan`/`analyze` command handlers.

**Analysis over the evidence**
- `imports.py` — best-effort, regex-level import extraction per language
  (`extract_imports`) and a `Resolver` that maps import strings to internal
  modules or external dependencies. Explicitly lossy and tagged `lossy: true`;
  it is never a real dependency graph.
- `importance.py` — `build_naming_candidates()` combines import fan-in/fan-out,
  file counts, and doc mentions into ranked "likely deserves a name"
  nominations, each carrying its reasons in plain numbers.
- `terminology.py` — `build_terminology()`: house-register statistics
  (naming-style and identifier-length distributions, common prefixes/suffixes),
  code-vs-doc vocabulary layers, and two nomination kinds — synonym candidates
  (parallel vocabulary like Job/Task/WorkItem, via inverse-frequency-weighted
  cosine similarity) and overloaded-term candidates (one term across disjoint
  contexts). All pairwise work is capped to the top-N vocabulary.

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
- `cache.py` — the user-owned per-file extraction cache. It lives under the
  platform cache directory, outside the scanned repository, in a directory
  keyed by the repository's resolved path. Reuse requires the current file's
  SHA-256 digest plus a valid entry shape; the whole cache invalidates on a
  cache-schema or generator-version change. Any doubt reads as a miss. An
  override that resolves inside the target repository disables caching.
- `glossary.py` — the persistent glossary (`glossarize-out/glossary.json`):
  schema validation (`validate_glossary`), load/save, the `show` command, and
  `require_glossary()` (the shared load-or-report-error helper). Bindings may
  only target stable identities (`symbol:` / `file:` / `module:`), never graph
  community or node ids, which are not stable across rebuilds.
- `drift.py` — `build_drift()` compares fresh evidence against the glossary:
  new terms paralleling canonical ones, discouraged/deprecated terms still in
  use, canonical terms fading from code, and canonical terms living in disjoint
  contexts. Findings are evidence with confidence, never auto-fixes.
- `reconcile.py` — `build_validation()`: two-directional coverage plus the
  mismatch taxonomy (unnamed structure, orphaned concept, unresolved binding,
  boundary mismatch, fragmentation, overloaded region) — heuristic alignment
  with no one-to-one community=concept assumption anywhere.

## Key flows

**`scan` / `analyze`** (`cli.py` → `evidence._scan` → `build_evidence`).
`build_evidence` walks the repo (`scanner.walk_repository`), reads each code and
doc file and hashes its bytes, reuses cached extraction only when that digest
matches, folds identifiers into `_Vocabulary`, extracts imports, optionally
builds structural groups from Graphify, computes naming candidates and
terminology, and returns the evidence dict, which is atomically written to
`glossarize-out/evidence.json`. `analyze` additionally prints a human-readable
terminology report (`_print_terminology_report`). A warm scan still reads every
included file to establish its digest, but avoids tokenization and import/doc
extraction for unchanged content while remaining byte-identical to a cold scan.

**`drift`** (`cli.py` → `drift.drift_command` → `build_drift`). Requires a
glossary (`require_glossary`, exits `1` if absent). Builds fresh evidence,
indexes the glossary's canonical/watched tokens, runs the four checks, writes
`glossarize-out/drift.json`, and prints the report.

**`validate`** (`cli.py` → `reconcile.validate_command` → `build_validation`).
Requires a glossary. Builds fresh evidence (with the Graphify graph if present),
matches canonical concepts against structural groups in both directions,
delegates vocabulary-drift and concept-collision detection to `drift.py`, writes
`glossarize-out/validation.json`, and prints the report. Validation embeds the
adapter's presence/usability/freshness/warning state; all structural sections
carry `skipped: true` plus a reason when usable groups were not loaded.

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
  cost/reason (`PLAN.md` principle 9).
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

## Where things stand

`PLAN.md` is the authoritative roadmap. Phases 0–12 are complete; Phase 13 is
next. Do not duplicate the remaining roadmap here — read it directly.
