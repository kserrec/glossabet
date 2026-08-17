# Security

## Threat model

The Glossabet CLI is a local tool. Its repository-analysis commands are
read-mostly: they do not run a server, open a network socket, import
target-project modules, evaluate source, or invoke a shell. Their one external
process is `git`, called with argument lists and a timeout. The separate
`install` command does not analyze a repository; it copies the wheel-bundled
canonical skill to a reported personal or explicitly selected directory.

The realistic attacker is a **hostile repository**: a user clones or receives
an untrusted project and runs Glossabet against it. Repository-controlled
inputs include source and documentation files, Git metadata, the two JSON
artifacts plus repository configuration read directly, and any paths
pre-created where Glossabet writes:

- `glossabet.json`
- `graphify-out/graph.json`
- `glossabet-out/glossary.json`
- `glossabet-out/` output paths

The incremental extraction cache is deliberately not on that list. It is
user-owned local state outside the scanned repository.

The enforced goal is that repository-controlled paths cannot make Glossabet
read content outside the repository, redirect an artifact write, or execute
repository code; individual inputs are size-bounded and malformed inputs
degrade according to a documented contract. Aggregate lexical work is bounded
per scan by source-file, source-byte, walked-entry, and per-directory-entry
ceilings. These ceilings bound input work; they are not a fixed wall-clock or
peak-memory guarantee because identifiers and repository layouts vary.
Glossary structure and the agent-facing output have independent semantic
ceilings, and repository-controlled terminal text must not execute control
sequences or reorder the displayed result.

## Boundaries enforced in code

### Repository reads

- **Walked source stays inside the repository.** The bounded manual
  `os.scandir` traversal does not descend through directory symlinks. A source
  or documentation file symlink
  whose real target is outside the repository is skipped and recorded under
  `skipped.symlinks_escaping_repo`; its target is not read. Root
  `Cargo.toml`/`package.json` workspace probes use the same escape check.
  Regressions: `test_symlink_escaping_repo_is_not_ingested`,
  `test_escaping_root_workspace_manifest_symlink_is_not_read`.
- **Direct JSON paths are stricter than source paths.** Every component of
  `glossabet.json`, `graphify-out/graph.json`, and
  `glossabet-out/glossary.json` must be a real path, not a symlink. A graph
  violation becomes a visible lexical-only warning; a configuration or
  glossary violation is a clean user error. This prevents a hostile checkout
  from using a direct-input symlink to read another file, including an
  unrelated file inside the repository. Regressions:
  `test_symlinked_config_is_rejected_without_reading_target`,
  `test_symlinked_graph_degrades_without_reading_target`,
  `test_glossary_symlink_is_rejected_without_reading_target`, and
  `test_inspect_rejects_symlinked_glossary_without_reading_target`.
- **Reads are individually size-bounded.** Walked code, documentation, and
  inspected root manifests are capped at `MAX_FILE_BYTES` (2 MB). Direct JSON
  artifacts and the user cache are capped at `MAX_JSON_BYTES` (64 MB) before
  `json.loads`; `glossabet.json` has a tighter 1 MB cap. An oversized graph
  degrades to lexical-only, an oversized configuration or glossary is a user
  error, an oversized cache is a miss, and an oversized root manifest is
  skipped and reported. Regressions include
  `test_oversized_config_is_a_user_error`,
  `test_oversized_graph_degrades_lexical_only`,
  `test_oversized_glossary_refused_as_user_error`, and
  `test_oversized_root_workspace_manifest_is_skipped`.
- **Aggregate lexical work is bounded and partial coverage is explicit.** A
  scan includes at most 10,000 code/documentation files and 32,000,000 source
  bytes, processes at most 100,000 directory entries, and accepts at most
  10,000 entries from one directory. Source-file/byte exclusions retain exact
  counts and a bounded path sample. A walk limit cannot count the unseen tree
  without defeating itself, so it records a lower bound, reason/path sample,
  and `exact: false`. An overfull directory is skipped whole rather than
  selecting nondeterministically from filesystem order. Every budget stop sets
  `skipped.corpus_budget.complete` false and emits a partial-evidence warning.
  Regressions: `test_corpus_file_budget_is_deterministic_and_reported`,
  `test_corpus_byte_budget_reports_skips_and_can_use_later_space`,
  `test_walk_work_budget_marks_unknown_remainder`, and
  `test_overfull_directory_is_skipped_whole_to_preserve_determinism`.

