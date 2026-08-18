#!/usr/bin/env python3
"""Enforce the release workflow's full-matrix dependency chain.

The project deliberately avoids adding a YAML parser solely for policy tests.
These checks parse only the small, pinned subset of workflow syntax that owns
the release gate and fail closed when that shape changes.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
QUALITY_WORKFLOW = "./.github/workflows/quality.yml"
SUPPORTED_OSES = ["ubuntu-latest", "macos-latest", "windows-latest"]
SUPPORTED_PYTHONS = ["3.10", "3.11", "3.12", "3.13", "3.14"]


def _strip_comments(workflow: str) -> str:
    """Drop comment lines and trailing ``# ...`` so a required fragment or a
    guard condition present only inside a comment cannot satisfy a check,
    and a forbidden construct cannot hide behind one. YAML has no ``#`` inside
    the plain scalars these workflows use except in quoted strings, which the
    workflows here do not contain a ``#`` inside."""
    kept = []
    for line in workflow.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith("- #"):
            continue
        kept.append(line.split(" #", 1)[0].rstrip())
    return "\n".join(kept)


def _job_block(workflow: str, name: str) -> str | None:
    lines = workflow.splitlines()
    marker = f"  {name}:"
    try:
        start = lines.index(marker)
    except ValueError:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.fullmatch(r"  [A-Za-z0-9_-]+:", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def _job_names(workflow: str) -> list[str]:
    lines = workflow.splitlines()
    try:
        start = lines.index("jobs:") + 1
    except ValueError:
        return []
    return [
        match.group(1)
        for line in lines[start:]
        if (match := re.fullmatch(r"  ([A-Za-z0-9_-]+):", line))
    ]


def _inline_list(block: str, key: str) -> list[str] | None:
    match = re.search(
        rf"(?m)^\s+{re.escape(key)}:\s*\[([^]]*)\]\s*$",
        block,
    )
    if match is None:
        return None
    return [part.strip().strip('"\'') for part in match.group(1).split(",")]


def _requires_in_order(block: str, fragments: list[str], errors: list[str],
                       label: str) -> None:
    # Each search starts past the previous fragment, so an out-of-order
    # fragment is reported as missing.
    cursor = -1
    for fragment in fragments:
        position = block.find(fragment, cursor + 1)
        if position < 0:
            errors.append(f"{label} is missing required step {fragment!r}")
            continue
        cursor = position


def _check_pinned_actions(name: str, workflow: str, errors: list[str]) -> None:
    for line in workflow.splitlines():
        # A commented-out ``uses:`` is not a step; a trailing comment after
        # the target still is (``uses: x@sha  # note``).
        stripped = line.lstrip()
        if stripped.startswith("- "):
            stripped = stripped[2:].lstrip()
        if stripped.startswith("#"):
            continue  # a commented-out step, with or without its list dash
        match = re.search(r"""\buses:\s*["']?([^\s#"']+)""", line)
        if match is None:
            continue
        target = match.group(1)
        if target.startswith("./"):
            continue
        if re.fullmatch(r"[^@]+@[0-9a-f]{40}", target) is None:
            errors.append(f"{name} has an unpinned action: {target}")


def validate_workflow_texts(workflows: dict[str, str]) -> list[str]:
    """Return every release-gate policy violation in supplied workflow text.

    ``workflows`` must hold EVERY file in the workflows directory: the three
    named ones carry the release gate; any other file is still held to the
    global rules (pinned actions, no fork-PR secret exposure, no expression
    interpolated into a shell line)."""
    errors: list[str] = []
    workflows = {name: _strip_comments(text) for name, text in workflows.items()}
    missing = sorted({"quality.yml", "ci.yml", "release.yml"} - workflows.keys())
    if missing:
        return [f"missing workflow file(s): {', '.join(missing)}"]

    quality = workflows["quality.yml"]
    ci = workflows["ci.yml"]
    release = workflows["release.yml"]

    if "on:\n  workflow_call:" not in quality:
        errors.append("quality.yml is not reusable through workflow_call")
    if re.search(r"(?m)^  (push|pull_request|release|workflow_dispatch):", quality):
        errors.append("quality.yml has a direct trigger instead of workflow_call only")
    if _job_names(quality) != ["test", "package"]:
        errors.append("quality.yml must contain only test then package jobs")

    test = _job_block(quality, "test") or ""
    package = _job_block(quality, "package") or ""
    if _inline_list(test, "os") != SUPPORTED_OSES:
        errors.append("quality.yml does not cover the exact supported OS matrix")
    if _inline_list(test, "python-version") != SUPPORTED_PYTHONS:
        errors.append("quality.yml does not cover the exact supported Python matrix")
    if "fail-fast: false" not in test:
        errors.append("quality.yml must run every matrix cell after a failure")
    _requires_in_order(
        test,
        [
            "uv sync --locked --python ${{ matrix.python-version }}",
            "uv run --locked pytest -q",
        ],
        errors,
        "quality test job",
    )
    if "needs: test" not in package:
        errors.append("quality package job does not require the full test matrix")
    _requires_in_order(
        package,
        [
            "python scripts/check_workflows.py",
            "python evaluation/run.py --verify-results evaluation/results.json",
            "python scripts/agent_eval.py --verify-results evaluation/agent-results.json",
            "python evaluation/review.py --verify-results evaluation/reviewer-results.json",
            "uv build --no-sources --clear",
            "python scripts/build_plugin.py dist",
            "python scripts/check_distribution.py dist",
            "python scripts/wheel_smoke.py dist",
        ],
        errors,
        "quality package job",
    )
    if "--current" in quality:
        errors.append(
            "quality.yml demands evidence currency outside the release gate"
        )

    if _job_names(ci) != ["quality"]:
        errors.append("ci.yml must delegate its only job to the reusable quality gate")
    ci_quality = _job_block(ci, "quality") or ""
    if f"uses: {QUALITY_WORKFLOW}" not in ci_quality:
        errors.append("ci.yml does not call the reusable quality gate")
    if "run:" in ci_quality:
        errors.append("ci.yml embeds commands instead of delegating the gate")

    if "workflow_dispatch:" not in release:
        errors.append("release.yml is not manually dispatched")
    if re.search(r"(?m)^  (push|pull_request|release):", release):
        errors.append("release.yml has a non-manual trigger")
    if _job_names(release) != ["quality", "publish"]:
        errors.append("release.yml must contain only quality then publish jobs")
    release_quality = _job_block(release, "quality") or ""
    publish = _job_block(release, "publish") or ""
    if f"uses: {QUALITY_WORKFLOW}" not in release_quality:
        errors.append("release.yml does not call the reusable quality gate")
    if "if:" in release_quality:
        errors.append("release quality gate must not be conditionally skipped")
    if "needs: quality" not in publish:
        errors.append("release publish job does not require the reusable quality gate")
    for condition in (
        "github.ref_type == 'tag'",
        "startsWith(github.ref_name, 'v')",
        "inputs.confirmation == 'publish-glossabet-to-pypi'",
    ):
        if condition not in publish:
            errors.append(f"release publish guard is missing {condition!r}")
    if "id-token: write" not in publish:
        errors.append("release publish job lacks scoped Trusted Publishing permission")
    if "write-all" in publish or re.search(r"contents:\s*write", publish):
        errors.append("release publish job permissions are broader than read + id-token")
    if "secrets." in publish:
        errors.append(
            "release publish job references a stored secret; publishing uses "
            "Trusted Publishing only"
        )
    _requires_in_order(
        publish,
        [
            "python scripts/check_workflows.py",
            "python evaluation/run.py --verify-results evaluation/results.json --current",
            "python scripts/agent_eval.py --verify-results evaluation/agent-results.json --current",
            "python evaluation/review.py --verify-results evaluation/reviewer-results.json --current",
            "uv build --no-sources --clear",
            "python scripts/build_plugin.py dist",
            "git diff --exit-code -- plugins/glossabet",
            'python scripts/check_distribution.py dist --tag "$RELEASE_TAG" --current',
            "RELEASE_TAG: ${{ github.ref_name }}",
            "python scripts/wheel_smoke.py dist",
            "pypa/gh-action-pypi-publish@",
        ],
        errors,
        "release publish job",
    )

    for name, workflow in workflows.items():
        _check_pinned_actions(name, workflow, errors)
        _check_global_rules(name, workflow, errors)
    return errors


_EVENT_EXPRESSION = re.compile(
    r"\$\{\{\s*(?:github\.event\.|github\.head_ref|github\.ref_name|"
    r"inputs\.|steps\.[^}]*outputs)"
)


def _check_global_rules(name: str, workflow: str, errors: list[str]) -> None:
    """Rules every workflow file obeys, whatever its job: no fork-PR trigger
    that exposes secrets, no attacker-influenced expression interpolated into
    a shell line (pass it through ``env:`` instead), no ``curl | sh``."""
    if re.search(r"(?m)^\s*pull_request_target\s*:", workflow):
        errors.append(f"{name} uses pull_request_target (secrets exposed to fork PRs)")
    for line in workflow.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- run:", "run:")) and _EVENT_EXPRESSION.search(stripped):
            errors.append(
                f"{name} interpolates an untrusted expression into a shell line: "
                f"{stripped[:80]}"
            )
        if re.search(r"curl[^|\n]*\|\s*(?:ba)?sh\b", stripped) or re.search(
            r"wget[^|\n]*\|\s*(?:ba)?sh\b", stripped
        ):
            errors.append(f"{name} pipes a download into a shell: {stripped[:80]}")


def check_workflows(directory: Path = WORKFLOWS) -> list[str]:
    """Every ``*.yml``/``*.yaml`` in the directory — an extra workflow file
    is checked, never ignored."""
    return validate_workflow_texts({
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(directory.iterdir())
        if path.suffix in (".yml", ".yaml") and path.is_file()
    })


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
