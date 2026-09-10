# Glossabet

Glossabet helps you agree on what to call the parts of your codebase. It works
through Codex or Claude Code: the agent reads your project, suggests names,
and talks them through with you. You save the names you choose in the project,
then come back when the code changes or something new needs a name.

The installation has two pieces: a local program that scans files and stores
your decisions, and an agent skill that tells Codex or Claude Code how to run
the naming conversation.

## Status

Glossabet 0.1.0 is in beta. You're welcome to try it on your projects and share
what works, what doesn't, and what could be clearer. The [plan](PLAN.md) tracks
what's next, and the [changelog](CHANGELOG.md) records what's changed. The
instructions below walk you through installing it from source.

## 1. Install it

You need Git, Python 3.10 or newer,
[`uv`](https://docs.astral.sh/uv/getting-started/installation/) (a tool for
installing Python programs), and a working Codex or Claude Code setup.

Clone Glossabet and install its command-line program:

```bash
git clone https://github.com/kserrec/glossabet.git
cd glossabet
uv tool install . --reinstall
glossabet --version
```

The version command should print `glossabet 0.1.0`. If you've already cloned
this repository, start with `uv tool install . --reinstall` from its root.

Then install the skill for the agent you use.

**Codex:**

```bash
glossabet install
```

**Claude Code:**

```bash
glossabet install --agent claude
```

The Claude installation also adds a startup command that loads saved project
names into ordinary sessions. Add `--skill-only` to install just the naming
skill. Step 4 explains how the startup command works.

The skill goes in `~/.agents/skills/glossabet/` for Codex or
`~/.claude/skills/glossabet/` for Claude Code. Install it once for your user
account, then use it across projects. This doesn't change those projects.
If the installer finds different existing skill files, it keeps them and
stops. Use `--force` only when you mean to replace them.

## 2. Start a naming conversation in your project

Now switch to your own project's root folder and start a new Codex or Claude
Code session there. This is the project whose parts you'll be naming.

Type one of these into the agent conversation:

**Codex:**

> $glossabet Help me establish shared names for the important parts of this repository.

**Claude Code:**

> /glossabet Help me establish shared names for the important parts of this repository.

The agent checks its Glossabet version, scans your project, and reads the
relevant code. It suggests three names for each part worth discussing, with
its favorite first. It should tell you about any gaps in the scan. You don't
need to run one yourself.

The `glossabet` program makes no network requests after installation. Your
coding agent may send scan results and source files to its model provider.
Read [Privacy](PRIVACY.md) before using it with confidential code.

## 3. Choose names and save them

Discuss the suggestions as you would with a teammate. Keep the names you like,
reject the ones you don't, or supply your own. For example:

> Use Dispatch for the component that assigns jobs to workers. Keep Queue for
> the waiting jobs. Give me more options for the retry component.

You can leave some names undecided. When you're ready to save, say so:

> Finalize Dispatch and Queue as agreed. Save the glossary, and keep the retry
> component as an open question.

The skill is instructed to save a name as **canonical** (accepted for this
project) only after you approve it. The save command checks the data, but
can't verify your approval. Review what the agent writes:

| File in your project | What it's for |
| --- | --- |
| `GLOSSARY.md` | The names you agreed on, what they mean, and why you chose them. |
| `glossabet-out/glossary.json` | Glossabet's memory for later sessions: accepted names, open proposals, alternate names, and recorded connections to code. |
| `GLOSSABET.md` | A report of naming problems, proposed changes, and open questions. It can be regenerated. |

**Commit both `GLOSSARY.md` and `glossabet-out/glossary.json`.** That JSON file
holds decisions you'll need next time, even though its folder is called
“out.” Check that `.gitignore` allows it; Glossabet won't edit that file for
you. Commit `GLOSSABET.md` if you want to share the open questions and findings.

If you already have a `GLOSSARY.md`, the skill is instructed to check it
against the code and edit only what you agree to change.

Choosing names doesn't rename your code. If you want identifiers, comments,
or other docs updated to match, ask for that as a separate change.

## 4. Use the names during normal work

Use the agreed names in issues, reviews, and ordinary coding requests:
“Add a timeout to Dispatch.” You don't need a Glossabet conversation for every
task. Here's how to make the names available in new agent sessions.

### If you use Codex

From your project's root, run:

```bash
glossabet sync-context .
```

For the source installation above, this puts a short vocabulary summary in
`AGENTS.md`, the project instruction file Codex reads. It creates the file if
needed and preserves text outside its marked Glossabet section. Review and
commit the change.

**Run it again when the glossary changes.** The summary is a saved copy.
Installing the skill and saving names don't update it automatically.

### If you use Claude Code

The default installation includes a startup command, called a hook. With the
hook enabled, Claude Code runs `glossabet brief .` to load a short summary of
your accepted names at the start of a session. With no saved glossary, it
adds nothing.

If you're not using the hook, save the summary in `CLAUDE.md` instead:

```bash
glossabet sync-context . --agent claude
```

Review and commit the change. Run the command again whenever the glossary
changes.

### Other ways to load the names

For either agent, ask it to run `glossabet brief .` to use the saved names in
just the current session, without changing an instruction file. Glossabet
also has a Codex plugin bundle with a startup hook, but no public listing yet.
See [Distribution](DISTRIBUTION.md) for that route and the versions tested.

These are short summaries and report when names have been left out. Loading
one doesn't check the code for changes or enforce naming. It can send project
vocabulary to your model provider during ordinary work, even when you haven't
invoked Glossabet.