### Repository writes

- **Generated writes cannot be redirected through symlinks.** The
  `glossabet-out` directory and final artifact path may contain no symlink
  component. An unsafe path is a clean user error, and no target is written.
  Regressions: `test_evidence_symlink_cannot_overwrite_outside_file`,
  `test_output_directory_symlink_cannot_redirect_writes`.
- **JSON artifacts are replaced atomically.** Glossabet writes a complete
  same-directory temporary file, flushes it, then commits with `os.replace`.
  A failed commit leaves the previous artifact intact and removes the
  temporary file. This prevents interrupted writes from leaving half a JSON
  document; it is not a guarantee against storage-device failure after the
  replacement. Regressions are in `tests/test_artifacts.py`.

### Managed project context

- **Only an explicit command selects this write path.** `sync-context` is the
  sole product route that targets a project-owned host instruction file. Its
  closed mapping is root `AGENTS.md` for Codex (the default) or root
  `CLAUDE.md` for explicit `--agent claude`; no arbitrary target path is
  accepted. `install`, `brief`, the plugin hook, the agent skill's glossary
  finalization, and every analysis command do not call it. Regression:
  `test_every_other_repository_command_leaves_host_file_byte_identical`.
- **The target is bounded and cannot redirect the read or write.** Existing
  targets must be regular UTF-8 files no larger than 2,000,000 bytes. The
  reader uses a non-following file descriptor where the platform supplies it,
  compares pre-open, opened, and post-open identities, and reads at most one
  byte beyond the cap. Symlinks, directories, other non-files, invalid UTF-8,
  and oversized files are user errors. The atomic commit preserves the prior
  mode, rechecks the bytes and mode before `os.replace`, and cleans its
  temporary file after failure. Regressions include
  `test_symlink_target_is_never_followed_or_replaced`,
  `test_unsafe_existing_targets_are_unchanged`,
  `test_atomic_replace_failure_preserves_original_and_cleans_temporary_file`,
  and `test_concurrent_target_change_is_not_overwritten`.
- **Markers define ownership; ambiguity preserves the file.** A missing block
  is appended without altering preceding bytes. One current deterministic
  block is a no-write operation, and one integrity-valid stale block is
  replaced inside its exact markers. A body that no longer matches its content
  stamp, or a newer unsupported format, requires explicit `--force`. Changed,
  missing, duplicate, nested, or malformed markers/metadata are never replaced,
  even with force. Surrounding bytes and line-ending style are covered by
  `test_stale_block_updates_only_the_managed_range`,
  `test_claude_target_preserves_crlf_surrounding_bytes_and_file_mode`, and the
  collision cases in `tests/test_context_sync.py`.
- **Health checks do not write host files.** `drift` and `validate` inspect
  both fixed targets read-only, never follow target symlinks, and record/print
  `stale`, `edited`, or `uninspectable` state. Absence and current state are not
  warnings. A structurally bounded block is removed from documentation text
  before lexical extraction so it cannot echo glossary words into drift; the
  hand-written surrounding file remains evidence. Cache schema 4 invalidates
  older extracted copies. Regressions:
  `test_drift_and_validate_flag_stale_and_edited_blocks` and
  `test_managed_block_never_echoes_into_repository_evidence`.

The pre-commit identity check catches an ordinary concurrent edit before the
replacement, but portable `os.replace` is not a filesystem compare-and-swap.
Do not run `sync-context` while another process is concurrently changing the
same host file. This is the same live-checkout limitation stated for scans,
not a claim that hostile concurrent mutation can be made atomic on every
supported platform.

### Agent skill installation

- **Existing user content is preserved by default.** `glossabet install` is
  idempotent when the destination already has the canonical bytes. A different
  existing `SKILL.md` is a user error and remains untouched unless `--force`
  is explicit. Neighboring files are never replaced. Regression:
  `test_install_refuses_different_existing_skill_without_force`.
