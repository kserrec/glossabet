# Releasing Glossabet

Glossabet 0.1.0 is an unreleased source alpha. It is packageable locally but
is not release-ready and has not been published to PyPI or a public plugin
directory. Kyle's owner self-testing pause, trusted-alpha evidence, and the
exact-artifact release-candidate gate in [`PLAN.md`](PLAN.md) are incomplete.

This document is the operational release procedure. Passing local commands
does not authorize account changes, model-account use, tags, uploads, releases,
or publication.

## Release prerequisites

Before preparing a candidate, all of the following must be true:

- The owner walkthrough and trusted-alpha gate are complete.
- No unresolved critical or high correctness/security finding remains.
- `CHANGELOG.md`, package version, README status, and roadmap status agree.
- The point-in-time package/plugin/name checks in `NAME-CLEARANCE.md` have been
  rerun from the candidate; old availability results do not reserve a name.
- GitHub private vulnerability reporting and its notifications provide a
  working non-public reporting route.
- A protected GitHub environment named `pypi` and a PyPI pending Trusted
  Publisher are configured for `kserrec/glossabet`, workflow `release.yml`,
  environment `pypi`.
- Any deterministic evidence that lags the candidate is regenerated.
- Kyle separately authorizes the exact count and cost ceiling for every live
  Codex/Claude evaluator or reviewer run needed to make evidence current.
- The candidate commit is clean and all release artifacts will be built from
  that exact commit.

Current evidence does not meet this gate: it predates the final candidate, the
recorded deterministic nomination-quality score is 0.75 against a 1.0
threshold, and trusted-alpha evidence does not exist. See
[`EVALUATION.md`](EVALUATION.md).

## Distribution boundary

The application wheel declares zero runtime dependencies. Its canonical skill
is package data, and the `glossabet` entry point maps to `glossabet.cli:main`.
The Codex plugin under `plugins/glossabet/` carries the same skill plus exactly
one matching dependency-free wheel and a version/digest-checking runner.
[`DISTRIBUTION.md`](DISTRIBUTION.md) explains ownership and uninstall behavior.

Development/build dependencies are not wheel dependencies:

- Hatchling `>=1.32,<1.33` builds distributions. The reviewed 1.32.0 wheel was
  78,435 bytes and had five unconditional direct dependencies plus `tomli` on
  Python 3.10.
- PyYAML 6.0.3 is used only to parse workflow YAML. Its CPython 3.12
  manylinux x86-64 wheel was 807,870 bytes, installed size about 2.9 MB, and it
  declared no transitive dependencies.
- pytest, Ruff, and mypy own test/static gates.
- actionlint 1.7.12 owns general GitHub Actions syntax/expression validation.

Those size and vulnerability observations are point-in-time review inputs, not
security guarantees. The lockfile and Dependabot carry the current development
tree; the built wheel's metadata is the authority for the runtime boundary.

## Prepare one exact candidate

1. Select the clean commit intended for release.
2. Set the intended version in `glossabet/__init__.py` and matching plugin,
   skill, and changelog surfaces.
3. Replace `Unreleased` beside that version in `CHANGELOG.md` with the release
   date.
4. Regenerate deterministic evaluation from the exact commit. If the live
   installed-agent or reviewer artifacts are not current, stop and obtain
   separate authorization before running their authenticated generation
   modes. Preserve every miss in the append-only ledgers.
5. Build the plugin from the candidate wheel and keep the generated checked-in
   plugin diff; do not hand-edit its embedded wheel.
6. Review public claims using the checklist below, commit the candidate, and
   rerun every gate from the clean commit.

## Exact local gate

Run from the clean candidate checkout. The temporary output directory prevents
stale `dist/` files from participating:

```bash
release_dir="$(mktemp -d)"
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked mypy glossabet
uv run --locked python scripts/check_workflows.py
actionlint
uv run --locked python evaluation/run.py --verify-results evaluation/results.json --current
uv run --locked python scripts/agent_eval.py --verify-results evaluation/agent-results.json --current
uv run --locked python evaluation/review.py --verify-results evaluation/reviewer-results.json --current
uv run --locked python scripts/run_walkthrough.py
uv run --locked python scripts/benchmark.py --repeat 3
uv build --no-sources --out-dir "$release_dir"
uv run --locked python scripts/build_plugin.py "$release_dir"
git diff --exit-code -- plugins/glossabet
uv run --locked python scripts/check_distribution.py "$release_dir" --tag v0.1.0 --current
uv run --locked python scripts/wheel_smoke.py "$release_dir"
uv run --locked python scripts/plugin_smoke.py "$release_dir"
```

