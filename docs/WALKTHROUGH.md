# End-to-end walkthrough

This walkthrough lets a new user exercise Glossarize without knowing the
project's internals and without modifying the checked-in sample. The sample is
an original, minimal payment service with vocabulary that has already been
settled by a human. That makes the machine-side result reproducible; it is not
an example of Glossarize choosing canonical names on its own.

## Run the reproducible sample

From a Glossarize source checkout with Python 3.10 or newer and
[uv](https://docs.astral.sh/uv/) installed:

```bash
uv sync --locked
uv run python scripts/run_walkthrough.py
```

The script copies `examples/payment-service` into a temporary directory, puts
its extraction cache there too, and runs these installed-package entry points:

```text
glossarize analyze <temporary-sample>
glossarize show <temporary-sample>
glossarize drift <temporary-sample>
glossarize validate <temporary-sample>
```

Success ends with `Walkthrough passed`. The run proves that evidence can be
built, a settled glossary can be read, drift can be checked, lexical
reconciliation can complete without Graphify, and all temporary files can be
removed. The expected sample result is zero drift and zero validation
findings; structural sections say they were skipped because the sample has no
Graphify graph.

## Install the agent skill

The wheel contains the exact canonical `skill/SKILL.md`. Install it for Codex
at the current official personal-skill location (`~/.agents/skills`) with:

```bash
glossarize install
```

Install it for Claude Code at `~/.claude/skills` with:

```bash
glossarize install --agent claude
```

Use `--destination DIR` to write `SKILL.md` into a different explicit
directory. Installation is idempotent. If a different `SKILL.md` already
exists, Glossarize preserves it and exits with a user error; `--force`
replaces only that file and should be used only when replacement is intended.
Symlinked destination components are refused.

The locations above follow the current
[OpenAI Codex skill documentation](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)
and [Claude Code skill documentation](https://code.claude.com/docs/en/skills#where-skills-live).

## Use it on a real repository

The actual human/agent workflow starts with deterministic evidence:

```bash
glossarize scan /path/to/repository
```

Then invoke `$glossarize` in Codex or `/glossarize` in Claude Code. The skill
checks whether the evidence is fresh, reads the repository's important files,
and opens a ranked naming brainstorm. Discuss and settle terms with the agent;
only an explicit human decision makes a term canonical. When asked to
finalize, the skill writes `GLOSSARY.md` and
`glossarize-out/glossary.json`. Thereafter, run `glossarize drift` and
`glossarize validate` as the code evolves.

Before analyzing confidential code or using an agent host, read
[`PRIVACY.md`](../PRIVACY.md). The local CLI and the agent-mediated workflow
have materially different data boundaries.
