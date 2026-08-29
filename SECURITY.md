# Security

Glossabet 0.1.0 is an unreleased local source alpha. This policy describes the
current code; it is not a claim that every hostile operating-system condition
is contained.

## Threat model

The production command-line program treats the selected repository as hostile
static data. An attacker may control names and contents below that repository,
including source, documentation, Git metadata, `glossabet.json`,
`graphify-out/graph.json`, `glossabet-out/glossary.json`, and pre-created output
paths.

The enforced goals are:

- never import or execute analyzed repository code;
- never let an initial repository path redirect a read or write outside the
  selected root;
- bound individual reads and aggregate analysis work;
- reject or explicitly degrade malformed and unsafe inputs;
- escape repository-controlled terminal text;
- preserve existing files when a safe atomic update cannot be proved; and
- record every omission so partial evidence cannot be mistaken for complete
  evidence.

The production package contains no network capability and invokes no shell.
Its one analysis subprocess is a narrowly hardened `git` executable called by
absolute path, argument vector, and timeout. `install` is separate from
repository analysis and copies packaged files only to the reported personal or
explicit destination.

The detailed data-flow and model-provider boundary is in
[`PRIVACY.md`](PRIVACY.md).

## Concurrency boundary

Filesystem claims use three distinct assumptions:

1. A hostile repository that is not mutated while a command runs is in scope.
2. Ordinary concurrent edits are detected where identity or byte rechecks are
   described below. A scan is still not an atomic filesystem snapshot.
3. An adversarial process running as the same operating-system user and racing
   path components between check and use is out of scope. Glossabet does not
   use descriptor-relative traversal with `openat`/`O_NOFOLLOW` on every path
   component. Such a process could also replace the installed program, cache,
   or artifacts. Do not scan a checkout while an untrusted process is rewriting
   it.

The important check/use behavior is:

| Surface | Enforced behavior | Remaining boundary |
| --- | --- | --- |
| Generated JSON paths | Every component is checked for symlinks and confinement before same-directory atomic replacement. Replacing a final symlink replaces the link, not its target. | A parent swapped after the check is same-user adversarial racing and out of scope. |
| Direct JSON reads | The file must be regular and unsymlinked; the bound is judged from bytes actually read, not a prior size. | A path-component swap after validation is out of scope. |
| Root `AGENTS.md` / `CLAUDE.md` | `lstat`, exact-name confirmation, non-following open where available, opened/pre/post device-and-inode comparison, `cap + 1` read, and byte, mode, device, and inode recheck before replacement. A lookup/listing race or unavailable inode identity is uninspectable and fails closed. | An edit after the final recheck but before `os.replace` is not prevented. |
| Scanner walk and source read | Initial target resolution, role, regular-file kind, and walk-time size are checked; directory links are not descended and non-regular source-shaped entries are never opened. | A regular file that changes after the walk can produce a mixed-time scan; adversarial mutation is out of scope. |
| User cache | Bounded unsymlinked read and current-content SHA-256 determine reuse; stale or changed state becomes a miss. | The cache belongs to the same user and is not an attacker-isolation boundary. |
| Skill/plugin install | Destination symlink components are rejected before and after directory creation; differing or newly appearing files require `--force`; writes are atomic. | A parent raced after the final component check is out of scope. |

[`tests/test_filesystem_races.py`](tests/test_filesystem_races.py) proves the
ordinary-change cases and states the unprotected windows directly.

## Repository reads

### Path confinement and exclusions

[`corpus.scanner`](glossabet/corpus/scanner.py) uses a bounded manual
`os.scandir` traversal. It never descends directory symlinks. A source or
documentation symlink is followed only when its resolved target remains inside
the repository and the target itself is not excluded; otherwise the path and
reason are recorded. This prevents an innocent-looking link from laundering a
sensitive, vendored, generated, or Glossabet-owned target into evidence.
Only regular direct entries and regular confined symlink targets are opened.
Sockets, devices, FIFOs, and other non-regular source-shaped entries are
recorded as visible skips instead of being read.

Direct control/artifact inputs are stricter. No component of
`glossabet.json`, `graphify-out/graph.json`, or
`glossabet-out/glossary.json` may be a symlink. Unsafe configuration or
glossary paths are user errors. Unsafe Graphify input degrades to visible
lexical-only analysis.

Sensitive-file filtering is name/path based. It covers dotenv variants,
common private-key and credential-store names, and paths whose components
signal secrets or credentials. The scanner does not open excluded files and
does not claim to find secrets embedded inside ordinarily named source or
documentation. Output must therefore be treated as confidential repository
data.