- **A symlink cannot redirect installation.** Every existing destination
  component is checked before and after directory creation; symlinked
  components and non-file targets are refused. The final file is written by a
  same-directory temporary file plus `os.replace`. Regressions:
  `test_install_refuses_symlinked_destination_components` and
  `test_force_replaces_only_the_skill_file_and_leaves_no_temporary_file`.
- **Package data is pinned to the repository source of truth.** Hatch maps
  `skill/SKILL.md` directly to `glossabet/_skill/SKILL.md`; focused tests and
  the built-wheel smoke test compare the bytes rather than maintaining an
  independent hand-copied skill.
- **The Codex plugin carries one matched engine/skill pair.** The manifest,
  canonical skill instructions, skill-local runner constant, nested wheel
  metadata, imported package version, and wheel-embedded skill all identify
  the same release. The runner accepts only one exact wheel filename and
  requires Python 3.10 or newer before importing it directly from the plugin
  cache. Build, unit, archive, and actual Codex lifecycle probes fail on a
  mismatch; the plugin never installs a second package or command on `PATH`.
- **The plugin hook has the same confined read boundary.** The manifest exposes
  one exact `SessionStart` handler for startup, resume, clear, and compaction.
  It runs the skill-local runner as `brief .`, disables Python bytecode writes
  beside that runner, times out after 30 seconds, and contributes the complete
  output only because `brief` itself has a 4,096-byte ceiling. It does not scan
  source or add a repository-write path, and an absent glossary emits nothing.
  Build, archive, unit, and installed-plugin smoke checks bind the exact hook
  bytes and command. Codex still requires the user to trust the hook; the
  authenticated harness bypasses that prompt for one invocation only after
  checking the temporary plugin against the current artifact digest.
- **Plugin lifecycle cleanup is narrowly owned.** The host-level smoke uses a
  random marketplace name, records Codex's returned install path, removes the
  plugin and marketplace in a `finally` block, and removes only the exact
  marketplace cache parent after proving it is empty. It never recursively
  deletes a user directory or touches another marketplace.
- **Installed-agent evidence tests the delivered boundary.**
  `scripts/agent_eval.py` uses a second unique temporary marketplace, proves
  Codex read the exact installed plugin skill and version-checked its bundled
  engine. Its fresh-session probe additionally requires the canonical term and
  definition to arrive from the exact installed hook without a product-naming
  user prompt or agent tool call. It then runs 10 plugin scenarios and one
  standalone missing-CLI scenario. Command/event/output storage is capped.
  Repository snapshots treat dotenv names as opaque and never read their
  contents; a separate unreadable sensitive file carries a synthetic canary
  that must not appear in raw JSONL or the agent response. Only the normal
  `inspect` evidence refresh is allowed; every other write fails the scenario.
  Cleanup is the same exact-path, re-queried lifecycle above. Each authorized
  attempt is appended with explicit canary, write, post-failure-inspect, and
  cleanup outcomes; any failed safety check fails the offline gate even when a
  later attempt passes. Full runs use unique immutable result paths and refuse
  overwrite; the current-result mirror is accepted only when its digest matches
  retained raw evidence and its complete input identity matches current bytes.
  Separately, the offline gate hashes and directly smokes the current canonical
  skill, plugin tree, hook, skill-local runner, and checked-in wheel, and
  rejects an ambiguous plugin-root runner.
  Agent command-choice success is reported as reliability evidence rather than
  substituted for those deterministic checks. The committed evidence covers
  two 12/12 Phase 28.2 batches on Codex CLI 0.147.0/Linux, including the
  replacement on final metadata-only rebuilt bytes. Other hosts remain
  unverified.

### Agent context and terminal output

- **The skill consumes CLI output, not repository artifacts.** The installed
  skill starts with `glossabet inspect .`. The command loads the optional
  glossary through the same confined, strict validator as `show`, builds fresh
  evidence through the bounded scanner, refreshes the normal evidence
  artifact atomically, and emits one versioned JSON document. The skill is
  explicitly forbidden from opening Glossabet JSON artifacts or falling back
  to an unrestricted recursive read when this command fails. Regressions are
  in `tests/test_skill.py` and `tests/test_agent_context.py`.
