# Release preparation and publication

Glossabet 0.1.0 is locally packageable and its current local verification
gates pass, but it is **not release-ready and is not published to PyPI**. The
installed-agent and controlled structural evaluation is complete. Kyle has
paused before outside trusted-alpha evidence while he runs the current build
and performs additional checks himself; the exact-artifact Phase 23 gate comes
after that outside evidence. Phase 21 records the Glossabet decision and a
working local Codex plugin lifecycle in `NAME-CLEARANCE.md` and
`DISTRIBUTION.md`. The source repository remains public and was renamed with
explicit authorization to <https://github.com/kserrec/glossabet>; its
configured remote now matches. With separate explicit authorization, package
metadata and distribution assertions now use that renamed URL, the embedded
plugin wheel was rebuilt, and its installed-agent evidence was regenerated.
Only the wheel's `METADATA` and `RECORD` entries changed; its executable
package entries remained byte-identical. Kyle's owner self-testing pause
remains active. As reverified on 2026-08-15, PyPI's `glossabet` JSON endpoint
returns 404. That does not reserve the name and must be checked again
immediately before publication.

No PyPI account, pending publisher, GitHub `pypi` environment, Git tag, GitHub
Release, package upload, or private vulnerability-reporting setting was
created or changed while preparing this release. The separately authorized
GitHub repository rename is complete. The remaining actions use Kyle's
accounts and create public or security-sensitive external state, so they
require his explicit authorization.

## What is already prepared

- `pyproject.toml` carries version 0.1.0, Python/platform classifiers, SPDX
  licensing, project links, and an exact wheel mapping for the canonical
  skill.
- `plugins/glossabet/` carries the same canonical skill plus the matching
  dependency-free wheel behind a version-checking skill-local runner. The
  local Codex 0.147.0 Linux probe installed 0.1.0, updated to a synthetic
  0.1.1, exercised `inspect`, and removed its plugin and marketplace state.
- The Phase 22 installed-agent harness passed 11/11 bounded scenarios through
  Codex CLI 0.147.0 on Linux, including hostile direct inputs, truncation,
  monorepo/resume behavior, excluded sensitive content, and missing CLI. The
  refreshed current wheel also passed all 11 scenarios on its first complete
  batch, and the temporary plugin state was removed. The deterministic
  seven-case evaluation and a separate blinded Codex reviewer also pass their
  recorded thresholds; this remains local/controlled evidence, not outside
  adopter validation.
- `.github/workflows/quality.yml` is the one reusable gate: it runs the
  complete suite on CPython 3.10–3.14 on Linux, macOS, and Windows, verifies
  workflow policy plus deterministic, installed-agent, and second-reviewer
  evidence provenance, then builds and smoke-tests both distributions.
  Ordinary CI and publication both call this same workflow.
- `.github/workflows/release.yml` is manual-only. Its publish job requires the
  reusable quality gate and can run only from a `v*` tag with the exact text
  `publish-glossabet-to-pypi`, and it expects a protected GitHub environment
  named `pypi` plus PyPI Trusted Publishing. It stores no long-lived PyPI
  token.
- `SECURITY.md` is the public policy file and already points to the future
  private-report form. GitHub private vulnerability reporting is currently
  disabled, so the form will not work until the repository setting is enabled.

## Dependency boundary and cost

The application wheel declares zero runtime dependencies. Hatchling is a
build-backend dependency only and is constrained to the reviewed
`>=1.32,<1.33` line. The 1.32.0 universal wheel is 78,435 bytes and declares
five unconditional direct dependencies (`packaging`, `pathspec`, `pluggy`,
`tomlkit`, and `trove-classifiers`) plus `tomli` on Python 3.10; the current
resolved releases add no deeper mandatory packages. PyPI listed no known
vulnerabilities for Hatchling 1.32.0 on 2026-08-14. This is a point-in-time
alerts snapshot, not a security guarantee.

Pytest 9.1.1 remains the sole locked development dependency because it runs
the concrete regression suite across the supported matrix. Its
386,536-byte wheel brings `iniconfig`, `packaging`, `pluggy`, and `pygments`,
plus platform/version-conditional `colorama`, `exceptiongroup` with
`typing-extensions`, and `tomli`. Neither build nor development packages are
declared in the published wheel's `Requires-Dist` metadata.

## Local release gate

