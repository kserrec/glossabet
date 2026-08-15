# Distribution ownership and lifecycle

Glossabet has two deliberate distribution routes. They carry the same
versioned engine and canonical skill, but they own different installed state.
The Codex plugin is the preferred Codex route once a marketplace entry is
published. The standalone Python wheel remains an atomic fallback and is the
route for people who want a normal shell command.

No Glossabet package or plugin marketplace entry is public yet. The repository
contains a locally validated plugin prototype at `plugins/glossabet/`; its
actual Codex lifecycle was probed on Linux with `codex-cli 0.147.0`. ChatGPT,
Codex on other operating systems, and Claude Code have not received an
equivalent installed-host probe and are not called supported.

| Installed state | Codex plugin route | Standalone wheel route |
| --- | --- | --- |
| Engine | A pure-Python wheel inside the plugin. The skill runs it through `scripts/run_glossabet.py`; no executable is added to `PATH`. | The package manager owns an isolated environment and the `glossabet` executable on `PATH`. |
| Skill | Codex owns the skill inside the same versioned plugin cache entry. | `glossabet install` makes a separate copy at the selected agent skill directory. |
| Version coupling | Plugin manifest, skill instructions, runner constant, nested wheel metadata, and wheel-embedded skill must all match. Tests and distribution checks fail on any mismatch. | The wheel version and wheel-embedded skill are built together. The skill checks the CLI's exact version before analysis. |
| Upgrade | Installing the same plugin identifier from a refreshed marketplace snapshot replaces the cached version. Codex 0.147.0 removed the prior version during the direct 0.1.0 → synthetic 0.1.1 probe. | Reinstall or upgrade the wheel, then run `glossabet install`. If a prior Glossabet-owned skill differs, inspect that exact file and use `--force` deliberately; the installer never assumes ownership. |
| Removal | `codex plugin remove` removes the plugin engine and skill together. Removing the local marketplace removes its configuration entry. Codex 0.147.0 left one empty marketplace cache parent, which the smoke test removes only after proving it is empty and test-owned. | Uninstalling the Python package removes its environment and command, not the separately copied skill. Inspect and remove only the reported skill directory if that copy is no longer wanted. |

Both routes leave analyzed repositories alone during package/plugin removal.
`glossabet-out/glossary.json` is human-governed project state, derived reports
share that output directory, and the platform cache is a disposable
performance optimization. Their ownership and cleanup rules are independent
from software installation.

## Codex plugin bundle

The plugin contains:

- `.codex-plugin/plugin.json`, versioned with the Python package;
- the byte-identical canonical `skill/SKILL.md`;
- `scripts/run_glossabet.py`, which verifies the manifest, expected filename,
  imported package version, and Python ≥ 3.10 before delegating to the CLI;
  and
- exactly one dependency-free `glossabet-<version>-py3-none-any.whl`.

This layout follows OpenAI's official
[plugin packaging](https://developers.openai.com/plugins/build/plugins) and
[skill supporting-resource](https://developers.openai.com/plugins/build/skills#add-supporting-resources)
contracts: the manifest exposes `./skills/`, and deterministic executable
support lives beneath that skill's `scripts/` directory.

The runner imports the wheel directly from the plugin cache. It does not
install into the user's Python environment, mutate `PATH`, contact a service,
or add a second package lifecycle outside Codex.

`scripts/build_plugin.py <dist-dir>` assembles the bundle only after checking
the source version, manifest, runner, canonical skill, wheel metadata, and
embedded skill. `tests/test_plugin.py` protects those relationships in normal
CI. `scripts/plugin_smoke.py <dist-dir>` is the host-level probe: it creates a
uniquely named temporary local marketplace, installs the current version,
executes `inspect` through the installed bundle, builds and installs a
synthetic next patch version, verifies the old cached version disappeared,
then removes the plugin, marketplace, and any exact empty cache parent it
created. It publishes nothing and leaves no marketplace entry installed.

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
uses the CLI and installed skill, uninstalls the package, and proves the
import and command are gone while the separately installed skill remains.

The Claude Code destination exposed by `glossabet install --agent claude` is
still experimental: path selection and safe copying are tested, but no Claude
Code session has been directly exercised with the installed pair.
