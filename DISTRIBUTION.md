# Distribution ownership and lifecycle

Glossabet has two deliberate distribution routes. They carry the same
versioned engine and canonical skill, but they own different installed state.
The Codex plugin is the preferred Codex route once a marketplace entry is
published. The standalone Python wheel remains an atomic fallback and is the
route for people who want a normal shell command.

No Glossabet package or plugin marketplace entry is public yet. The repository
contains a locally validated plugin prototype at `plugins/glossabet/`; its
actual Codex lifecycle and 12-scenario installed-host batch—including fresh
session-start context, 10 plugin-skill scenarios, and the standalone
missing-CLI boundary—were probed twice on Linux with `codex-cli 0.147.0`.
ChatGPT, Codex on other operating systems, and Claude Code have not received an
equivalent installed-host probe and are not called supported.

| Installed state | Codex plugin route | Standalone wheel route |
| --- | --- | --- |
| Engine | A pure-Python wheel inside the plugin. The skill runs it through `scripts/run_glossabet.py`; no executable is added to `PATH`. | The package manager owns an isolated environment and the `glossabet` executable on `PATH`. |
| Skill | Codex owns the skill inside the same versioned plugin cache entry. | `glossabet install` makes a separate copy at the selected agent skill directory. |
| Ambient context | After the user trusts the plugin hook, Codex runs the bundled `brief .` command at session startup, resume, clear, and compaction. Canonical glossary text becomes developer context; no glossary means no added text. | **Claude Code:** `glossabet install --agent claude` also writes `.claude-plugin/plugin.json` and `hooks/hooks.json` beside the skill, so Claude Code loads the folder as the plugin `glossabet@skills-dir` and runs `<installed glossabet> brief .` at session startup, resume, clear, and compaction; no glossary means no added text; nothing outside the skill folder is written. Validated offline with `claude plugin validate`; not yet probed in a live Claude Code session (PLAN Phase 33.2). **Codex standalone:** no automatic host integration. Either host: run `glossabet brief .` and deliberately supply its output, or explicitly run `glossabet sync-context .` to persist one managed block in root `AGENTS.md` (`--agent claude` selects root `CLAUDE.md`). |
| Version coupling | Plugin manifest, skill instructions, runner constant, nested wheel metadata, and wheel-embedded skill must all match. Tests and distribution checks fail on any mismatch. | The wheel version and wheel-embedded skill are built together. The skill checks the CLI's exact version before analysis. |
| Upgrade | Installing the same plugin identifier from a refreshed marketplace snapshot replaces the cached version. Codex 0.147.0 removed the prior version during the direct 0.1.0 → synthetic 0.1.1 probe. | Reinstall or upgrade the wheel, then run `glossabet install`. If a prior Glossabet-owned skill differs, inspect that exact file and use `--force` deliberately; the installer never assumes ownership. |
| Removal | `codex plugin remove` removes the plugin engine and skill together. Removing the local marketplace removes its configuration entry. Codex 0.147.0 left one empty marketplace cache parent, which the smoke test removes only after proving it is empty and test-owned. | Uninstalling the Python package removes its environment and command, not the separately copied skill or a project-owned synchronized block. Inspect and remove only the reported skill directory and/or exact marked project block if no longer wanted. |

Both routes leave analyzed repositories alone during package/plugin removal.
`glossabet-out/glossary.json` is human-governed project state, derived reports
share that output directory, root `GLOSSABET.md` is a derived vocabulary-health
report the skill can regenerate, and the platform cache is a disposable
performance optimization. Their ownership and cleanup rules are independent
from software installation.

## Codex plugin bundle

The plugin contains:

- `.codex-plugin/plugin.json`, versioned with the Python package;
- `hooks/hooks.json`, whose `SessionStart` handler invokes the bundled bounded
  `brief .` command on startup, resume, clear, and compaction;
- the byte-identical canonical `skill/SKILL.md`;
- `scripts/run_glossabet.py`, which verifies the manifest, expected filename,
  imported package version, and Python ≥ 3.10 before delegating to the CLI;
  and
- exactly one dependency-free `glossabet-<version>-py3-none-any.whl`.

