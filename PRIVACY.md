# Privacy and data flow

Glossabet has two distinct operating modes: a local deterministic CLI and an
agent-mediated skill. They do not have the same data boundary. This document
states what each mode reads, writes, and may disclose.

## Local CLI

After installation, the `glossabet` CLI makes no network requests, sends no
telemetry, uses no account, and calls no language model. It processes files on
the machine where it runs.

For `scan`, `analyze`, `inspect`, `drift`, and `validate`, the CLI may read:

- ordinary source and documentation files under the selected repository;
- root `glossabet.json` and Glossabet-owned JSON artifacts when the selected
  command needs them;
- an exact root `GLOSSARY.md` through a bounded safe-read path for presence,
  size/digest metadata and, during validation, lexical term-presence only; its
  words never enter repository evidence or agent context, and nested
  `GLOSSARY.md` files are ignored;
- optional `graphify-out/graph.json` as repository-controlled structural
  evidence; and
- local Git commit and worktree status through a constrained `git` subprocess.

`brief` is narrower: it reads only `glossabet-out/glossary.json` through the
same confined validator and the local Git commit/worktree stamp. It does not
scan source or documentation and does not write a repository or cache file.
Its output contains canonical terms, human-written definitions, scopes,
aliases, and state fingerprints, so it remains confidential repository data
even though it is small.

`sync-context` is a separate, explicitly invoked local write. It reads the
validated glossary and at most one selected repository-root host file:
`AGENTS.md` by default or `CLAUDE.md` with `--agent claude`. It reads no source
files, Git state, Graphify output, or network service. It persists canonical
terms, definitions, scopes, aliases, semantic/content hashes, and coverage in
one marked block. The chosen host will ordinarily load that project instruction
file in later sessions, so the block may be sent to that host's configured
model provider even when a later user prompt does not mention Glossabet. Run
the command only when that disclosure and persistent project change are
intended.

`drift` and `validate` read both fixed root host files, when present, only to
classify a managed block as absent, current, stale, edited, or uninspectable;
they do not follow a target symlink or modify either file. Normal scanning still
analyzes the surrounding human-written documentation, but removes one exactly
bounded managed block before lexical extraction so the synchronized copy does
not contaminate vocabulary evidence.

Sensitive-file exclusion is path-based. Dotenv variants, common private-key
and credential-store names, and paths containing `secret` or `credential` are
excluded without reading their contents. Glossabet does **not** scan ordinary
source or documentation text for secret-looking values. A password, token, or
personal datum embedded in an ordinarily named included file can therefore be
represented in lexical evidence. Outputs are not anonymized or sanitized.

