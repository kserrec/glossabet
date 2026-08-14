# Release preparation and publication

Glossarize 0.1.0 is release-ready locally but is **not published to PyPI**.
The source repository is already public at
<https://github.com/kserrec/glossarize>. As verified on 2026-08-14, PyPI's
`glossarize` JSON endpoint returns 404, so the name appears unused; that does
not reserve it and must be checked again immediately before publication.

No PyPI account, pending publisher, GitHub `pypi` environment, Git tag, GitHub
Release, package upload, or private vulnerability-reporting setting was
created or changed while preparing this release. Those actions use Kyle's
accounts and create public or security-sensitive external state, so they
require his explicit authorization.

## What is already prepared

- `pyproject.toml` carries version 0.1.0, Python/platform classifiers, SPDX
  licensing, project links, and an exact wheel mapping for the canonical
  skill.
- `.github/workflows/ci.yml` runs the complete suite on CPython 3.10–3.14 on
  Linux, macOS, and Windows, then builds and smoke-tests both distributions.
- `.github/workflows/release.yml` is manual-only. It can publish only when run
  from a `v*` tag with the exact confirmation text
  `publish-glossarize-to-pypi`, and it expects a protected GitHub environment
  named `pypi` plus PyPI Trusted Publishing. It stores no long-lived PyPI
  token.
- `SECURITY.md` is the public policy file and already points to the future
  private-report form. GitHub private vulnerability reporting is currently
  disabled, so the form will not work until the repository setting is enabled.

## Local release gate

Run these commands from a clean checkout. They build into a fresh temporary
directory rather than trusting stale artifacts in `dist/`:

```bash
release_dir="$(mktemp -d)"
uv sync --locked
uv run pytest -q
uv build --no-sources --out-dir "$release_dir"
uv run python scripts/check_distribution.py "$release_dir" --tag v0.1.0
uv run python scripts/wheel_smoke.py "$release_dir"
```

Before a real release, replace `Unreleased` beside `0.1.0` in `CHANGELOG.md`
with the publication date, commit that change, and rerun the gate from the
exact commit to be tagged.

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
| PyPI project name | `glossarize` |
| GitHub owner | `kserrec` |
| GitHub repository | `glossarize` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

PyPI documents this at [Creating a PyPI project with a Trusted
Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).
A pending publisher does not create the project or reserve its name; the first
successful workflow upload does both.

## Publication consequence and trigger

Publishing creates a public `glossarize` project and public release metadata
and files on PyPI. A bad release can be yanked, but the same uploaded
filename/version cannot be silently replaced in place. The workflow and its
logs are visible in the public GitHub repository.

After the local gate, security channel, GitHub environment, pending publisher,
changelog date, and `v0.1.0` tag are all verified, an authorized maintainer can
trigger the workflow from that exact tag with:

```console
gh workflow run release.yml --repo kserrec/glossarize --ref v0.1.0 -f confirmation=publish-glossarize-to-pypi
```

That command is the publication action: once the external configuration is in
place and the workflow passes its guards, it uploads the package to public
PyPI. Merely merging the workflow never uploads anything. GitHub documents
manual workflow dispatch through the command line in [Manually running a
workflow](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow#running-a-workflow-using-github-cli).

After publication, verify the PyPI project page, install the release by exact
version in a new environment, rerun the walkthrough, and create a matching
GitHub Release from the already-published tag. None of those external steps
has been performed for 0.1.0.
