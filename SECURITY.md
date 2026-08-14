# Security

## Threat model

The Glossarize CLI is a local, read-mostly analysis tool. It does not run a
server, open a network socket, import target-project modules, evaluate source,
or invoke a shell. Its one external process is `git`, called with argument
lists and a timeout.

The realistic attacker is a **hostile repository**: a user clones or receives
an untrusted project and runs Glossarize against it. Repository-controlled
inputs include source and documentation files, Git metadata, the two JSON
artifacts read directly, and any paths pre-created where Glossarize writes:

- `graphify-out/graph.json`
- `glossarize-out/glossary.json`
- `glossarize-out/` output paths

The incremental extraction cache is deliberately not on that list. It is
user-owned local state outside the scanned repository.

The enforced goal is that repository-controlled paths cannot make Glossarize
read content outside the repository, redirect an artifact write, or execute
repository code; individual inputs are size-bounded and malformed inputs
degrade according to a documented contract. This is not yet a claim that
arbitrarily large repositories cannot consume substantial aggregate time or
memory: the current per-file and analysis caps do not include a whole-corpus
file/byte budget. That remaining limit is tracked in Phase 15 of `PLAN.md`.

## Boundaries enforced in code

### Repository reads

- **Walked source stays inside the repository.** `os.walk(followlinks=False)`
  does not traverse directory symlinks. A source or documentation file symlink
  whose real target is outside the repository is skipped and recorded under
  `skipped.symlinks_escaping_repo`; its target is not read. Root
  `Cargo.toml`/`package.json` workspace probes use the same escape check.
  Regressions: `test_symlink_escaping_repo_is_not_ingested`,
  `test_escaping_root_workspace_manifest_symlink_is_not_read`.
- **Direct artifact paths are stricter than source paths.** Every component of
  `graphify-out/graph.json` and `glossarize-out/glossary.json` must be a real
  path, not a symlink. A graph violation becomes a visible lexical-only
  warning; a glossary violation is a clean user error. This prevents a hostile
  checkout from using an artifact symlink to read another file, including an
  unrelated file inside the repository. Regressions:
  `test_symlinked_graph_degrades_without_reading_target`,
  `test_glossary_symlink_is_rejected_without_reading_target`.
- **Reads are individually size-bounded.** Walked code, documentation, and
  inspected root manifests are capped at `MAX_FILE_BYTES` (2 MB). Direct JSON
  artifacts and the user cache are capped at `MAX_JSON_BYTES` (64 MB) before
  `json.loads`. An oversized graph degrades to lexical-only, an oversized
  glossary is a user error, an oversized cache is a miss, and an oversized
  root manifest is skipped and reported. Regressions include
  `test_oversized_graph_degrades_lexical_only`,
  `test_oversized_glossary_refused_as_user_error`, and
  `test_oversized_root_workspace_manifest_is_skipped`.

### Repository writes

- **Generated writes cannot be redirected through symlinks.** The
  `glossarize-out` directory and final artifact path may contain no symlink
  component. An unsafe path is a clean user error, and no target is written.
  Regressions: `test_evidence_symlink_cannot_overwrite_outside_file`,
  `test_output_directory_symlink_cannot_redirect_writes`.
- **JSON artifacts are replaced atomically.** Glossarize writes a complete
  same-directory temporary file, flushes it, then commits with `os.replace`.
  A failed commit leaves the previous artifact intact and removes the
  temporary file. This prevents interrupted writes from leaving half a JSON
  document; it is not a guarantee against storage-device failure after the
  replacement. Regressions are in `tests/test_artifacts.py`.

### Incremental cache

- **A repository cannot supply trusted extraction results.** Cache state lives
  under the current user's platform cache directory, keyed by a SHA-256 hash
  of the repository's resolved path. Repository-local `.glossarize/cache.json`
  is legacy, excluded from evidence, and never loaded. If
  `GLOSSARIZE_CACHE_DIR` would place the cache inside the scanned repository,
  caching is disabled.
