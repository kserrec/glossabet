# Privacy and data flow

Glossarize has two distinct operating modes: a local deterministic CLI and an
agent-mediated skill. They do not have the same data boundary. This document
states what each mode reads, writes, and may disclose.

## Local CLI

After installation, the `glossarize` CLI makes no network requests, sends no
telemetry, uses no account, and calls no language model. It processes files on
the machine where it runs.

For `scan`, `analyze`, `drift`, and `validate`, the CLI may read:

- ordinary source and documentation files under the selected repository;
- root `glossarize.json`, `GLOSSARY.md`, and Glossarize-owned JSON artifacts
  when the selected command needs them;
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

The installed skill is a Markdown instruction set. When invoked, an agent may
read Glossarize artifacts and repository files in order to understand real
components and propose names. The agent host may send that content to its
model provider or other configured tools according to that host's current
privacy, retention, training, workspace, and connector settings. Glossarize
does not operate or control those services and cannot enforce their policies.

Before invoking the skill on confidential code:

- verify that the selected agent account, workspace, model provider, and any
  enabled connectors are approved for that repository;
- inspect `glossarize-out/evidence.json` as confidential repository-derived
  data, not as a sanitized export; and
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