The root maintainer-owned `GLOSSARY.md` is excluded from lexical evidence at
every depth. Its exact root entry may be bounded-read to report presence,
readability, size, digest, and a validation-only lexical term-presence check.
Readable content must be valid UTF-8. It is not copied into engine evidence or
agent context. A confined symlink is reported as such so the skill will not
write through it; escaping, sensitive-target, excluded-target, dangling,
oversized, invalid-UTF-8, or unconfirmed entries are present-but-unreadable,
never falsely absent or complete.

Glossabet's derived root `GLOSSABET.md` and every nested file with that name are
excluded from evidence. One exact managed Glossabet block is stripped from
`AGENTS.md` or `CLAUDE.md` before documentation tokenization. These rules stop
generated terminology from becoming evidence for itself.

### Bounds and omission accounting

The primary hostile-input limits are:

| Input/work | Limit |
| --- | ---: |
| Walked file size at classification | 2,000,000 bytes |
| Direct JSON artifact | 64,000,000 bytes |
| `glossabet.json` | 1,000,000 bytes, 500 path rules |
| Included code/documentation files | 10,000 |
| Included source bytes | 32,000,000 |
| Walked directory entries | 100,000 |
| Entries accepted from one directory | 10,000 |
| Tokens in one identifier | 64 |
| Agent context | 1,000,000 bytes |
| Canonical brief | 4,096 bytes |
| Existing managed host file | 2,000,000 bytes |
| Glossary | 10,000 concepts, plus independent aggregate alias, binding, scope, identity, and prose limits |
| Graphify input references | 1,000,000 |
| Graphify label characters | 5,000,000 after per-label truncation to 512 characters |
| Graphify group member tokens | 2,000 per group |

Hitting a corpus limit sets `skipped.corpus_budget.complete` false and emits a
warning. When the unseen remainder cannot be counted without defeating the
bound, its total is explicitly a lower bound (`exact: false`). Vocabulary,
terminology, naming, Graphify, matching, drift, validation, brief, and agent
projection use their own ledgers and reasons. Consumers suppress absence or
low-use conclusions when incomplete evidence cannot support them.

Identifier tokenization retains at most the first 64 accepted tokens. After
whole-string Unicode normalization, it stops consuming the lazy splitter once
one more accepted token proves that a tail was omitted. Vocabulary owns that
one bounded prefix; terminology, evidence serialization, naming, and matching
reuse it instead of retokenizing the spelling. An omitted tail makes every
affected token, suffix, layer, naming, and match-absence ledger inexact, so
omitted text cannot support a false absence conclusion.

Graphify is checked for reference work before members are materialized and for
total label characters before tokenization. Unsupported shapes, non-finite or
unusable cohesion, malformed values, oversize, and work-budget exhaustion are
warnings with lexical fallback. Repository-controlled `built_at_commit`
metadata is only a staleness signal, not proof that the graph is authentic.

## Repository writes

JSON artifacts use
[`runtime.artifacts.replace_file_atomic`](glossabet/runtime/artifacts.py): a
complete same-directory temporary file is flushed and then committed with
`os.replace`. Commit failure preserves the prior file and removes the
temporary file. This prevents a half-written document; it is not a guarantee
against storage-device failure after replacement.

Normal write ownership is:

- `scan`, `analyze`, `inspect`, `drift`, and `validate` refresh
  `glossabet-out/evidence.json`;
- `save` alone writes `glossabet-out/glossary.json` from bounded validated JSON
  on standard input;
- `drift` writes `glossabet-out/drift.json`;
- `validate` writes `glossabet-out/validation.json`;
- the agent skill, after human instruction, may write the human glossary and
  derived `GLOSSABET.md` through its host tools; and
- `sync-context` alone targets a project-owned host instruction file.

Glossabet never edits `.gitignore` and never renames application code.

### Managed host context

`sync-context` has a closed target mapping: root `AGENTS.md` for Codex or root
`CLAUDE.md` for explicit `--agent claude`. It accepts no arbitrary output path.
Existing targets must be exact-name, regular, unsymlinked, bounded UTF-8 files.
The update preserves surrounding bytes, line-ending style, and file mode.

