# Distribution ownership and lifecycle

Glossabet has two distribution routes built from the same versioned engine and
canonical skill. Neither a package nor a public plugin listing has been
published for 0.1.0.

OpenAI's current plugin architecture allows a plugin to package skills and
optional server/UI capabilities; Glossabet uses the smallest relevant shape:
one skill, a SessionStart hook, and a self-contained local engine. See the
official [plugin architecture](https://developers.openai.com/plugins/concepts/plugins)
and [packaging guide](https://developers.openai.com/plugins/build/plugins).

## Ownership at a glance

| State | Codex plugin route | Standalone wheel route |
| --- | --- | --- |
| Engine | One pure-Python wheel inside the plugin cache. The skill-local runner imports it directly; nothing is added to `PATH`. | The package manager owns an isolated environment and the `glossabet` command on `PATH`. |
| Skill | Lives inside the same versioned plugin cache entry. | `glossabet install` copies the wheel-bundled skill to the selected host directory. |
| Ambient context | After the user trusts the plugin hook, the bundled `brief .` runs at startup, resume, clear, and compaction. No structured glossary means no emitted context. | Codex has no automatic standalone integration. Claude installation can make its personal skill folder a skills-directory plugin with the same brief hook; `--skill-only` omits it. Either host can use manual `brief` output or explicit `sync-context`. |
| Upgrade | A refreshed plugin version replaces the cache entry as one unit. | Upgrade/reinstall the wheel, then rerun `glossabet install`; differing copied files require deliberate `--force`. |
| Removal | Removing the plugin removes its engine and skill together. A separately configured marketplace remains separately owned. | Package uninstall removes the command, not the copied skill, platform cache, structured project glossary, or a synchronized project block. |

Analyzed repository state has its own lifecycle. In particular,
`glossabet-out/glossary.json` is human-governed machine state and may contain
decisions that exist nowhere else. Package/plugin removal and cache clearing do
not remove it. Root `GLOSSABET.md` and the other JSON reports are derived;
`GLOSSARY.md` is maintainer-owned human vocabulary. See the ownership table in
[`README.md`](README.md).

## Codex plugin bundle

[`plugins/glossabet/`](plugins/glossabet/) contains:

- `.codex-plugin/plugin.json`, versioned with the Python package;
- `hooks/hooks.json`, whose `SessionStart` handler invokes the bounded
  skill-local `brief .` command;
- the byte-identical canonical [`skill/SKILL.md`](skill/SKILL.md);
- `scripts/run_glossabet.py`, which checks Python, manifest version, expected
  wheel name/digest, imported package version, and skill parity; and
- exactly one `glossabet-<version>-py3-none-any.whl` with no runtime
  dependencies.

The runner adds only that verified wheel to its import path. It does not install
the package, mutate the user's normal Python environment or `PATH`, or make a
network request.

`scripts/build_plugin.py <dist-dir>` verifies the source version, manifest,
hook, runner, canonical skill, wheel metadata, and embedded skill before
assembling the bundle and pinning its wheel digest. The checked-in plugin is a
generated release artifact: ordinary development may leave it honestly
lagging, but a release candidate must rebuild it and require a clean
`git diff --exit-code -- plugins/glossabet`.

`scripts/plugin_smoke.py <dist-dir>` performs a local host lifecycle in unique
temporary state. It installs the current plugin from a local marketplace,
executes `inspect` and the configured SessionStart command, proves that the
hook emits canonical rather than proposed/source-canary vocabulary without a
repository write, installs a synthetic next patch version, verifies replacement
of the old cache entry, and removes the exact plugin/marketplace/test-owned
empty cache state. It does not publish or leave a marketplace installed.

The recorded installed-agent result adds fourteen user-facing cases and binds
their raw outcome to an append-only history. It passed on Codex CLI 0.147.0 and
Linux, including a fresh hook-only session and an isolated missing-CLI stop.
That is evidence for one host/version/operating system, not a support promise
for every Codex release or platform. Details and limitations are in
[`EVALUATION.md`](EVALUATION.md).

## Standalone wheel

From a source checkout:

```bash
uv tool install . --reinstall
glossabet install
```

The first command installs the application in the package manager's isolated
environment. The second writes only `SKILL.md` to the reported Codex personal
skill directory or explicit `--destination`. It never runs `sync-context` and
never changes the repository being analyzed.

The wheel smoke creates a fresh virtual environment, installs with
`--no-deps --no-index`, exercises version, skill install, `save`, `inspect`,
`brief`, idempotent managed-context synchronization, drift/validation, and
uninstall, then proves the package import and executable disappeared while the
separately copied skill and project block remained. This makes ownership
visible rather than silently deleting state another lifecycle owns.

If a copied skill differs during upgrade, inspect that file and use `--force`
only when replacing it is intended. The installer rejects destination symlink
components and writes atomically.

## Claude Code personal route

```bash
glossabet install --agent claude
```

The default destination is `~/.claude/skills/glossabet/`. Current Claude Code
documentation describes personal skills under `~/.claude/skills/` and says a
skill folder containing `.claude-plugin/plugin.json` loads automatically as a
`<name>@skills-dir` plugin. Glossabet writes that manifest and
`hooks/hooks.json` beside its root `SKILL.md`, all inside the one reported
folder. Official references: [Claude skills](https://code.claude.com/docs/en/slash-commands)
and [plugins](https://code.claude.com/docs/en/plugins).

Claude Code documents `SessionStart` for startup, resume, clear, and compact,
with command stdout added to context. Glossabet's hook runs the absolute
installed `glossabet brief .` executable and writes no repository file. Review
the hook and its model-disclosure consequence before use. Add `--skill-only`
when ambient loading is not wanted.

Offline tests prove path selection, exact bytes, no write outside the skill
folder, refusal to replace different files without `--force`, hook execution,
and `claude plugin validate` acceptance. A manual Claude Code 2.1.235/Linux
owner session provided partial evidence that the context and skill loaded. The
controlled automated batch stopped before SessionStart/model use on a now-fixed
response-schema incompatibility, so the route does not yet have accepted
controlled live-host evidence. Other versions and operating systems are
unverified.

## Ambient and persistent context

Both plugin hooks call `brief`, which reads only the validated structured
glossary and a hardened Git stamp and emits at most 4 KiB. Its first line names
Glossabet and the SessionStart origin. The text contains repository vocabulary
and can be sent to the configured model provider even when the user prompt does
not mention Glossabet. No glossary emits no text.

`glossabet sync-context .` is an independent fallback and explicit project
write. It targets only root `AGENTS.md`, or root `CLAUDE.md` with
`--agent claude`, preserves surrounding bytes, rejects unsafe/ambiguous files,
and requires `--force` only for an edited but structurally valid owned block.
Installation, hooks, analysis, and glossary finalization never invoke it.

Uninstalling software does not remove synchronized project context. To clean
up, inspect the target and remove only the exact marked Glossabet block while
preserving all surrounding instructions.