Use the actual version in both the changelog and `--tag`. The `--current`
checks are release-only currency checks. They require the recorded engine,
manifest, prompts, schemas, canonical skill, checked-in plugin, wheel, and
reviewer inputs to match the exact candidate and require release thresholds to
pass. A default verifier passing is not sufficient for release.

`scripts/build_plugin.py` updates generated plugin files. Commit that generated
change before the final clean run; on the clean candidate, rebuilding must make
`git diff --exit-code -- plugins/glossabet` pass.

The local plugin smoke creates only a uniquely named temporary local
marketplace/plugin lifecycle and removes its exact state. It does not publish.

## Manual claims check

The automated gates cannot prove prose. From the exact candidate, verify:

- README, roadmap, changelog, and this file state the same version and release
  status.
- The human-decision wording remains honest: the skill is instructed to wait
  for approval, while `save` validates structure and trusts its caller.
- `PRIVACY.md` still matches every production and agent-host data path.
- `SECURITY.md` still matches path, network, process, race, and reporting
  behavior.
- `NAME-CLEARANCE.md` contains freshly dated package index, plugin directory,
  domain, GitHub, and trademark-search observations and their limits.
- README provenance/affiliation and `CONTRIBUTING.md` Apache-2.0/DCO terms are
  present in the source distribution.
- The wheel declares no `Requires-Dist` runtime dependency, includes LICENSE
  and the canonical skill, and contains no local absolute home path.
- Every built archive rejects escaping member paths, links/devices, and dotenv
  paths under the distribution checker.

## Supported-platform gate

`.github/workflows/quality.yml` is the reusable quality gate. It runs pytest on
CPython 3.10–3.14 across Linux, macOS, and Windows; Ruff/mypy/actionlint on its
static job; then genuine evidence verification, build, distribution checks,
and wheel smoke. `.github/workflows/release.yml` depends on that gate and adds
the release-only current evidence and exact-tag checks before upload.

Local Python 3.10 syntax/type compatibility is required before tagging. The
hosted matrix is the evidence for the other supported versions/platforms; do
not infer their state from a local Python 3.12 run.

## External setup

These are account/security mutations and remain Kyle's actions under separate
explicit authorization.

### Private vulnerability reporting

Enable GitHub private vulnerability reporting for `kserrec/glossabet` and
enable notifications for security alerts. The observable completion state is
that the repository's **Report a vulnerability** form works for a non-owner.
Until then, `SECURITY.md` must continue to say no working private channel is
offered.

### PyPI Trusted Publishing

Create a protected GitHub environment named `pypi`, then configure a pending
PyPI Trusted Publisher with:

| Field | Value |
| --- | --- |
| PyPI project | `glossabet` |
| GitHub owner | `kserrec` |
| Repository | `glossabet` |
| Workflow | `release.yml` |
| Environment | `pypi` |

A pending publisher does not reserve or publish the project. The first
successful upload creates public, durable package metadata.

## Tag and publish

Only after every prerequisite and the final clean gate pass:

1. Create and push the exact `v<version>` tag from the verified candidate.
2. With separate explicit publication authorization, dispatch the manual
   workflow from that tag using the literal confirmation
   `publish-glossabet-to-pypi`.
3. Observe the protected-environment approval and all quality/current checks.
4. Verify the public PyPI project, install the exact version in a fresh
   environment, rerun the user walkthrough, and create a matching GitHub
   Release from the already-published tag.

For 0.1.0, the publication command would be:

```bash
gh workflow run release.yml --repo kserrec/glossabet --ref v0.1.0 -f confirmation=publish-glossabet-to-pypi
```

Do not run it during owner testing. Once external setup exists and workflow
guards pass, it uploads public wheel/source files and public logs to PyPI; an
uploaded filename/version cannot be silently replaced. Merging the workflow or
running local checks alone publishes nothing.