- **The skill persists machine state through the CLI.** After the human settles
  terms, the skill sends the complete JSON document to `glossabet save .` on
  standard input; it never writes or patches `glossary.json` directly. The
  command accepts at most 64 MB (reading one detection byte beyond the limit),
  parses one document, applies strict validation, and delegates to the confined
  atomic writer. Invalid input leaves an existing glossary intact. Regressions
  include
  `test_save_command_validates_stdin_and_writes_atomically`,
  `test_save_command_rejects_invalid_stdin_without_writing`, and
  `test_save_command_bounds_standard_input`, and
  `test_save_command_cannot_follow_a_glossary_symlink`.
- **Agent output has an independent hard bound.** The context deterministically
  caps named top-level collections and nested lists, truncates overlong strings
  with an omission record, and refuses either more than 100 distinct omission
  records or more than 1,000,000 UTF-8 bytes. `coverage.corpus` describes scanner
  coverage and `coverage.context` describes projection coverage; neither can
  silently read as complete after an omission. Regressions:
  `test_context_sampling_is_explicit` and
  `test_context_hard_byte_limit_fails_cleanly`.
- **Ambient vocabulary is a narrower read-only projection.** `brief` loads only
  the confined, strictly validated glossary and the hardened Git stamp. It does
  not walk source files or write the repository. Its deterministic text is
  capped at 4,096 UTF-8 bytes and reports omitted concepts and truncated
  entries; an absent glossary emits nothing. Regressions in
  `tests/test_brief.py` cover determinism, source/secret non-contamination,
  symlink refusal, terminal-safe one-line prose, and the byte ceiling.
  `tests/test_plugin.py` additionally executes the declared hook command with
  and without a glossary and proves exact output plus zero repository changes.
- **Persistent ambient vocabulary remains separately human-authorized.** The
  skill states that ordinary ambient context is read-only and that glossary
  finalization does not authorize `sync-context`. It may run that command only
  after a separate explicit human request naming the desired host target.
- **Terminal controls are data, not instructions.** CLI stdout/stderr pass
  through `display.py`. Repository/user-controlled C0/C1 controls, DEL, Unicode
  line separators, and bidirectional-format characters are rendered as visible
  escape spellings. Glossary identity fields reject them; prose permits only
  ordinary line feed/tab layout and the renderer escapes those when embedded
  in a displayed value. JSON output uses JSON escaping as an additional layer.
  Regressions: `test_repository_control_sequences_are_rendered_visibly`,
  `test_unexpected_exception_text_is_terminal_safe`, and
  `test_terminal_controls_and_bidi_formatting_are_rejected`.

### Incremental cache

- **A repository cannot supply trusted extraction results.** Cache state lives
  under the current user's platform cache directory, keyed by a SHA-256 hash
  of the repository's resolved path. Repository-local `.glossabet/cache.json`
  is legacy, excluded from evidence, and never loaded. If
  `GLOSSABET_CACHE_DIR` would place the cache inside the scanned repository,
  caching is disabled.
- **Reuse is content-based.** Every included file is read and SHA-256 hashed on
  every scan. Cached identifier/import/doc extraction is reused only when its
  recorded digest matches those current bytes and its shape is valid. A cache
  schema or generator-version mismatch, wrong repository identity, malformed
  JSON, wrong top-level type, invalid entry shape, symlinked cache file, or I/O
  failure is a miss. Regressions include
  `test_same_size_same_mtime_rewrite_invalidates_by_content`,
  `test_ascii_tokenizer_cache_version_is_invalidated`,
  `test_repository_supplied_legacy_cache_is_never_trusted`, and
  `test_wrong_top_level_cache_json_is_a_miss`.

The cache protects against the hostile-repository attacker defined above. It
does not try to defend against another process already able to modify files as
the same operating-system user; that process could also modify the installed
Glossabet program or its output artifacts.

### Content, execution, and malformed input