Run these commands from a clean checkout. They build into a fresh temporary
directory rather than trusting stale artifacts in `dist/`:

```bash
release_dir="$(mktemp -d)"
uv sync --locked
uv run pytest -q
uv run python scripts/check_workflows.py
uv run python evaluation/run.py --verify-results evaluation/results.json
uv run python scripts/agent_eval.py --verify-results evaluation/agent-results.json
uv run python evaluation/review.py --verify-results evaluation/reviewer-results.json
uv build --no-sources --out-dir "$release_dir"
uv run python scripts/build_plugin.py "$release_dir"
git diff --exit-code -- plugins/glossabet
uv run python scripts/check_distribution.py "$release_dir" --tag v0.1.0
uv run python scripts/wheel_smoke.py "$release_dir"
uv run python scripts/plugin_smoke.py "$release_dir"
```

Before a real release, replace `Unreleased` beside `0.1.0` in `CHANGELOG.md`
with the publication date, commit that change, and rerun the gate from the
exact commit to be tagged.

## Hosted repository identity — completed

On 2026-08-15, with Kyle's explicit authorization, the public GitHub
repository was renamed to `kserrec/glossabet`, the configured Git remote was
updated to `git@github.com:kserrec/glossabet.git`, and the old GitHub path was
directly verified to resolve to the renamed repository. No commits were pushed
by the rename. On the same date, with separate explicit authorization, the
package project links, distribution assertion, embedded plugin wheel, and
exact installed-agent evidence were refreshed for the renamed URL.

## Exact-artifact URL refresh — completed

On 2026-08-15, Kyle explicitly authorized this internal refresh while keeping
the owner self-testing pause in force. `pyproject.toml`, the distribution
assertion, and the embedded plugin wheel now use `kserrec/glossabet`. Comparing
the rebuilt wheel with the Phase 22 wheel showed changes only to `METADATA` and
`RECORD`; every executable package entry was byte-identical. The authenticated
installed-agent evaluation consumed Codex usage and passed 11/11 scenarios on
the refreshed exact wheel. Its uniquely named user-level Codex marketplace and
plugin state was removed and verified absent afterward. A clean public-main CI
checkout exposed that the first evidence identity included an ignored local
Python `__pycache__` file; the identity now excludes interpreter cache
directories, a focused regression protects clean-checkout parity, and the same
exact wheel passed 11/11 again under the corrected identity. This refresh did
not invite outside testers, begin Phase 23, create a release, or publish a
package.

## External setup still requiring Kyle

### Private security reports

Enable GitHub private vulnerability reporting for the public repository, then
enable notifications for security alerts. GitHub's current instructions are
[Configuring private vulnerability reporting for a
repository](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).
Enabling it creates a private disclosure channel; it does not publish a report
or expose vulnerability details.

### PyPI Trusted Publishing

Create a GitHub environment named `pypi` and protect it with the desired
reviewer policy. Then register a PyPI pending Trusted Publisher with these
literal values:

| Field | Value |
|---|---|
| PyPI project name | `glossabet` |
| GitHub owner | `kserrec` |
| GitHub repository | `glossabet` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

PyPI documents this at [Creating a PyPI project with a Trusted
Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).
A pending publisher does not create the project or reserve its name; the first
successful workflow upload does both.

## Publication consequence and trigger

Publishing creates a public `glossabet` project and public release metadata
and files on PyPI. A bad release can be yanked, but the same uploaded
filename/version cannot be silently replaced in place. The workflow and its
logs are visible in the public GitHub repository.

After the local gate, security channel, GitHub environment, pending publisher,
changelog date, and `v0.1.0` tag are all verified, an authorized maintainer can
trigger the workflow from that exact tag with:

```console
gh workflow run release.yml --repo kserrec/glossabet --ref v0.1.0 -f confirmation=publish-glossabet-to-pypi
```

The hosted repository rename prerequisite is complete, but the command remains
unauthorized while owner self-testing and all later gates are incomplete. It
is the publication action: once the external configuration is in place and the
workflow passes its guards, it uploads the package to public PyPI. Merely
merging the workflow never uploads anything.
GitHub documents
manual workflow dispatch through the command line in [Manually running a
workflow](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow#running-a-workflow-using-github-cli).

After publication, verify the PyPI project page, install the release by exact
version in a new environment, rerun the walkthrough, and create a matching
GitHub Release from the already-published tag. None of those external steps
has been performed for 0.1.0.
