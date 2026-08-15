# Privacy and data flow

Glossarize has two distinct operating modes: a local deterministic CLI and an
agent-mediated skill. They do not have the same data boundary. This document
states what each mode reads, writes, and may disclose.

## Local CLI

After installation, the `glossarize` CLI makes no network requests, sends no
telemetry, uses no account, and calls no language model. It processes files on
the machine where it runs.

For `scan`, `analyze`, `inspect`, `drift`, and `validate`, the CLI may read:

- ordinary source and documentation files under the selected repository;
- root `glossarize.json` and Glossarize-owned JSON artifacts when the selected
  command needs them (`GLOSSARY.md` is deliberately excluded from analysis);
- optional `graphify-out/graph.json` as repository-controlled structural
  evidence; and
- local Git commit and worktree status through a constrained `git` subprocess.

Sensitive-file exclusion is path-based. Dotenv variants, common private-key
and credential-store names, and paths containing `secret` or `credential` are
excluded without reading their contents. Glossarize does **not** scan ordinary
source or documentation text for secret-looking values. A password, token, or
personal datum embedded in an ordinarily named included file can therefore be
represented in lexical evidence. Outputs are not anonymized or sanitized.

The CLI writes derived reports and the human-governed machine glossary under
`<repository>/glossarize-out/`. It writes incremental extraction state to the
current user's platform cache directory. These files can contain repository
paths, identifiers, import strings, documentation terms, Graphify labels,
configuration paths, and human-written definitions. Handle them with the same
confidentiality as the repository. `README.md` documents exact ownership and
cleanup rules; in particular, `glossary.json` is not disposable if it contains
decisions that exist nowhere else.

`glossarize install` is separate from repository analysis. It reads the
canonical skill bundled in the installed wheel and writes one `SKILL.md` to
the reported personal or explicitly selected skill directory. It does not
contact Codex, Claude, OpenAI, Anthropic, PyPI, or GitHub. Package installation
itself may contact the package index chosen by the user's package manager.

## Agent-mediated skill

The installed skill is a Markdown instruction set. When invoked, it first runs
`glossarize inspect .` and parses that command's versioned, bounded JSON
output. It is forbidden from opening Glossarize's repository JSON artifacts or
falling back to unrestricted recursive reading. The context includes sampled
repository paths, identifiers, documentation vocabulary, Graphify labels, and
the validated optional glossary; it records both scanner and context
omissions. The agent may then read production files named by the context to
understand real components and propose names. After the human approves terms,
the agent passes the complete machine-readable glossary to `glossarize save .`
on standard input; the skill does not write the repository JSON artifact
directly.

The agent host may send the CLI context and those selected files to its model
provider or other configured tools according to that host's current privacy,
retention, training, workspace, and connector settings. Glossarize does not
operate or control those services and cannot enforce their policies.

Before invoking the skill on confidential code:

- verify that the selected agent account, workspace, model provider, and any
  enabled connectors are approved for that repository;
- treat the `glossarize inspect .` context as confidential
  repository-derived data, not as an anonymized or secret-scrubbed export; and
- remember that the local path exclusions do not remove secrets embedded in
  ordinarily named source or documentation files.

Graphify is optional and separate software. Glossarize reads its local export
when present but makes no claim about how Graphify itself was installed,
generated, or configured.

## Explicit network exceptions in this repository

The production CLI has no network path. Two developer/release activities do:

- `evaluation/run.py --fetch` invokes `git` to fetch only the public revisions
  pinned in `evaluation/corpus.json` into a temporary directory. Without
  `--fetch`, it does not retrieve them.
- Building or installing development/release dependencies can contact PyPI or
  another configured package index. The prepared publication workflow, if a
  maintainer later authorizes and runs it, uploads public release artifacts to
  PyPI through GitHub Actions.

There are no hidden analytics, crash-report uploads, update checks, or remote
feature flags in Glossarize 0.1.0.