One current deterministic block is a no-write result. One integrity-valid
stale block is replaced inside its exact markers. An edited but structurally
unambiguous block requires `--force`; missing, duplicate, nested, or malformed
markers remain an error even with force. A concurrent byte, mode, device, or
inode change detected before replacement aborts the write. Drift and validation
only inspect the two targets and report `stale`, `edited`, or `uninspectable`
state.

## Git and executable behavior

[`runtime.git_state`](glossabet/runtime/git_state.py) resolves `git` from
`PATH` without considering the repository/current directory, then invokes the
absolute executable with `shell=False`, a timeout, prompts disabled, and
repository-selection environment variables removed. Command-line overrides
disable hooks and filesystem monitors and clear configured content-filter
drivers, including drivers introduced through Git config includes. Only HEAD
and a dirty stamp are consumed. Any missing, timed-out, malformed, or unsafe
result becomes an honest unverified state rather than a command failure.

The dirty stamp excludes only the selected root's derived
`glossabet-out/` namespace and root `GLOSSABET.md`. Git-ignored files retain
Git's normal invisibility, so `dirty: false` is not a claim that every byte was
examined. A subproject scan describes that subproject path, not unrelated
changes elsewhere in the containing worktree.

Static trust ratchets in
[`tests/test_trust_ratchets.py`](tests/test_trust_ratchets.py) reject network
imports, dynamic code execution, shell-enabled process calls, unauthorized
subprocess sites, and imports of analyzed repository code. These tests are
targeted tripwires, not formal verification.

## Installation and ambient context

`glossabet install` writes the wheel-bundled canonical skill to the reported
personal or explicit directory. A different existing file is preserved unless
`--force` is explicit. Claude installation may additionally write a manifest
and SessionStart hook inside that same skill directory; `--skill-only` omits
them. Nothing in the target repository is written by installation.

The Codex plugin bundles the canonical skill, exact hook configuration,
version/digest-checking runner, and one dependency-free wheel. After a user
trusts the hook, `brief .` places bounded canonical vocabulary in developer
context at startup, resume, clear, and compaction. The Claude skills-directory
plugin is designed around the same read-only brief boundary. Read-only does
not mean private: the agent host may send that context to its configured model
provider. Review the installed hook and [`PRIVACY.md`](PRIVACY.md) before
trusting it for confidential work.

Windows plugin lifecycle and Claude ambient behavior outside the recorded
Linux evidence remain unverified. Host/version evidence is not a blanket
support promise; [`EVALUATION.md`](EVALUATION.md) states exactly what ran.

## Developer and release surfaces

The no-network claim applies to the production package, not every repository
maintenance script:

- `evaluation/run.py --fetch` may fetch only pinned public corpus revisions;
- live reviewer and agent evaluators contact their configured model service
  only behind their explicit run modes and authorization boundaries;
- dependency installation may contact the selected package index;
- plugin smoke invokes the local Codex host and may inherit host update checks;
  and
- the prepared release workflow can publish to PyPI only after its separate
  manual guards and external setup.

Workflow safety uses two independent mechanisms. PyYAML parses the files and
`scripts/check_workflows.py` enforces only Glossabet-specific matrices,
dependency chains, permissions, action pins, checkout credentials, and release
guards. actionlint 1.7.12 checks general GitHub Actions syntax, expressions,
inputs, and script-injection risks. Neither prevents an authorized maintainer
from changing both policy and workflows.

## Assumptions and known limits

- Path roles are convention/configuration based, not parser-proven provenance.
- Identifier extraction is Unicode-aware lexical approximation and can see
  identifier-like words in comments and strings.
- In-repository source symlinks are intentionally followed when their resolved
  target is safe; direct control/artifact symlinks are rejected.
- Normalized Graphify groups do not carry repository paths. Structural checks
  for path-scoped concepts therefore report partial coverage where safe
  scoping is impossible.
- A bounded `inspect` result is fresh for that command but is not an atomic
  snapshot and is not anonymized.
- The agent skill's human-approval rule is an instruction. `save` validates
  structure but cannot mechanically authenticate the human decision.
- A same-user hostile process, compromised interpreter, compromised `git`,
  compromised package installer, or malicious agent/model host is outside the
  local hostile-repository boundary.

## Reporting

Do not put vulnerability details in a public issue.

The intended private route is GitHub's **Report a vulnerability** form at
<https://github.com/kserrec/glossabet/security/advisories/new>. Private
vulnerability reporting is not yet enabled, so this project does not currently
claim a working private disclosure channel. Enabling that repository setting
and notifications is a release prerequisite in [`RELEASING.md`](RELEASING.md).
