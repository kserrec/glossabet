# Security

## Threat model

Glossarize is a command-line tool you point at a repository. It does not run a
server, open a network socket, evaluate or execute any code it reads, or invoke
a shell. Its one external process is `git`, always called with list arguments
(never a shell string), with a timeout.

The realistic attacker is a **hostile repository**: you clone an open-source
project (or receive one) and run `glossarize scan` on it. Everything in that
repo is attacker-controlled input — its source files, and the three JSON files
glossarize reads directly:

- `graphify-out/graph.json`
- `glossarize-out/glossary.json`
- `.glossarize/cache.json`

The security goal is that scanning a hostile repo cannot read files outside the
repo, cannot exhaust the machine, and cannot execute anything. Reported findings
below have been fixed with pinned regression tests.

## Boundaries enforced in code

- **The repo is the boundary.** Only files whose real path lies inside the
  repository root are read. A symlink resolving outside the root is skipped and
  recorded under `skipped.symlinks_escaping_repo` in evidence — it is never
  read. (`os.walk(followlinks=False)` guards directory symlinks; the explicit
  `_escapes` check in `scanner.py` guards file symlinks.) Regression:
  `tests/test_evidence.py::test_symlink_escaping_repo_is_not_ingested`.
- **Sensitive files and paths never enter any artifact.** Filenames and
  directory names matching `_SENSITIVE_PATTERNS` (`.env`, keys, credentials,
  anything containing `secret`/`credential`) are excluded and reported, never
  ingested. Regression: `test_sensitive_files_never_enter_evidence`,
  `test_sensitive_directories_pruned_and_reported`.
- **All input reads are size-bounded.** Walked files are capped at
  `MAX_FILE_BYTES` (2 MB); the three directly-read JSON artifacts are capped at
  `MAX_JSON_BYTES` (64 MB) before `json.loads`, so a giant artifact cannot
  OOM the process. graph.json degrades to lexical-only, glossary.json is a
  clean user error (exit 1), cache.json is treated as a miss. Regressions:
  `test_oversized_graph_degrades_lexical_only`,
  `test_oversized_glossary_refused_as_user_error`.
- **The cache cannot poison evidence.** A cache entry is trusted only when its
  recorded `mtime_ns` and `size` match the file on disk; any mismatch is a
  miss, so a pre-seeded `.glossarize/cache.json` cannot inject fabricated
  identifiers. (Verified by audit probe; the mtime/size check predates the
  audit.)
- **No contamination.** `glossarize-out/`, `.glossarize/`, `graphify-out/`, and
  `GLOSSARY.md` (at any depth) are excluded from the lexical walk so the
  glossary cannot echo back through evidence.
- **The scanned repo's git config cannot execute code.** glossarize runs
  `git rev-parse`/`git status` inside the target repo to stamp HEAD and dirty
  state. A repository's own `.git/config` can name programs git executes
  (`core.fsmonitor` runs on `git status`; hooks on other operations), so every
  git call overrides those keys to empty (`-c core.fsmonitor=`,
  `-c core.hooksPath=/dev/null`) and disables credential prompts. A hostile
  `.git/config` therefore cannot achieve code execution. Note: `git clone`
  does not copy a remote's `.git/config`, so the delivery vector is a repo
  received with its `.git/` directory intact (a tarball, a shared drive).
  Regression: `test_hostile_git_config_does_not_execute_code`.
- **Malformed input never crashes as an "internal defect."** All three JSON
  readers catch `RecursionError` (a deeply nested payload — `[[[[…]]]]` — which
  `json` raises outside the `ValueError` hierarchy) alongside decode errors, so
  a hostile artifact degrades cleanly (graph → lexical-only, glossary → user
  error, cache → miss) instead of exiting 2 and blaming glossarize.
  Regressions: `test_deeply_nested_graph_json_does_not_crash`,
  `test_deeply_nested_glossary_json_is_clean_error`,
  `test_deeply_nested_cache_json_is_a_miss`.

## Known trust decisions (accepted, do not re-litigate)

- **`graphify-out/graph.json` freshness is unverified.** Graphify stamps no git
  state glossarize can check, so structural evidence is tagged
  `freshness_unverified: true` rather than trusted as current. This is a data-
  quality caveat surfaced to the user, not a security hole — the adapter still
  bounds and shape-checks everything it reads.
- **In-repo symlinks are followed.** A symlink whose target is inside the repo
  is read normally (its content is legitimately repo content). Only escaping
  symlinks are skipped.

## Reporting

This is a personal project not yet published. If it ships, add a contact route
here.