## 5. Come back when the project changes

Come back when you add a component, change its job, or notice two people
using different names for the same thing. Ask your agent:

> Run glossabet drift . and glossabet validate . and explain what needs a look.

Or run the checks yourself from your project's root:

```bash
glossabet drift .
glossabet validate .
```

`drift` looks for changes in how the code uses your names, including old
names that still turn up. `validate` also checks the glossary against the
code and any connections you've recorded between names and implementations.
Both scan and write JSON reports in `glossabet-out/`. They leave the names
and code alone; you decide what to do about the findings.

To save the findings for people to read, ask the agent to refresh `GLOSSABET.md`.

To discuss new names, invoke the skill again. For example, in Codex:

> $glossabet We added a scheduler. Review it against our glossary and help me
> name the new parts. Keep our settled names unless there's a conflict.

Use `/glossabet` in Claude Code. The skill is instructed to pick up where you
left off. Settled names stay settled unless you ask to revisit them or a
conflict comes up. Open proposals and new parts are the next things to discuss.

Discuss the changes, ask to finalize the ones you accept, and review and commit
the updated glossary files. If you used `sync-context`, run it again and
include the updated instruction file. A session-start hook reads the latest
saved glossary the next time it runs.

## Working with other people

Teammates get the saved vocabulary when they clone or pull your project.
Anyone can read `GLOSSARY.md` and use the names. To run checks or naming
sessions, they also install Glossabet and their agent's skill. Each person
using a startup hook needs that integration installed and enabled.

## Try the included example

From the Glossabet checkout, run:

```bash
uv sync --locked
uv run python scripts/run_walkthrough.py
```

This checks a temporary copy of the included payment-service example and ends
with `Walkthrough passed`. It exercises the local commands, without an agent
conversation. [Walkthrough](docs/WALKTHROUGH.md) explains the sample.

## Files and cleanup

The scan cache lives outside your project; `glossabet cache-clear` removes
recognized Glossabet cache data. The generated JSON reports in
`glossabet-out/` can be rebuilt. Keep `glossary.json` and `GLOSSARY.md`.

Uninstalling the program leaves the cache, copied skill, and project files in
place. To remove the integration too, remove its reported skill directory and
only the marked Glossabet section in `AGENTS.md` or `CLAUDE.md`. Preserve the
surrounding instructions. See [Distribution](DISTRIBUTION.md) for upgrades
and removal.

## Command reference

| Command | Purpose |
| --- | --- |
| `scan` | Scan the repository and save the evidence. |
| `analyze` | Scan and print a terminology report. |
| `inspect` | Scan and give the agent fresh context for a naming session. |
| `brief` | Print accepted names without scanning or writing files. |
| `show` | Display the saved glossary. |
| `save` | Check and save glossary JSON received on standard input; the skill handles this when you finalize. |
| `drift` | Compare current vocabulary with the accepted glossary. |
| `validate` | Check the glossary against repository evidence and optional structural data. |
| `sync-context` | Copy accepted vocabulary into `AGENTS.md` or `CLAUDE.md`. |
| `cache-clear` | Remove Glossabet's recognized cache; leave mixed or unreadable folders alone. |
| `install` | Install the agent skill. |

Add `--help` for a command's arguments, for example `glossabet drift --help`.
Commands that take a repository path use the current folder if you omit it.

## Development and release verification

From the Glossabet checkout, install the development tools and run the checks:

```bash
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked mypy glossabet
uv run --locked python scripts/check_workflows.py
```

If you change a GitHub Actions workflow, also check it with actionlint
1.7.12. With Go installed, run these from the Glossabet checkout:

```bash
go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12
actionlint
```

The complete pre-release verification and publication procedure is in
[`RELEASING.md`](RELEASING.md).

## Documentation

| Topic | Where to read |
| --- | --- |
| Trying the sample | [Walkthrough](docs/WALKTHROUGH.md) |
| Code organization | [Architecture](ARCHITECTURE.md) |
| Following the code | [Code walkthrough](docs/CODE-WALKTHROUGH.md) |
| Saved formats and compatibility | [Compatibility](COMPATIBILITY.md) |
| Security claims and limits | [Security](SECURITY.md) |
| Where your data goes | [Privacy](PRIVACY.md) |
| Evaluation results and evidence | [Evaluation](EVALUATION.md) and [evaluation files](evaluation/README.md) |
| Performance measurements | [Performance](docs/PERFORMANCE.md) |
| Packages and releases | [Distribution](DISTRIBUTION.md) and [Releasing](RELEASING.md) |
| Plans and contribution status | [Plan](PLAN.md) and [Contributing](CONTRIBUTING.md) |
| Earlier development records | [History](https://github.com/kserrec/glossabet/tree/main/docs/history), kept in Git but excluded from source distributions |

## Provenance and affiliation

Glossabet is an independent open-source project licensed under the
[Apache License 2.0](LICENSE). It is not affiliated with, endorsed
by, or sponsored by OpenAI, Anthropic, GitHub, or Graphify Labs. Those names
identify third-party hosts or optional tools and remain their owners' marks.

Glossabet is developed with AI coding assistants under human direction and
review. Claude Code contributions are recorded in the commit history;
the repository-only [historical plan](https://github.com/kserrec/glossabet/blob/main/docs/history/PLAN-THROUGH-2026-08-22.md) records
ChatGPT's contribution to the initial 2026-08-14 product plan.