The CLI writes derived reports and the human-governed machine glossary under
`<repository>/glossabet-out/`. It writes incremental extraction state to the
current user's platform cache directory; `glossabet cache-clear` removes that
cache (only Glossabet's own layout, never a repository) and prints what it
removed or left in place. These files can contain repository
paths, identifiers, import strings, documentation terms, Graphify labels,
configuration paths, and human-written definitions. Handle them with the same
confidentiality as the repository. `README.md` documents exact ownership and
cleanup rules; in particular, `glossary.json` is not disposable if it contains
decisions that exist nowhere else.

A synchronized `AGENTS.md`/`CLAUDE.md` block is project-owned state outside
`glossabet-out/`. Package/plugin uninstall and cache cleanup do not remove it.
Review and commit it if it should be shared; otherwise remove only the exact
marked block while preserving surrounding instructions.

`glossabet install` is separate from repository analysis. It reads the
canonical skill bundled in the installed wheel and writes one `SKILL.md` to
the reported personal or explicitly selected skill directory. It does not
contact Codex, Claude, OpenAI, Anthropic, PyPI, or GitHub. Package installation
itself may contact the package index chosen by the user's package manager.
With `--agent claude`, the installer may also write a plugin manifest and
SessionStart hook inside that same reported skill folder; `--skill-only`
suppresses those files. It writes nothing outside the selected folder.

The Codex plugin route keeps both components inside Codex's plugin cache. Its
skill-local runner verifies and imports the bundled wheel directly; it does
not install a Python package, add a command to `PATH`, or make a network
request. The plugin also declares a `SessionStart` hook. After the user trusts
that hook, Codex runs `brief .` at startup, resume, clear, and compaction and
adds its stdout to developer context. That text can therefore be sent to the
configured model provider without a user mentioning Glossabet in that
session. An absent glossary emits no text. Adding a remote marketplace could
make Codex retrieve plugin files, but the local lifecycle probes use only
temporary local marketplaces. Codex's own plugin configuration, cache, hook
trust, model transmission, and retention behavior remain part of the host,
outside Glossabet's production CLI.

## Agent-mediated skill

The installed skill is a Markdown instruction set. When invoked, it first runs
`glossabet inspect .` and parses that command's versioned, bounded JSON
output. It is forbidden from opening Glossabet's repository JSON artifacts or
falling back to unrestricted recursive reading. The context includes sampled
repository paths, identifiers, documentation vocabulary, Graphify labels, and
the validated optional glossary; it records both scanner and context
omissions. The agent may then read production files named by the context to
understand real components and propose names. The skill is instructed that,
only after the human approves terms, the agent passes the complete
machine-readable glossary to `glossabet save .` on standard input; the skill
does not write the repository JSON artifact directly, and `save` itself
validates structure but cannot verify that approval happened.

The agent host may send the CLI context and those selected files to its model
provider or other configured tools according to that host's current privacy,
retention, training, workspace, and connector settings. Glossabet does not
operate or control those services and cannot enforce their policies.
The same warning applies to `glossabet brief` output whether a user pipes or
pastes it manually or the trusted Codex plugin hook supplies it automatically.
The hook remains read-only, but read-only does not mean private from the model
provider: the canonical terms, definitions, scopes, aliases, and Git state in
the digest become session context. So that this stays visible long after
installation, the digest's first line states that it was emitted by
`glossabet brief .` and that an installed Glossabet `SessionStart` hook
injects it into agent context automatically; anyone reading a transcript can
see where the text came from.

Before invoking the skill on confidential code:

- verify that the selected agent account, workspace, model provider, and any
  enabled connectors are approved for that repository;
- treat the `glossabet inspect .` context as confidential
  repository-derived data, not as an anonymized or secret-scrubbed export; and
- remember that the local path exclusions do not remove secrets embedded in
  ordinarily named source or documentation files.

Graphify is optional and separate software. Glossabet reads its local export
when present but makes no claim about how Graphify itself was installed,
generated, or configured.

## Explicit network exceptions in this repository

The production CLI has no network path. Several developer/release activities
can use one:

- `evaluation/run.py --fetch` invokes `git` to fetch only the public revisions
  pinned in `evaluation/corpus.json` into a temporary directory. Without
  `--fetch`, it does not retrieve them.
- Building or installing development/release dependencies can contact PyPI or
  another configured package index. The prepared publication workflow, if a
  maintainer later authorizes and runs it, uploads public release artifacts to
  PyPI through GitHub Actions.
- `scripts/plugin_smoke.py` invokes the locally installed `codex` executable,
  creates a temporary local marketplace and versioned plugin cache, then
  removes that exact test-owned state. It does not publish or contact a plugin
  directory; the host may still perform its own update checks under its normal
  configuration.
- An explicitly authorized `scripts/agent_eval.py --run` invokes the locally
  authenticated Codex host on generated temporary scenarios, creates a unique
  local marketplace/plugin cache entry, and removes that exact state. Codex may
  contact its configured model service under the account's policy. Its three
  host turns cover fresh-session hook delivery, the plugin skill scenarios,
  and the isolated missing-CLI boundary. The harness uses a one-invocation
  hook-trust bypass only for the exact checked temporary plugin. Each run
  writes a unique bounded raw result, mirrors only digest-retained bytes as the
  current result, and appends its outcome; the
  `--refresh-artifact` and `--verify-results` modes are local-only and do not
  invoke Codex or the network.
- An explicitly authorized `scripts/claude_eval.py --run` invokes the existing
  normal-profile Claude Code authentication for exactly three tool-disabled
  scenarios. It neither reads nor changes authentication files, disables
  session persistence, confines fixtures to one named temporary directory,
  records bounded raw events and reported usage, and removes only its own
  temporary state. Verification/history modes are local-only. The recorded
  attempt stopped before model use; any new run still requires separate
  account/cost authorization.
- `evaluation/review.py --run-reviewer` invokes one authenticated, ephemeral,
  read-only Codex review over a blinded bounded packet. Its verification mode
  is local-only.

There are no hidden analytics, crash-report uploads, update checks, or remote
feature flags in Glossabet 0.1.0.