- **Sensitive-path exclusion is path-based, not secret scanning.** Files and
  directories matching `_SENSITIVE_PATTERNS`—dotenv names, key/certificate
  extensions, credential stores, or names containing `secret`/`credential`—are
  excluded and reported. Glossabet does not inspect source text for API keys,
  passwords, or other secret-like values. A secret embedded in an ordinarily
  named `.py`, `.js`, or documentation file can therefore appear as lexical
  evidence. Do not treat the output as sanitized. Regressions for the path
  boundary: `test_sensitive_files_never_enter_evidence`,
  `test_sensitive_directories_pruned_and_reported`.
- **Repository configuration is data, not code.** `glossabet.json` accepts
  only a version, literal repository-relative ignore prefixes, and literal
  path-role prefixes. Absolute paths, parent traversal, glob syntax, unknown
  fields/roles, duplicate equal-path roles, excessive path lengths/counts,
  malformed JSON, and symlinks are rejected as user errors. Matching is plain
  string-prefix comparison; configuration never causes a filesystem path to
  be opened directly. Regressions are in `tests/test_config.py`.
- **Glossary data is strict and semantically bounded.** Every glossary object
  rejects unknown fields. Optional concept scopes accept only a non-empty list
  of non-overlapping literal repository-relative path prefixes; absolute paths,
  parent traversal, globs, backslashes, empty lists, duplicates, and unknown
  fields are rejected. A valid document may contain at most 10,000 concepts,
  50,000 aliases, 50,000 bindings, and 50,000 scope prefixes; identity strings
  are capped at 1,024 characters, prose at 16,384, aggregate scope text at
  1,000,000 characters, inherited vocabulary/scope work at 5,000,000
  characters, and returned diagnostics at 100. Aggregate counts are checked
  before per-entry validation. Scope checks
  compare paths already present in bounded evidence; they never open a glossary
  path. NFKC-casefolded ownership uses a per-term path-prefix trie, so disjoint
  scopes do not trigger pairwise owner comparisons. Regressions include
  `test_unknown_glossary_fields_are_rejected_at_every_object_level`,
  `test_validation_diagnostics_are_bounded`,
  `test_concept_budget_is_checked_before_per_concept_validation`, and
  `test_vocabulary_owner_validation_uses_indexed_scope_lookup`.
- **Target Git configuration cannot name an executable.** Each
  `git rev-parse`/`git status` call overrides `core.fsmonitor` and
  `core.hooksPath`, and additionally clears every content-filter driver the
  repository defines (`filter.<name>.clean/smudge/process`, enumerated from
  the repository's *effective* config with `include.path`/`includeIf`
  directives resolved exactly as `git status` resolves them — not just the
  literal `.git/config` — and overridden per name), because `git status`
  runs those commands during content conversion of a modified tracked file.
  The `git` executable is resolved to an absolute path so a repository that
  ships `git.exe` cannot be run through Windows's current-directory search.
  Every call uses no shell, disables credential prompts, and has a timeout.
  The status call uses stable porcelain output, requests all
  untracked files, disables rename detection, and excludes only the
  top-level, Glossabet-owned `glossabet-out/` path relative to the directory
  being scanned. This exclusion is an argument to Git, not a mutation of
  `.gitignore`; it also works for subproject scans inside a larger worktree,
  and moving a file across the boundary still exposes the non-output side.
  Regressions:
  `test_hostile_git_config_does_not_execute_code` and
  `tests/test_freshness.py`.
- **Malformed JSON is classified, not blamed on an internal defect.** Graph
  problems warn and fall back to lexical evidence; configuration and glossary
  problems are user errors; cache problems are misses. This includes wrong
  top-level types and deeply nested JSON raising `RecursionError`.
- **Generated evidence does not feed itself.** `glossabet-out/`, legacy
  `.glossabet/`, `graphify-out/`, and `GLOSSARY.md` are excluded from the
  lexical walk. Graphify is consumed only through its bounded adapter.
- **Non-production code has an explicit boundary.** Tests and fixtures are
  inventoried and cached with a visible role but do not feed lexical
  vocabulary or heuristic signals. Generated and vendored paths are pruned
  before content reads and reported. The optional configuration can override
  conservative defaults or add ignores; sensitive and self-output exclusions
  remain non-overridable.

## Data and network behavior

