# Glossabet

Glossabet helps a team choose shared names for the important parts of a
codebase and keep those names consistent as the code changes.

It has two parts:

- The `glossabet` command-line program scans a repository and records facts
  about the words and structure already present.
- The Glossabet agent skill gives Codex or Claude Code a repeatable naming
  workflow. It reads fresh evidence and relevant source files, then proposes
  names for the human to discuss and decide.

The skill is instructed to save a term only after a human explicitly approves
it as canonical, meaning accepted for that project. The command-line program
can validate the saved data but cannot verify that approval happened. Review
Glossabet's files like any other agent-written change.

## Status

**Status:** Glossabet 0.1.0 is an unreleased source alpha under owner
self-testing. It is not a supported public release, and outside contributions
are paused. [`PLAN.md`](PLAN.md) records the roadmap and current gate;
[`CHANGELOG.md`](CHANGELOG.md) records the unreleased version.

## Install from source

You need Python 3.10 or newer and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/). From a
Glossabet source checkout, run:

```bash
uv tool install . --reinstall
glossabet install
glossabet --version
```

The first command installs the command-line program in an isolated environment.
The second copies the matching skill to
`~/.agents/skills/glossabet/`, a user skill location documented by
[OpenAI](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills).
The final command should print `glossabet 0.1.0`.

For Claude Code instead, run:

```bash
glossabet install --agent claude
```

That installs `~/.claude/skills/glossabet/`, a personal skill location
documented by
[Claude Code](https://code.claude.com/docs/en/skills#where-skills-live).
It also installs Glossabet's session-start hook; add `--skill-only` to omit
the hook. These default installation commands do not alter a repository you
want to analyze, and the installer refuses to replace different existing skill
files unless you add `--force`.

## Use Glossabet

Start Codex or Claude Code from the root of the repository whose vocabulary
you want to improve. Invoke the skill and state the naming goal:

> **Codex:** `$glossabet Help me establish shared names for the important
> parts of this repository.`
>
> **Claude Code:** `/glossabet Help me establish shared names for the
> important parts of this repository.`

The skill then:

1. verifies that its command-line program is the matching version;
2. scans the repository and reports any limits that made the evidence partial;
3. reads the important production files selected by that scan;
4. proposes three ranked names for each part worth discussing; and
5. waits for the human to accept, reject, or reshape the proposals.

Glossabet does not rename code. When the human explicitly approves the
vocabulary and asks to finalize it, the skill writes the glossary and its
machine-readable state.

The installed command-line program makes no network requests after
installation. The agent-mediated workflow is different: the agent host may
send repository-derived evidence and selected source files to its configured
model provider or tools. Read [`PRIVACY.md`](PRIVACY.md) before using the
skill with confidential code.

To exercise the command-line workflow on a temporary copy of the included
sample:

```bash
uv sync --locked
uv run python scripts/run_walkthrough.py
```

Success ends with `Walkthrough passed`.
[`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md) explains that sample and the
real-repository workflow.

## Files and cleanup

| Path | Meaning and lifecycle |
| --- | --- |
| `GLOSSARY.md` | The human-readable vocabulary the team approved. Review and commit it when the vocabulary should be shared. |
| `glossabet-out/glossary.json` | The machine-readable vocabulary state, including accepted and proposed terms. It is not disposable; preserve and commit it with a shared glossary. |
| `GLOSSABET.md` | A derived vocabulary-health report. It contains no canonical state and can be deleted and regenerated. |
| Other JSON files in `glossabet-out/` | Derived evidence, drift, and validation reports. They can be rebuilt by the corresponding commands. |

Glossabet never edits the target repository's `.gitignore`. Its extraction
cache lives outside the repository and can be removed with
`glossabet cache-clear`. A skill installed in a user directory and a block
explicitly written by `glossabet sync-context` are separate state; uninstalling
the Python package or clearing the cache does not remove them. Remove only the
reported Glossabet skill directory or the exact marked block when that state is
no longer wanted; preserve any surrounding project instructions.

## Command reference

| Command | Purpose |
| --- | --- |
| `scan` | Build or refresh repository evidence. |
| `analyze` | Scan and print a terminology report. |
| `inspect` | Emit fresh context for the agent skill. |
| `brief` | Emit a read-only digest of accepted vocabulary. |
| `show` | Display the current glossary. |
| `save` | Validate and save glossary data received on standard input. |
| `drift` | Compare current vocabulary with the accepted glossary. |
| `validate` | Check the glossary against repository evidence and optional structural data. |
| `sync-context` | Explicitly copy accepted vocabulary into a root `AGENTS.md` or `CLAUDE.md` block. |
| `cache-clear` | Remove Glossabet's user cache, never the repository. |
| `install` | Install the canonical agent skill. |

Run `glossabet COMMAND --help` for a command's arguments.

## Why repository vocabulary matters

In controlled studies, descriptive compound identifiers helped participants
find a semantic defect about 14% faster
([Schankin et al.](https://brains-on-code.github.io/descriptive-compound-identifier-names.pdf)),
and the median probability that two developers independently chose the same
name was only 6.9%
([Feitelson et al.](https://arxiv.org/abs/2103.07487)). These results motivate
deliberate naming; they do not prove that Glossabet improves real projects.

## Development and release verification

Create the locked development environment and run the test suite and the
static gates (Ruff and mypy, both pinned development dependencies):

```bash
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run mypy glossabet
```

The complete pre-release verification and publication procedure is in
[`RELEASING.md`](RELEASING.md).

## Documentation

- [`EVALUATION.md`](EVALUATION.md) records the evaluation method, evidence,
  results, and limitations.
- [`SECURITY.md`](SECURITY.md) defines the threat model and enforced trust
  boundaries.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) explains the implementation and its
  design constraints.
- [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) is the reproducible performance
  baseline.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) records the current contribution pause
  and the terms that will apply afterward.

## Provenance and affiliation

Glossabet is an independent open-source project by Kyle Serrecchia, released
under the [Apache License 2.0](LICENSE). It is not affiliated with, endorsed
by, or sponsored by OpenAI, Anthropic, GitHub, or Graphify Labs. Those names
identify third-party hosts or optional tools and remain their owners' marks.

Glossabet is developed with AI coding assistants under human direction and
review. Claude Code contributions are recorded in the commit history;
`PLAN.md` records ChatGPT's contribution to the initial 2026-08-14 plan.
