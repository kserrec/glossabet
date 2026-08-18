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
promotes vocabulary on its own and never renames code. The "human decides"
half is enforced as an instruction to the skill, not by the engine: `save`
validates and trusts its caller.

## The division of labor

```
  human decides ────────────────────────────────────┐
        ▲                                             │
        │ brainstorms names from evidence             │ approves vocabulary;
  /glossabet skill (skill/SKILL.md)                  │ skill writes GLOSSARY.md
        │                                             │ and the GLOSSABET.md
        │                                             │ health report; CLI saves
        │                                             │ glossary.json
        ▲                                             ▼
        │ runs `glossabet inspect .`; parses bounded JSON stdout
  ┌─────┴──────────────────────────────────────────────────────┐
  │ glossabet engine / CLI  (this Python package)              │
  │ install · inspect · brief · save · scan · analyze · show · drift · validate│
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

Prerequisites: Git, Python ≥ 3.10, and [uv](https://docs.astral.sh/uv/). The
only runtime code is the Python standard library; `pytest` is the sole
development dependency. Hatchling `>=1.32,<1.33` is used only in an isolated
build environment. Nothing is fetched at application runtime.

From a fresh clone, create the locked development environment and run the test
suite:

```bash
git clone https://github.com/kserrec/glossabet.git
cd glossabet
uv sync --locked
uv run pytest -q
```

The preferred Codex distribution is the version-coupled plugin described in
`DISTRIBUTION.md`; its local source is `plugins/glossabet/` and it is not yet
published in a marketplace. Install the standalone fallback CLI onto your
PATH (`~/.local/bin/glossabet`):

```
uv tool install . --reinstall
```

Install the wheel-bundled canonical skill for Codex (or pass
`--agent claude` for Claude Code, which also installs the session-start
`brief` hook as a skills-directory plugin — see `glossabet/claude_plugin.py`):

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
| `configuration` | normalized `glossabet.json` state, or an explicit absent state, plus `shape` — the file's own description (keys, roles, rules, example) carried so the option is met at the point of need |
| `totals` | source/code/doc file, byte, and word counts, including per-role totals |
| `languages`, `modules` | language tally; per-directory module and role inventory |
| `imports` | best-effort internal edges + external dependency tally (lossy, tagged so) |
| `naming_candidates` | ranked, typed "likely deserves a name" nominations (modules, terms, structures), with plain-number reasons |
| `structural_groups` | Graphify presence, usability, warnings, commit freshness, and normalized groups |
| `files` | code/doc files with their production/test/fixture role |
| `vocabulary` | normalization contract plus production-scoped, capped origin-tagged `tokens`, enriched `identifiers`, and `doc_terms` tables |
| `terminology` | production scope, self-accounting register stats, code-vs-doc layers, bounded context-dispersion profiles, synonym and overload nominations |
| `monorepo` | `{detected, reasons, sub_roots}` |
| `skipped` | sensitive, oversized, escaping-symlink, symlink-to-excluded-content, symlinked-directory, unreadable, configured, generated, vendored, self-glossary, self-report, oversized-identifier, and corpus-budget exclusions |

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

The context carries two glossary channels that are never merged. `glossary`
is the validated structured state from `glossabet-out/glossary.json`.
`repository_glossary` (`glossabet/repository_glossary.py`) is the repository's
own hand-maintained root `GLOSSARY.md`, reported as metadata only — presence,
`readable` with a named `reason` (`symlink-escapes-repository`,
`symlink-to-sensitive-file`, `symlink-to-excluded-content`,
`not-a-regular-file`, `oversized`, `unreadable`,
`root-listing-unconfirmed`), byte count, the SHA-256 of
the exact bytes read (the reader takes `MAX_FILE_BYTES + 1` bytes so the bound
is judged from the bytes, not a racy stat), and `nested_ignored`, the non-root
`GLOSSARY.md` files the walk excluded (`skipped.self_glossaries` in evidence)
and never consulted. Its content deliberately never enters the context: that
is what lets the skill build an independent naming baseline before it reads
the maintainers' document (Step 4½ of the skill), and it keeps an unreadable
glossary from ever being mistaken for an absent one.

AgentContext v3 is serialized as compact JSON. Its routine projection samples
tokens/identifiers/document terms at 100/50/50 items, replaces their repeated
file-location lists with per-module occurrence rollups, and retains file paths
only on the naming candidates and register exemplars the skill may inspect.
`glossabet inspect . --full` keeps the former detailed projection for
diagnostics. Both modes have documented per-field limits, a smaller default
list limit, a string ceiling, and at most 100 omission records.
`coverage.corpus` preserves scanner coverage; `coverage.context` names the
projection mode and every omitted section, item, string, or rolled-up file
location. The routine projection has a repository-level regression target of
100 KB (80 KB before Phase 39's subpackages lengthened Glossabet's own module
paths); the universal 1 MB ceiling remains a hard failure backstop. If the
final object cannot fit, the command exits as a user error instead of emitting
partial JSON. This is a model-context boundary, not a replacement for the full
deterministic artifact used by other engine commands.

## Module map

The package is `glossabet/`, laid out as one entry point plus six layer
subpackages (Phase 39). Imports flow downward through this list; a package
name never repeats a module name, so no `x/x` doubling:

```
glossabet/
  cli.py, __main__.py, __init__.py, _skill/     entry point
  runtime/   engine_run, artifacts, display, coverage, git_state
  corpus/    scanner, config, extraction, cache, tokenize, imports
  analysis/  evidence, evidence_view, vocabulary, terminology, importance,
             graphify, evidence_report
  glossary/  store, glossary_commands, repository_glossary, matching,
             findings, drift, reconcile
  agent/     agent_context, brief, managed_block, managed_context, context_sync
  install/   installer, claude_plugin