This layout follows OpenAI's official
[plugin packaging](https://developers.openai.com/plugins/build/plugins) and
[skill supporting-resource](https://developers.openai.com/plugins/build/skills#add-supporting-resources)
contracts, plus the official [Codex hooks contract](https://learn.chatgpt.com/docs/hooks):
the manifest exposes `./skills/` and the hook configuration, and deterministic
executable support lives beneath that skill's `scripts/` directory. Codex
treats plain hook stdout as additional developer context and requires the user
to trust plugin hooks before they execute. Review the installed hook before
granting that trust; Glossabet's hook sends the bounded canonical glossary
digest into the same model context as the session.

The runner imports the wheel directly from the plugin cache. It does not
install into the user's Python environment, mutate `PATH`, contact a service,
or add a second package lifecycle outside Codex.

`scripts/build_plugin.py <dist-dir>` assembles the bundle only after checking
the source version, manifest, exact hook configuration, runner, canonical
skill, wheel metadata, and embedded skill. `tests/test_plugin.py` protects
those relationships in normal CI. `scripts/plugin_smoke.py <dist-dir>` is the
host-level probe: it creates a uniquely named temporary local marketplace,
installs the current version, executes `inspect` and the configured
`SessionStart` command through the installed bundle, proves that command emits
only canonical glossary state without writing the repository, then installs a
synthetic next patch version, verifies the old cached version disappeared,
then removes the plugin, marketplace, and any exact empty cache parent it
created. It publishes nothing and leaves no marketplace entry installed.

An explicitly authorized `scripts/agent_eval.py --run` separately observes the
user-facing delivery boundary. It asks Codex to read the exact temporarily
installed skill and version-check the matching bundled engine. One fresh
ephemeral session uses a user prompt that names neither Glossabet nor the
expected term and must reproduce the canonical term from hook context without
running any tool. A second exercises current/stale/absent Graphify state,
hostile glossaries, partial context, monorepo scope, resumed state, and excluded
sensitive content. A third installs only the standalone skill in a temporary
repository and checks that a missing `glossabet` command stops before
inspection. The harness permits only `inspect`'s normal evidence refresh,
rejects every other repository write, and removes/re-queries its uniquely named
plugin and marketplace state in all outcomes. It uses Codex's one-invocation
hook-trust bypass only for the exact digest-bound temporary plugin. Each full
run has a unique immutable raw path; `evaluation/agent-results.json` mirrors
only bytes whose digest is retained by the append-only attempt history.
Outcomes are appended even when preflight aborts, so procedural agent misses
remain visible instead of being replaced by a later green run.

The offline verifier separately hashes and directly smokes the current skill,
plugin tree, runner, and wheel, and treats every recorded canary, write,
post-failure-inspect, and cleanup outcome as a hard safety gate. The observed
agent attempts are host/version reliability evidence, not a support claim for
untested Codex hosts or a substitute for deterministic artifact checks.

## Standalone wheel fallback

From a source checkout, the current fallback is:

```bash
uv tool install . --reinstall
glossabet install
```

The first command owns the Python environment and `glossabet` executable. The
second command writes only the canonical `SKILL.md` at the reported Codex
location (or the explicit destination). The isolated wheel smoke creates a
fresh virtual environment, installs the wheel without an index or dependency,
uses the CLI and installed skill, exercises an idempotent `sync-context` plus
drift inspection against a temporary repository, uninstalls the package, and
proves the import and command are gone while the separately installed skill
and project block remain.

`glossabet install` never invokes `sync-context`. The latter is a separate
human-authorized project write. It refuses target symlinks, non-files,
oversized/non-UTF-8 files, and ambiguous markers; it preserves surrounding
bytes and requires `--force` to replace an integrity-mismatched but
structurally valid managed body.

The Claude Code destination exposed by `glossabet install --agent claude` is
tested offline — path selection, safe copying, exact manifest and hook bytes,
refusal to replace a different existing file without `--force`, no writes
outside the skill folder, and `claude plugin validate` acceptance — and the
written hook is executed against a fixture repository in the test suite. No
live Claude Code session has yet been exercised with the installed folder;
that evidence is PLAN Phase 33.2, and until then the route is labelled
unverified rather than supported.