- **Reuse is content-based.** Every included file is read and SHA-256 hashed on
  every scan. Cached identifier/import/doc extraction is reused only when its
  recorded digest matches those current bytes and its shape is valid. A cache
  schema or generator-version mismatch, wrong repository identity, malformed
  JSON, wrong top-level type, invalid entry shape, symlinked cache file, or I/O
  failure is a miss. Regressions include
  `test_same_size_same_mtime_rewrite_invalidates_by_content`,
  `test_repository_supplied_legacy_cache_is_never_trusted`, and
  `test_wrong_top_level_cache_json_is_a_miss`.

The cache protects against the hostile-repository attacker defined above. It
does not try to defend against another process already able to modify files as
the same operating-system user; that process could also modify the installed
Glossarize program or its output artifacts.

### Content, execution, and malformed input

- **Sensitive-path exclusion is path-based, not secret scanning.** Files and
  directories matching `_SENSITIVE_PATTERNS`—dotenv names, key/certificate
  extensions, credential stores, or names containing `secret`/`credential`—are
  excluded and reported. Glossarize does not inspect source text for API keys,
  passwords, or other secret-like values. A secret embedded in an ordinarily
  named `.py`, `.js`, or documentation file can therefore appear as lexical
  evidence. Do not treat the output as sanitized. Regressions for the path
  boundary: `test_sensitive_files_never_enter_evidence`,
  `test_sensitive_directories_pruned_and_reported`.
- **Target Git configuration cannot name an executable.** Each
  `git rev-parse`/`git status` call overrides `core.fsmonitor` and
  `core.hooksPath`, uses no shell, disables credential prompts, and has a
  timeout. Regression: `test_hostile_git_config_does_not_execute_code`.
- **Malformed JSON is classified, not blamed on an internal defect.** Graph
  problems warn and fall back to lexical evidence; glossary problems are user
  errors; cache problems are misses. This includes wrong top-level types and
  deeply nested JSON raising `RecursionError`.
- **Generated evidence does not feed itself.** `glossarize-out/`, legacy
  `.glossarize/`, `graphify-out/`, and `GLOSSARY.md` are excluded from the
  lexical walk. Graphify is consumed only through its bounded adapter.

## Data and network behavior

The CLI itself makes no network requests. Its artifacts can contain repository
paths, identifiers, import strings, aggregate documentation terms, Graphify
labels, and human-written glossary definitions. They should be handled with
the same confidentiality as the repository.

The `/glossarize` skill is a separate agent-mediated interface. When it asks an
agent to read code or generated evidence, that content is handled according to
the agent host and model provider's data policy. Glossarize cannot enforce that
external policy, and the path-based exclusions above do not make artifacts
safe to send to an unapproved service.

## Known trust decisions and limits

- Graphify 0.9.42 exports `built_at_commit`. Glossarize reports its structural
  evidence as `current` only when that commit matches the current repository
  HEAD and the worktree is clean; a mismatch is `stale`. Legacy graphs without
  the stamp, repositories without a readable HEAD, and matching commits over a
  dirty or uncheckable worktree are `unverified`. These states and adapter
  warnings are embedded in validation output; a present but unusable graph
  causes structural checks to be explicitly skipped. `built_at_commit` is
  repository-controlled metadata: the comparison detects ordinary staleness,
  but a matching value is not proof that graph content is authentic or was
  actually generated from that commit.
- In-repository **source** symlinks are followed because their targets are
  repository content. Direct artifact symlinks are rejected for the separate
  read/write-redirection reasons above.
- The scanner assumes the repository is not being adversarially mutated
  concurrently between path validation and file access. Do not run it while an
  untrusted process is rewriting the same checkout.
- Per-file and pairwise-analysis limits exist, but a deterministic
  whole-corpus file/byte/work budget has not yet been implemented. Phase 15 is
  the tracked work.

## Reporting

This is a personal project not yet published. Before a public release, Phase
17 requires a public security-reporting route.