```

`runtime` is the plumbing every command shares; `corpus` walks, scopes,
reads, caches, and tokenizes the repository; `analysis` turns that into
RepositoryEvidence and its terminology/naming signals; `glossary` holds the
persistent vocabulary state and every check against it; `agent` is what an
agent host sees (`inspect`, `brief`, the managed block); `install` puts the
skill in place. The entries below are grouped by role and named by module;
prefix each with its subpackage (`glossabet.corpus.scanner`, …).

**Entry point and shared plumbing**
- `cli.py` — argparse dispatcher. Owns the exit-status contract: `0` success,
  `1` user or environment error (bad usage, missing input, malformed
  glossary, and `OSError`s such as permission denied or a full disk; a
  closed stdout pipe also exits `1`, silently), `2` internal defect. A custom parser remaps argparse's own exit-2-on-usage-error to `1`.
  Both terminal streams are protected for the entire invocation.
- `engine_run.py` — the one command preamble. `open_run(path_arg,
  glossary=none|optional|required, missing=…)` resolves the repository root
  and applies the glossary policy, returning a `Run(root, glossary)` or
  raising `RunError` (an `ArtifactError`) for the user errors — not a
  directory, unreadable/invalid glossary, required glossary absent — which
  `cli` reports through `print_error` and maps to exit `1`. Every repository
  command opens a run first; none re-spells those decisions or messages.
- `display.py` — centralized terminal rendering. C0/C1 controls, DEL, line
  separators, and bidirectional-format characters from repository/user data
  are rendered as visible escape spellings rather than emitted as terminal
  instructions. Glossary identity fields reject them during validation.
- `artifacts.py` — the reserved `glossabet-out/` plumbing shared by every command:
  `OUT_DIR`, `confined_artifact_path()` (direct artifacts may contain no symlink
  component), `write_artifact()` / `write_json_atomic()` (deterministic,
  same-directory atomic JSON replacement), and the one bounded read
  discipline: `read_bounded_bytes()` / `read_bounded_json()` /
  `parse_bounded_json()` read `cap + 1` bytes (the bound is judged from the
  bytes read, never a racy stat), decode UTF-8 only, catch hostile-nesting
  `RecursionError`, and return a named outcome — absent, read, oversized,
  unreadable, malformed — that `config`, `glossary` (file and stdin),
  `graphify`, `cache`, and `repository_glossary` map to their own
  degradation. `MAX_JSON_BYTES` is the default cap for directly-read JSON.
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
  excluded so the glossary can't echo back into evidence (contamination), and
  the skill-written `GLOSSABET.md` vocabulary-health report (`SELF_REPORT_FILES`,
  any depth, reported as `skipped.self_reports`) is excluded because it is
  derived Glossabet output that must never become evidence for its own next
  run;
  symlinks whose real target escapes the repo root are skipped so a hostile
  repo can't read outside files, and a confined link whose target has a
  sensitive name is classified sensitive, and a link whose target the walk
  itself would exclude (Glossabet's own files, hidden, configured-ignored,
  generated, vendored) is skipped as `symlink-to-excluded-content` — all
  through `symlink_content_refusal()`, the one content rule for symlinked
  paths, which classifies the target's complete repository-relative path and
  which root `GLOSSARY.md` discovery reuses verbatim (its reasons
  `symlink-escapes-repository` / `symlink-to-sensitive-file` /
  `symlink-to-excluded-content` are the scanner's). Every such exclusion is one entry in
  `EXCLUSION_KINDS`, the ledger that owns its `evidence["skipped"]` key, the
  `WalkResult` list that collects it, and the sentence `scan` reports it with
  (`WalkResult.skipped_as_evidence()` emits the section, `exclusion_sentences()`
  renders it, `EvidenceView.skipped_paths()` reads it) — adding a kind is one
  entry, and no other module spells the keys. Root `Cargo.toml` and `package.json`
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
  documented noise reduction. The current conservative Python builtin table
  tags retained tokens as language or domain vocabulary; unlisted languages
  and ambiguous words stay domain. The source matcher is still lexical and
  sees identifier-like text in comments/strings; it does not claim parser
  syntax.

**The aggregation hub**
- `evidence.py` — `build_evidence()` is assembly: walk the repo, hand each
  inventoried file to a `SourceExtractor`, fold production identifiers into
  a `ProductionVocabulary` and production doc words into a
  `DocumentationVocabulary`, then build the imports/structural/terminology/
  naming sections and the evidence dict. It owns the evidence schema
  (`EVIDENCE_SCHEMA_VERSION`, `Limits`, the capped vocabulary tables with their
  location samples) and `write_evidence()`; no printer lives here.
- `extraction.py` — per-file extraction beneath the hub: `read_source()`
  (bytes + digest, or the corpus-budget skip reason), `extract_code_entry()`
  / `extract_doc_entry()`, and `SourceExtractor`, which reuses a valid cache
  entry instead of re-extracting, strips the managed block from docs before
  word extraction, confesses unreadable, binary, and non-UTF-8 files to the
  corpus budget (a file that is not valid UTF-8 is skipped as `not-utf-8`,
  never decoded with dropped bytes into invented vocabulary), and
  keeps the reused/extracted counts and the entries for the next cache save.
- `evidence_report.py` — the `scan`/`analyze` command handlers and their
  terminal rendering (walk/graph/cache summary, exclusion sentences, the
  `analyze` terminology report). Rendering only; every number is read back
  out of the evidence through `EvidenceView`.
- `evidence_view.py` — `EvidenceView`, the read side of RepositoryEvidence:
  the named lookups every consumer repeats (`vocabulary_table(name)`,
  `truncated(name)`, `terminology_section(name)`, `structural_groups()`,
  `skipped_paths(kind)`, `corpus_budget()`, `git()`, …) plus the two
  corpus-completeness rules (`repository_corpus_complete()`,
  `production_corpus_complete()`). `evidence.py` writes the document as a
  literal; every other module reads it through the view, and
  `tests/test_document_keys.py` fails on any evidence key spelled elsewhere.
- `git_state.py` — the filtered Git state of a repository root:
  `repository_git_stamp()` runs `git` with the repo's dangerous config keys
  neutralized (`SAFE_CONFIG` plus per-name filter-driver overrides — see
  Security) and the Glossabet-output freshness pathspec
  (`FRESHNESS_STATUS_ARGS`), returning `{"head", "dirty"}`. The one place
  the engine runs `git`; `evidence` and `brief` call it, the Graphify
  adapter and the cache consume its stamp, and tests substitute it here.
- `agent_context.py` — the `inspect` command and versioned skill boundary.
  It loads the optional glossary through the confined validator, builds fresh
  evidence, applies deterministic list/string/output limits, records all
  projection omissions, and prints JSON only.
- `repository_glossary.py` — safe, content-free discovery of the repository's
  own root `GLOSSARY.md` (tri-state: absent / present+readable with digest /
  present+unreadable with reason) for the `repository_glossary` context
  channel, plus `repository_glossary_divergence`, the one deterministic
  managed-mode signal: NFKC+casefold substring presence of each canonical
  term and superseded alias in the document, capped at 500 terms and at
  4 M normalized characters (NFKC can expand 18×; the length guard runs
  before any search) with the cap reported, surfaced by `inspect` and `validate` only when both files
  exist and the Markdown was read completely. It is not lexical evidence and
  not Glossabet state.
- `brief.py` — the read-only ambient vocabulary projection. It loads no source
  files, reuses the confined glossary validator and hardened Git stamp, and
  emits deterministic plain text capped at 4,096 UTF-8 bytes. The semantic
  glossary SHA-256 names the exact validated state; coverage names every
  omitted canonical concept or truncated entry.

**Analysis over the evidence**
- `vocabulary.py` — the scan's vocabularies as aggregates with named views.
  `ProductionVocabulary`: `fold()` takes each production file's identifier
  counts and keeps every view in step (token counts, per-file/per-module
  counts, positional compound patterns, domain/language origins, in-identifier
  neighbors, capped per-module neighbor sets with their truncation record,
  raw identifier counts/files, and the `MAX_IDENTIFIER_TOKENS` cut count).
  `DocumentationVocabulary`: `fold()` takes each production doc's word counts
  and keeps `term_counts` / `term_files` in step (docs are not
  module-attributed). `build_terminology(vocabulary, doc_term_counts)` and
  `build_naming_candidates(…, vocabulary, …)` take the production aggregate,
  never its views as parallel arguments, and only the documentation
  vocabulary's `term_counts`; tests build one with `from_files()`.
- `imports.py` — best-effort, regex-level import extraction per language
  (`extract_imports`) and a `Resolver` that maps import strings to internal
  modules or external dependencies. Explicitly lossy and tagged `lossy: true`;
  it is never a real dependency graph. RepositoryEvidence imports are
  production-scoped by default.
- `importance.py` — `build_naming_candidates()` combines import fan-in/fan-out,
  repository breadth, doc mentions, source-unit naming, and count-normalized
  diversity from the existing compound-pattern index into ranked "likely
  deserves a name" nominations. Term candidates require an explicit domain
  tag and carry every input in plain-number reasons. They reuse terminology's
  bounded context-dispersion profiles to distinguish "deserves a canonical
  name" from "deserves disambiguation." The score only orders evidence; it
  never makes a term canonical. Streaming top-k selection still reports every
  filtered input and capped detail.
- `terminology.py` — `build_terminology()`: house-register statistics
  (naming-style and identifier-length distributions, common prefixes/suffixes),
  code-vs-doc vocabulary layers, and two nomination kinds — synonym candidates
  (parallel vocabulary like Job/Task/WorkItem, via inverse-frequency-weighted
  cosine similarity) and overloaded-term candidates (one term across disjoint
  contexts). Synonym nominations require low cross-term file overlap, at least
  two shared positional identifier patterns, and calibrated context similarity
  so sibling fields are not mistaken for replacements. All inputs are
  production-scoped and all pairwise work is capped to the top-N domain
  vocabulary after counted language-token exclusion;
  overload dispersion is computed once for both importance and overload
  nominations and has an explicit per-term module ceiling. The full
  eligible-token total and every detail/sample/work omission use the shared
  coverage ledger rather than turning a bounded sample into an exhaustive
  claim. Register headline distributions use only multi-token spellings whose
  snake/camel/Pascal structure is code evidence in its own right. Flat and
  one-token case variants are admitted only when they are domain-origin and
  document mentions do not outnumber identifier-shaped code-file matches. The
  register's `composition` accounts for every spelling as structurally styled,
  corroborated flat, language-tagged flat, prose-dominated flat, or without
  lexical tokens; filtered percentages therefore state their denominator.
- `coverage.py` — the common bounded-collection ledger. Known totals, retained
  details, known drops, total exactness, completeness, and reasons have one
  shape across evidence, candidates, terminology, Graphify, drift, and
  validation. `capped_collection()` is the one way to "cap this list and
  say so" (upstream reasons first, then the cap reason, optional known
  larger total); `capped_section()` returns it in the
  `{items, dropped_items, coverage}` section shape. Bare `coverage_ledger()`
  calls remain only where the ledger is not a list cap: work budgets
  (matching, structural matching), empty/skipped states, and the
  structure-candidate ledger whose drops come from two mechanisms.
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
- `claude_plugin.py` — the Claude Code skills-directory plugin contract that
  `install --agent claude` writes beside the skill: manifest, `SessionStart`
  hook running `brief .`, and version-verified resolution of the `glossabet`
  executable the hook names. Pure data out; `installer.py` does the writing.
- `managed_block.py` — the exact managed block Glossabet may place in a root
  `AGENTS.md`/`CLAUDE.md`: markers, metadata stamp, block regex, the host →
  file map (`AGENT_TARGETS`), and `strip_managed_context_for_evidence()`.
  It sits beneath its users — `managed_context` renders and analyzes the
  block, `context_sync` writes it, the scanner's read path in `evidence`
  strips it — so the aggregation hub never imports a command module.
- `managed_context.py` — the managed block as an *inspected* thing:
  `render_block()` (the exact block one glossary deserves, with its format,
  glossary and content stamps), `read_regular_target()` (bounded,
  identity-checked read of a regular UTF-8 root host file that never follows
  a symlink), `analyze_managed_block()` (absent / current / stale / edited),
  `inspect_managed_context()` (both root targets, read-only; `uninspectable`
  when the file cannot be read), `unchecked_managed_context()`, and
  `print_managed_context_issues()`. `drift` and `reconcile` import the
  inspector and printer from here — analysis never depends on the
  `sync-context` command (`tests/test_module_dependencies.py`).
- `context_sync.py` — the explicit project-context fallback for hosts without
  a trusted lifecycle hook. `sync-context` selects only root `AGENTS.md`
  (Codex default) or root `CLAUDE.md` (explicit Claude target), renders the
  same bounded canonical projection with a stable semantic-glossary stamp
  (through `managed_context`), and atomically appends or replaces one exact
  managed block. It preserves surrounding bytes and the file mode, refuses
  ambiguous marker layouts, rechecks the target before the atomic commit,
  and requires `--force` before replacing an integrity-mismatched body.
- `cache.py` — the user-owned per-file extraction cache. It lives under the
  platform cache directory, outside the scanned repository, in a directory
  keyed by the repository's resolved path. Reuse requires the current file's
  SHA-256 digest plus a valid entry shape; the whole cache invalidates on a
  cache-schema or generator-version change. Cache schema 4 invalidates
  entries from before managed blocks were removed from host-document
  extraction; schema 3 previously invalidated pre-Unicode entries. Any doubt
  reads as a miss. An override that resolves inside the target repository
  disables caching.
- `glossary/store.py` (was `glossary.py`) — the persistent glossary (`glossabet-out/glossary.json`):
  schema validation (`validate_glossary`) and confined load/save. Bindings may
  only target stable identities (`symbol:` / `file:` / `module:`), never graph
  community or node ids, which are not stable across rebuilds. Optional
  `scope.path_prefixes` are literal repository-relative subsystem boundaries;
  aliases inherit the concept scope. Vocabulary identity (the normalized word sequence before the keyword filter; NFKC-casefolded string when wordless) has one owner
  within overlapping scopes, while disjoint scopes may deliberately reuse it.
- `glossary_commands.py` — the `show` and `save` commands: `show` renders the
  loaded glossary; `save` reads one bounded JSON document from standard input
  (`_read_glossary_from_stdin`), then `save_glossary()`, then prints the path.
  Every object rejects unknown fields; accepted concepts, aliases, bindings,
  scope paths, strings, and diagnostics have semantic ceilings. Vocabulary
  ownership uses a per-term path-prefix trie rather than pairwise owner scans.
- `findings.py` — the findings document drift and validation share:
  `finding()` (exactly one of `certainty` / `signal_strength`, the status
  the renderer keys on), `capped_section()` (the findings-flavoured
  `coverage.capped_section` with the reported `FINDINGS_CAP`),
  `empty_section()` (a skipped or scope-limited check with its reason),
  `mark_incomplete()`, the
  evidence-limitation derivation that alone reads RepositoryEvidence's
  `vocabulary[*].truncated` markers and the matcher's work ledgers
  (`vocabulary_omission_reasons()`, `matching_reasons()`,
  `collection_limitations()`), `FindingsDocumentView` (the read side both
  documents share: totals, coverage, managed context, sections by key —
  `drift.DriftView` and `reconcile.ValidationView` add each document's own
  fields, so a document's key spellings live in the module that writes it),
  and `print_sections()`, the one terminal renderer of annotated finding
  lines. `drift` and `reconcile` decide what is a finding; this module owns
  how findings are shaped, bounded, read, and printed.
- `drift.py` — `build_drift()` compares fresh evidence against the glossary:
  new terms paralleling canonical ones, discouraged/deprecated terms still in
  use, canonical terms fading from code, and canonical terms living in disjoint
  contexts. Rule-proven occurrences carry `certainty: observed`; heuristics
  carry `signal_strength`, never uncalibrated confidence. Section caps retain
  legacy `dropped_items` plus the shared coverage ledger, and
  `total_findings` includes displayed and dropped items.
  Every term occurrence, parallel-vocabulary association, fading check, and
  overload check is restricted to its concept's scope and reports that scope.
  Schema 6 also records the read-only managed-context inspection and prints
  stale, edited, or uninspectable host blocks without counting them as lexical
  findings.
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
  Schema 7 carries the same managed-context inspection and terminal warning as
  drift.

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
  verification mode always checks genuineness (untampered, internally
  consistent results with recomputable aggregates and passing thresholds);
  with `--current` — the release gate — it additionally rejects stale engine
  source, schemas, manifest, corpora, source metadata, run count, or
  Graphify case coverage. The other two evidence verifiers follow the same
  two-mode contract, so committed evidence may honestly lag the tree during
  development but can never lag at a release.
- `evaluation/results.json` — the current seven-case, five-run Phase 22 replay,
  including every actual/expected finding key, per-case timing, structured
  engine/version metadata, and digests for the engine, manifest, and each
  accepted corpus.
- `evaluation/review.py`, `reviewer-packet.json`, and `reviewer-results.json` —
  build a label-blinded packet, run one separate Codex reviewer in an isolated
  read-only temporary directory, retain bounded packet-only trace evidence,
  and record disagreements separately from deterministic correctness.
- `scripts/agent_eval.py`, `evaluation/agent-history.json`, and
  `evaluation/agent-results.json` — deterministically bind and smoke the current
  canonical skill, plugin tree, session-start hook, skill-local runner, and
  checked-in wheel;
  retain every authenticated attempt without overwriting earlier raw output;
  and keep safety as a hard gate while reporting stochastic command compliance
  separately. An authorized full run uses three ephemeral Codex sessions: one
  fresh-session hook probe whose prompt does not name Glossabet, one batch of
  12 plugin scenarios (Step 0 only), and one standalone missing-CLI scenario.
  It independently checks contexts, writes, sensitive canaries, exact hook
  bytes, and plugin cleanup. The recorded host is Codex CLI 0.147.0 on Linux
  (latest batch 2026-08-18, 14/14).
  `EVALUATION.md` documents methodology, calibration history, dependency
  decisions, limitations, and reproduction.

**Distribution and first use**
- `plugins/glossabet/` — the local Codex plugin prototype. Its manifest exposes
  the canonical skill and `hooks/hooks.json`; the hook runs the skill-local
  runner's bounded `brief .` command at each Codex session-start lifecycle
  event. The manifest, canonical skill copy, skill-local runner, and nested
  pure-Python wheel all carry version 0.1.0. The runner imports that exact wheel
  from the plugin cache and never installs a second command or environment.
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
- `scripts/check_workflows.py` — standard-library policy checks over every
  workflow file (comments stripped first) for the supported matrix, the CI →
  quality → package / release → quality → publish dependency chains, SHA-pinned
  actions, no fork-PR secret exposure, and no untrusted expression in a shell
  line. A bounded checker of a small YAML subset, not a parser: mutation tests
  prove the important weakenings are rejected without adding a YAML dependency.
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
atomically writes `SKILL.md`. With `--agent claude` (and not `--skill-only`)
it also writes the skills-directory plugin manifest and the `SessionStart`
hook beside it, and runs the selected `glossabet` executable with
`--version` to pin the hook to a working CLI. It never inspects a repository
and writes nothing outside the skill folder.

**`cache-clear`** (`cli.py` → `cache.cache_clear_command` → `cache.clear_cache`).
Removes the user-owned extraction cache and nothing else: it unlinks
`cache.json` (and `cache.json.*` atomic-write temporaries) inside
64-hex-named per-repository directories under Glossabet's cache root, removes
those directories and then the root only once empty, never follows a
symlink, and reports every unrecognized entry it left in place — so a
misconfigured `GLOSSABET_CACHE_DIR` pointing at, say, a home directory can
never be wiped. It reads no repository.

**`scan` / `analyze`** (`cli.py` → `evidence_report._scan` → `evidence.build_evidence`).
`build_evidence` loads `glossabet.json`, walks and role-classifies the repo
(`scanner.walk_repository`), reads each included code/doc file and hashes its
bytes (`extraction.SourceExtractor`), reuses cached extraction only when that
digest matches, folds production identifiers into a `ProductionVocabulary` and
production doc words into a `DocumentationVocabulary`, extracts production
imports, optionally builds
structural groups from Graphify, computes naming candidates and terminology,
and returns the evidence dict, which is atomically written to
`glossabet-out/evidence.json`. `analyze` additionally prints a human-readable
terminology report (`_print_terminology_report`). Test and fixture paths stay in
the inventory/cache but outside vocabulary signals; generated and vendored
paths are not read. A warm scan still reads every included file to establish
its digest, but avoids tokenization and import/doc extraction for unchanged
content while remaining byte-identical to a cold scan. Any scanner-budget stop
is visible in `skipped.corpus_budget` and on stderr; downstream users must treat
that evidence as partial. For root `AGENTS.md` and `CLAUDE.md`, one exactly
bounded Glossabet managed block is removed before doc-word extraction; the raw
file digest still controls cache reuse and every surrounding human-authored
byte remains evidence.

**`inspect`** (`cli.py` → `agent_context.inspect_command`). Loads and validates
the optional glossary first, builds fresh evidence through the same scanner as
`scan`, refreshes `glossabet-out/evidence.json`, projects the result through
the independent lean `AgentContext` limits, and emits one compact JSON document
on stdout. `--full` selects the detailed diagnostic projection without
changing `RepositoryEvidence`. Malformed, oversized, or symlinked glossaries
and a context that exceeds its hard byte ceiling exit `1` without a lower-trust
fallback. The installed skill parses the routine output and reads only
production paths it names.

**`brief`** (`cli.py` → `brief.brief_command`). Loads only the strictly
validated glossary plus the live filtered Git stamp and emits a read-only
canonical-vocabulary digest. It never scans source, refreshes evidence, or
writes the repository. An absent glossary produces no output; malformed,
oversized, or symlinked glossary input exits `1`. Output is deterministic,
plain text, and at most 4,096 UTF-8 bytes, with a semantic glossary SHA-256,
Git `{head, dirty}` state and `glossary.json`'s own Git state (`git_state.path_git_state`), canonical terms, one-line definitions, scopes,
alias statuses, and explicit projection coverage.

**Plugin `SessionStart` delivery** (`plugins/glossabet/hooks/hooks.json` →
skill-local `run_glossabet.py brief .`). Codex expands `PLUGIN_ROOT` to the
installed plugin cache and runs the exact bundled engine at startup, resume,
clear, and compaction. Plain stdout is additional developer context; the hook
has no separate repository-write path, uses `-B` to suppress interpreter
bytecode beside the plugin runner, and inherits `brief`'s 4,096-byte output
ceiling and empty output when no glossary exists. Codex requires hook trust
before execution; the authenticated evidence harness uses a one-invocation
trust bypass only after digest-checking the temporary plugin bytes.

**`sync-context`** (`cli.py` → `context_sync.sync_context_command`). Requires a
validated glossary and an explicit command invocation. `--agent codex`
(default) maps to root `AGENTS.md`; `--agent claude` maps to root `CLAUDE.md`.
The persistent body shares brief's canonical projection and 4,096-byte bound,
but replaces live Git state with a semantic-snapshot line so the act of writing
cannot make its own stamp false. The outer metadata binds format, glossary,
and content hashes. An absent block is appended, an integrity-valid stale block
is replaced, and a current block does not write. An edited body needs
`--force`; malformed/duplicated/unmatched markers or metadata are never
overwritten. The same-directory atomic commit rechecks target bytes and mode
before replacement and preserves every byte outside the managed range.

**`save`** (`cli.py` → `glossary_commands.save_command`). Accepts at most 64 MB from
standard input (reading one additional byte only to detect overflow), parses
exactly one JSON document, applies the strict glossary schema and semantic
budgets, then calls `save_glossary()` for a confined, atomic replacement. The
skill is instructed to use this flow only after human approval and never to
write the machine artifact directly; `save` itself cannot verify that approval
happened.

**`drift`** (`cli.py` → `drift.drift_command` → `build_drift`). Requires a
glossary (`open_run(..., glossary=required)`, exits `1` if absent). Builds
fresh evidence (`evidence.persist_evidence`),
indexes the glossary's canonical/watched tokens and ownership scopes, runs the
four checks within those path regions, writes `glossabet-out/drift.json`, and
prints the report. It also inspects both supported managed-context targets
without following links, persists that separate status, and visibly flags
stale, edited, or uninspectable blocks.

**`validate`** (`cli.py` → `reconcile.validate_command` → `build_validation`).
Requires a glossary. Builds fresh evidence (with the Graphify graph if present),
matches canonical concepts against structural groups in both directions,
delegates vocabulary-drift and concept-collision detection to `drift.py`, writes
`glossabet-out/validation.json`, and prints the report. Validation embeds the
adapter's presence/usability/freshness/warning state; all structural sections
carry `skipped: true` plus a reason when usable groups were not loaded.
Scoped lexical checks still run, while structural sections disclose partial or
skipped scope coverage because normalized Graphify groups have no path map.
It carries the same read-only managed-context report as drift.

## Git freshness and artifact lifecycle

`git_state.repository_git_stamp()` records the live-state definition used in evidence. It reads
`HEAD`, then run porcelain-v1 status with all untracked files, rename detection
disabled, and these scanned-root-relative pathspecs:

```
.
:(exclude)glossabet-out
:(exclude)glossabet-out/**
:(exclude)GLOSSABET.md
```

The engine runs Git from the selected repository directory. The skill no
longer runs Git itself: `inspect` creates its context from the live scan in the
same invocation, while `brief` reuses the same filtered stamp without scanning
or writing. The exclusions deliberately omit Git's `top`
modifier so a subproject scan inside a larger worktree excludes the
subproject's output rather than an unrelated checkout-root path. They apply
whether output is tracked or untracked. Disabling rename detection ensures a
move across the ownership boundary still reports the changed non-output path.
The third pathspec is the scan root's own `GLOSSABET.md` vocabulary-health
report — derived Glossabet output like the directory, so regenerating it never
makes the inputs it was built from look stale; a nested subproject's report is
that subproject's output and stays visible here. No other path inside the
scanned root is filtered: source, `GLOSSARY.md` (human-governed vocabulary —
deliberately not treated as output despite the similar name),
Graphify output, and the legacy repository-local cache path all retain normal
Git status behavior. `AGENTS.md` and `CLAUDE.md` are likewise normal Git state:
an uncommitted synchronized block makes a tracked or untracked target visible
as dirty. Git-ignored files remain invisible under Git's own rules,
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
reserved directory and is never excluded from freshness. `GLOSSABET.md`, also
at the root, is the third artifact and the opposite case: the skill's
human-readable analysis of vocabulary health (gaps, overloads, suspected
synonyms, drift, glossary/code disagreement, structural mismatches, proposals
marked as proposed, open questions, coverage limits), written at Step 7 of the
skill, refreshed as one report rather than appended to, never machine state
(deleting it changes nothing canonical), never lexical evidence, and never a
freshness input. The engine neither reads nor writes it; `artifacts.REPORT_FILE`
is the one spelling the scanner exclusion and the freshness pathspec share. When a repository
already has one before Glossabet is ever run, the skill treats it as
maintainer-owned: it edits it surgically for settled decisions only, re-checks
its SHA-256 against the inspect-time value before writing, and regenerates it
wholesale only on the user's literal request.

## Security and trust boundaries

Glossabet is pointed at repositories that may be untrusted, so the scanned
repo's contents are treated as attacker-controllable input. The enforced
boundaries — sensitive-file/directory exclusion, symlink-escape prevention, no
contamination, per-input size caps, neutralizing the scanned repo's git
config so it can't execute code, and catching malformed input cleanly rather
than crashing as a "defect" — are documented with their regression tests in
`SECURITY.md`. Read that file before touching `scanner.py`, `git_state.py`,
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

`PLAN.md` is the authoritative roadmap. Phases 0–22, 24–32, and 34–36 are
complete (Phase 35 and 36 were zero-behaviour-change refactors, each step
verified byte-identical against a command oracle over the local corpus
fixtures); Phase 33.2 (live Claude Code hook evidence) and Phase 36.8 (live
post-approval skill scenarios) remain, and both need an explicit usage
authorization to run. The owner self-testing pause is active: no outside
maintainer invitation, and no Phase 23 work until the trusted-alpha gate
passes. Package metadata, the embedded plugin wheel, source skill, hook, and
deterministic artifact record are bound together and current as of
2026-08-18. The installed-agent history retains its procedural
failures instead of presenting a selected green run. The trusted-alpha
evidence gate, Phase 23, and explicit external authorization remain before
public package or plugin publication.