The CLI itself makes no network requests. Its artifacts can contain repository
paths, identifiers, import strings, aggregate documentation terms, Graphify
labels, normalized configuration paths, and human-written glossary
definitions. They should be handled with the same confidentiality as the
repository.

Phase 16 did not add a parsing library. The evaluated Tree-sitter language-pack
candidate downloads native grammar binaries on first use and caches them; that
would violate the CLI's current no-network behavior unless redesigned around
an explicit installation/prefetch boundary. It was rejected because the new
labels showed no remaining accuracy gain to justify that network, native-code,
cache, and supply-chain surface. The exact package-cost snapshot is in
`EVALUATION.md`.

The developer-only `evaluation/run.py` helper is separate from the CLI. With
an explicit `--fetch`, it asks `git` to retrieve only the public revisions
pinned in `evaluation/corpus.json` into a temporary directory. It disables
prompts and global/system Git configuration, uses no shell, and neither imports
nor executes target-project code. The checked-out source is still untrusted
input to the same scanner boundaries.

The developer-only second-reviewer runner is also separate from the CLI. It
uses an authenticated Codex session in a fresh temporary directory containing
only a usefulness prompt, response schema, and label-blinded finding packet.
The model sandbox is read-only; the harness rejects tool types or commands
outside the packet, caps the JSONL trace, removes the host-written final
response, and proves the two inputs remain byte-identical. This establishes a
second recorded judgment, not isolation from the Codex service or an outside
human review.

The `/glossabet` skill is a separate agent-mediated interface. It receives the
bounded JSON emitted by `glossabet inspect .` and may then read context-named
production code. That content is handled according to
the agent host and model provider's data policy. Glossabet cannot enforce that
external policy, and the path-based exclusions above do not make artifacts
safe to send to an unapproved service.

`PRIVACY.md` gives the complete local and agent-mediated data flow, including
the opt-in developer/release operations that do use the network.

## Known trust decisions and limits

- The production/test/fixture/generated/vendored classification is
  path-convention based, not parser- or provenance-proven. Conservative
  defaults are recorded in the public docs, every included file records its
  effective role, and `glossabet.json` can override project-specific layouts.
  A misclassified path changes analysis scope; inspect per-role totals when
  adopting the tool in an unconventional repository.
- Identifier extraction is NFKC-normalized and Unicode-aware but remains a
  lexical approximation. Identifier-like words in comments and strings can
  enter evidence, and language forms beyond the pinned representative cases
  may split imperfectly. This is not a parser-level symbol claim.
- Evidence freshness uses Git's tracked/untracked worktree model. Generated
  files under the reserved top-level `glossabet-out/` namespace are the only
  excluded paths, whether tracked or untracked. `GLOSSARY.md`, Graphify output,
  the current `.glossabet/` cache name, pre-rename `.glossarize/` and
  `glossarize-out/` paths, and all other paths inside the scanned root remain
  visible to Git freshness unless Git itself ignores them. An explicitly
  scoped subproject scan does not include changes
  elsewhere in the enclosing worktree. Files ignored by Git are not reported
  by `git status` and therefore cannot dirty the stamp; this is a stated limit,
  not a claim that ignored bytes were checked.
  Repositories without a readable `HEAD`, or whose status cannot be checked,
  receive `{head: null, dirty: null}` and are freshness-unverified.
- Graphify 0.9.42 exports `built_at_commit`. Glossabet reports its structural
  evidence as `current` only when that commit matches the current repository
  HEAD and the worktree is clean; a mismatch is `stale`. Legacy graphs without
  the stamp, repositories without a readable HEAD, and matching commits over a
  dirty or uncheckable worktree are `unverified`. These states and adapter
  warnings are embedded in validation output; a present but unusable graph
  causes structural checks to be explicitly skipped. `built_at_commit` is
  repository-controlled metadata: the comparison detects ordinary staleness,
  but a matching value is not proof that graph content is authentic or was
  actually generated from that commit.
- Normalized Graphify groups do not currently carry repository paths. When a
  glossary contains path-scoped concepts, lexical validation remains scoped,
  but structural validation marks coverage partial and skips unnamed-structure
  conclusions that could not be scoped safely.
