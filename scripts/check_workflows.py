#!/usr/bin/env python3
"""Check the release invariants that generic workflow tooling cannot know.

PyYAML owns YAML parsing. ``actionlint`` owns GitHub Actions syntax,
expressions, action inputs, and script-injection diagnostics. This module
checks only Glossabet's expected jobs, matrices, release gates, permissions,
and pinned external actions; it is not a workflow-security proof.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
QUALITY_WORKFLOW = "./.github/workflows/quality.yml"
SUPPORTED_OSES = ["ubuntu-latest", "macos-latest", "windows-latest"]
SUPPORTED_PYTHONS = ["3.10", "3.11", "3.12", "3.13", "3.14"]
SETUP_GO_ACTION = (
    "actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e"  # v7.0.0
)
ACTIONLINT_INSTALL = (
    "go install github.com/rhysd/actionlint/cmd/actionlint@v1.7.12"
)
PUBLISH_ACTION = (
    "pypa/gh-action-pypi-publish@"
    "dc37677b2e1c63e2034f94d8a5b11f265b73ba33"
)

TEST_RUNS = [
    "uv sync --locked --python ${{ matrix.python-version }}",
    "uv run --locked pytest -q",
]
STATIC_RUNS = [
    'uv sync --locked --python "3.10"',
    "uv run --locked ruff check .",
    "uv run --locked mypy glossabet",
    ACTIONLINT_INSTALL,
    "actionlint",
]
PACKAGE_RUNS = [
    "uv run --locked python scripts/check_workflows.py",
    "python evaluation/run.py --verify-results evaluation/results.json",
    "python scripts/agent_eval.py --verify-results evaluation/agent-results.json",
    "python evaluation/review.py --verify-results evaluation/reviewer-results.json",
    "uv build --no-sources --clear",
    "python scripts/build_plugin.py dist",
    "python scripts/check_distribution.py dist",
    "python scripts/wheel_smoke.py dist",
]
PUBLISH_RUNS = [
    "uv run --locked python scripts/check_workflows.py",
    "python evaluation/run.py --verify-results evaluation/results.json --current",
    "python scripts/agent_eval.py --verify-results evaluation/agent-results.json --current",
    "python evaluation/review.py --verify-results evaluation/reviewer-results.json --current",
    "uv build --no-sources --clear",
    "python scripts/build_plugin.py dist",
    "git diff --exit-code -- plugins/glossabet",
    'python scripts/check_distribution.py dist --tag "$RELEASE_TAG" --current',
    "python scripts/wheel_smoke.py dist",
]


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _steps(job: dict[str, object]) -> list[dict[str, object]]:
    value = job.get("steps")
    if not isinstance(value, list):
        return []
    return [step for step in value if isinstance(step, dict)]


def _needs(job: dict[str, object]) -> list[str]:
    value = job.get("needs")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _scalar_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _scalar_strings(key)
            yield from _scalar_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _scalar_strings(child)


def _parse_workflows(
    workflow_texts: dict[str, str], errors: list[str]
) -> dict[str, dict[str, object]]:
    parsed: dict[str, dict[str, object]] = {}
    for name, text in workflow_texts.items():
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as error:
            errors.append(f"{name} is invalid YAML: {error}")
            continue
        if not isinstance(document, dict):
            errors.append(f"{name} must contain a YAML mapping")
            continue
        if "on" not in document and True in document:
            errors.append(
                f'{name} must quote its top-level "on" key for PyYAML'
            )
            continue
        parsed[name] = document
    return parsed


def _require_runs(
    label: str,
    job: dict[str, object],
    required: list[str],
    errors: list[str],
) -> None:
    """Require exact, unconditional run steps in the specified order."""
    steps = _steps(job)
    cursor = 0
    for command in required:
        while cursor < len(steps) and steps[cursor].get("run") != command:
            cursor += 1
        if cursor == len(steps):
            errors.append(f"{label} is missing required run step {command!r}")
            continue
        if "if" in steps[cursor]:
            errors.append(f"{label} makes required run step conditional: {command!r}")
        cursor += 1


def _check_action_steps(
    name: str, jobs: dict[str, object], errors: list[str]
) -> None:
    """Enforce repository-wide action pins and checkout credential handling."""
    for job_name, raw_job in jobs.items():
        job = _mapping(raw_job)
        if "continue-on-error" in job:
            errors.append(f"{name} job {job_name} is allowed to fail")
        for step in _steps(job):
            if "continue-on-error" in step:
                errors.append(f"{name} job {job_name} has a step allowed to fail")
            target = step.get("uses")
            if not isinstance(target, str):
                continue
            if not target.startswith("./") and re.fullmatch(
                r"[^@\s]+@[0-9a-f]{40}", target
            ) is None:
                errors.append(f"{name} has an unpinned action: {target}")
            if target.startswith("actions/checkout@"):
                options = _mapping(step.get("with"))
                if options.get("persist-credentials") is not False:
                    errors.append(
                        f"{name} checkout must set persist-credentials: false"
                    )


def _expect_job_names(
    name: str,
    jobs: dict[str, object],
    expected: list[str],
    errors: list[str],
) -> None:
    if list(jobs) != expected:
        errors.append(f"{name} jobs must be exactly {', '.join(expected)}")


def _check_quality(workflow: dict[str, object], errors: list[str]) -> None:
    triggers = _mapping(workflow.get("on"))
    if set(triggers) != {"workflow_call"}:
        errors.append("quality.yml must be reusable through workflow_call only")
    if workflow.get("permissions") != {"contents": "read"}:
        errors.append("quality.yml top-level permissions must be contents: read")

    jobs = _mapping(workflow.get("jobs"))
    _expect_job_names("quality.yml", jobs, ["test", "static", "package"], errors)
    test = _mapping(jobs.get("test"))
    static = _mapping(jobs.get("static"))
    package = _mapping(jobs.get("package"))
    for label, job in (("test", test), ("static", static), ("package", package)):
        if "if" in job:
            errors.append(f"quality {label} job must be unconditional")

    strategy = _mapping(test.get("strategy"))
    matrix = _mapping(strategy.get("matrix"))
    if test.get("runs-on") != "${{ matrix.os }}":
        errors.append("quality test job must run on every matrix OS")
    if strategy.get("fail-fast") is not False:
        errors.append("quality test matrix must set fail-fast: false")
    if matrix.get("os") != SUPPORTED_OSES:
        errors.append("quality test matrix must cover every supported OS")
    if matrix.get("python-version") != SUPPORTED_PYTHONS:
        errors.append("quality test matrix must cover every supported Python")
    _require_runs("quality test job", test, TEST_RUNS, errors)

    if static.get("runs-on") != "ubuntu-latest":
        errors.append("quality static job must run on Ubuntu")
    setup_go = next(
        (step for step in _steps(static) if step.get("uses") == SETUP_GO_ACTION),
        None,
    )
    if setup_go is None or _mapping(setup_go.get("with")) != {
        "go-version": "1.25.x",
        "cache": False,
    }:
        errors.append("quality static job must install the pinned Go toolchain")
    _require_runs("quality static job", static, STATIC_RUNS, errors)

    if _needs(package) != ["test", "static"]:
        errors.append("quality package job must require test and static")
    _require_runs("quality package job", package, PACKAGE_RUNS, errors)


def _check_ci(workflow: dict[str, object], errors: list[str]) -> None:
    if set(_mapping(workflow.get("on"))) != {"push", "pull_request"}:
        errors.append("ci.yml must run for pushes and pull requests")
    if workflow.get("permissions") != {"contents": "read"}:
        errors.append("ci.yml top-level permissions must be contents: read")
    jobs = _mapping(workflow.get("jobs"))
    _expect_job_names("ci.yml", jobs, ["quality"], errors)
    quality = _mapping(jobs.get("quality"))
    if quality != {"uses": QUALITY_WORKFLOW}:
        errors.append("ci.yml must delegate only to the reusable quality workflow")


def _check_release(workflow: dict[str, object], errors: list[str]) -> None:
    triggers = _mapping(workflow.get("on"))
    if set(triggers) != {"workflow_dispatch"}:
        errors.append("release.yml must be manually dispatched only")
    dispatch = _mapping(triggers.get("workflow_dispatch"))
    confirmation = _mapping(_mapping(dispatch.get("inputs")).get("confirmation"))
    if confirmation.get("required") is not True or confirmation.get("type") != "string":
        errors.append("release dispatch must require a string confirmation")
    if workflow.get("permissions") != {"contents": "read"}:
        errors.append("release.yml top-level permissions must be contents: read")

    jobs = _mapping(workflow.get("jobs"))
    _expect_job_names("release.yml", jobs, ["quality", "publish"], errors)
    quality = _mapping(jobs.get("quality"))
    if quality != {"uses": QUALITY_WORKFLOW}:
        errors.append("release quality job must call the reusable quality workflow")

    publish = _mapping(jobs.get("publish"))
    if _needs(publish) != ["quality"]:
        errors.append("release publish job must require the quality job")
    expected_guard = (
        "github.ref_type == 'tag' && "
        "startsWith(github.ref_name, 'v') && "
        "inputs.confirmation == 'publish-glossabet-to-pypi'"
    )
    if publish.get("if") != expected_guard:
        errors.append("release publish job must use the exact tag and confirmation guard")
    if _mapping(publish.get("environment")).get("name") != "pypi":
        errors.append("release publish job must use the pypi environment")
    if publish.get("permissions") != {"contents": "read", "id-token": "write"}:
        errors.append(
            "release publish permissions must be exactly contents: read and id-token: write"
        )
    _require_runs("release publish job", publish, PUBLISH_RUNS, errors)

    steps = _steps(publish)
    if not any(step.get("uses") == PUBLISH_ACTION for step in steps):
        errors.append("release publish job must use the pinned PyPI publisher")
    distribution_step = next(
        (step for step in steps if step.get("run") == PUBLISH_RUNS[-2]),
        None,
    )
    if distribution_step is None or distribution_step.get("env") != {
        "RELEASE_TAG": "${{ github.ref_name }}"
    }:
        errors.append("release tag must reach distribution checking through env")
    if any(
        "${{" in command
        for step in steps
        if isinstance(command := step.get("run"), str)
    ):
        errors.append("release publish run steps must not interpolate expressions")
    if any("secrets." in value for value in _scalar_strings(publish)):
        errors.append("release publish job must not use stored secrets")


def validate_workflow_texts(workflow_texts: dict[str, str]) -> list[str]:
    """Return all project-specific policy violations in supplied workflows."""
    errors: list[str] = []
    required = {"quality.yml", "ci.yml", "release.yml"}
    missing = sorted(required - workflow_texts.keys())
    if missing:
        errors.append(f"missing workflow file(s): {', '.join(missing)}")
    workflows = _parse_workflows(workflow_texts, errors)
    if not required <= workflows.keys():
        return errors

    _check_quality(workflows["quality.yml"], errors)
    _check_ci(workflows["ci.yml"], errors)
    _check_release(workflows["release.yml"], errors)
    for name, workflow in workflows.items():
        _check_action_steps(name, _mapping(workflow.get("jobs")), errors)
    return errors


def check_workflows(directory: Path = WORKFLOWS) -> list[str]:
    """Parse and check every workflow file, including newly added ones."""
    return validate_workflow_texts(
        {
            path.name: path.read_text(encoding="utf-8")
            for path in sorted(directory.iterdir())
            if path.suffix.lower() in (".yml", ".yaml") and path.is_file()
        }
    )


def main() -> int:
    errors = check_workflows()
    if errors:
        for error in errors:
            print(f"workflow policy: {error}")
        return 1
    print("workflow policy check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