- In-repository **source** symlinks are followed because their targets are
  repository content. Direct artifact symlinks are rejected for the separate
  read/write-redirection reasons above.
- The scanner assumes the repository is not being adversarially mutated
  concurrently between path validation and file access. Do not run it while an
  untrusted process is rewriting the same checkout. An `inspect` context is
  generated in one command, but is not an atomic filesystem snapshot.
- Corpus ceilings make lexical processing finite, but reaching one necessarily
  makes repository coverage partial. `walk_remainder.exact: false` means the
  number and nature of unseen paths are unknown; consumers must not interpret
  an absent term or finding as repository-wide evidence in that state.
- Per-identifier token analysis is quadratic in token count, so a single
  spelling is capped at `MAX_IDENTIFIER_TOKENS` (64); any file with a longer
  spelling is counted in `skipped.oversized_identifiers` and its excess
  tokens do not enter pattern/co-occurrence analysis. Owner-scope overlap in
  drift is likewise bounded by a comparison budget charged the actual
  path-prefix-pair work each overlap performs (not the owner count, which
  would let one concept carrying tens of thousands of prefixes hide a
  hundred-million-comparison overlap behind a charge of one), and reports its
  section partial when reached. Import extraction is anchored so its
  line-oriented patterns cannot backtrack across blank lines into quadratic
  work. Real code never approaches either bound; both exist to keep a hostile
  glossary or source file from exhausting CPU/memory.
- A symlink whose own name is ordinary but whose in-repository target has a
  sensitive name (for example `notes.py -> .env`) is classified sensitive by
  the resolved target and excluded, so it cannot launder secret contents into
  evidence.
- **Brief content is untrusted repository input.** The vocabulary brief the
  agent skill and the SessionStart hook emit renders terms and definitions a
  repository authored in its committed `glossary.json`. Those bytes are
  bounded, terminal-escaped, and read-only, but they are attacker-controlled
  *text reaching a model* in a cloned hostile repository. The brief header
  labels the content as unverified repository input rather than authoritative
  instruction; a consumer must still weigh it as untrusted.
- **The evaluation harness (`evaluation/run.py --fetch`) rejects non-`https://`
  corpus URLs and disables Git's `ext::` remote helper**, because an
  attacker-authored corpus entry could otherwise run a shell at fetch time on
  a maintainer's machine. The manifest's `checkout_dir` and local-source
  `path` are additionally required to be safe relative paths (no absolute
  path, no `..`, no drive letter) and the resolved checkout is asserted to
  stay inside its base, so a poisoned `corpus.json` cannot create or overwrite
  files outside the temporary checkout root; each `commit` must be a 40- or
  64-character hex object name and is passed after a `--` guard so a value
  beginning with `-` cannot be read as a git option. The three committed
  result artifacts are also size-capped before parsing. This is maintainer
  tooling, not shipped code.
- **Accepted risk — build backend is version-pinned, not hash-pinned.** The
  release build resolves `hatchling>=1.32,<1.33` from PyPI at build time in
  the one job that holds PyPI upload permission; a compromised hatchling patch
  release in that range would run there. There is no clean hash-pin in the
  PEP 517 / `uv build` flow, so this is documented rather than fixed. Every
  other dependency is hash-locked in `uv.lock`; the shipped wheel declares
  zero runtime dependencies.
- Published distributions are scanned at build time for absolute local home
  paths (`/home/<user>/`, `/Users/<user>/`, `C:\Users\<user>`) so a machine
  trace can never leak a maintainer's username or layout onto PyPI; internal
  planning docs are excluded from the source distribution.

## Reporting

The source repository is public, but version 0.1.0 is not yet published to
PyPI. Do not put vulnerability details in a public issue.

The prepared private route is GitHub's **Report a vulnerability** form at
<https://github.com/kserrec/glossabet/security/advisories/new>. Repository
private vulnerability reporting is currently disabled (verified
2026-08-15), so that form is not yet available. `RELEASING.md` makes enabling
the setting and its notifications a hard precondition for package
publication. Until that account-level action is explicitly authorized and
completed, this project does not claim to offer a working private reporting
channel.
