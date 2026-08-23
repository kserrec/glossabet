"""Identity and structural verification of the checked-in Codex plugin
artifact — the release gate's deterministic check that the delivered plugin
matches the canonical skill, engine source, and README, without an agent or
network. Executing the checked-in runner is the one subprocess this lane's
offline verification ever spawns, and only under ``current=True``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

from evaluation.codex.contract import (
    ARTIFACT_IDENTITY_KEYS,
    CANONICAL_SKILL,
    PLUGIN,
    PLUGIN_HOOK,
    ROOT,
    AgentEvaluationError,
    expected_hook_config,
    fail,
    read_json,
)
from evaluation.harness.io import file_sha256, is_sha256_hex, tree_sha256, walk_paths
from glossabet import __version__


def plugin_wheel() -> Path:
    wheels = sorted(
        (PLUGIN / "skills" / "glossabet" / "assets").glob("glossabet-*.whl")
    )
    if len(wheels) != 1:
        fail(f"expected one checked-in plugin wheel, found {len(wheels)}")
    return wheels[0]


def artifact_snapshot() -> dict:
    runner = (
        PLUGIN / "skills" / "glossabet" / "scripts" / "run_glossabet.py"
    )
    wheel = plugin_wheel()
    return {
        "canonical_skill_sha256": file_sha256(CANONICAL_SKILL),
        "engine_version": __version__,
        "hook_sha256": file_sha256(PLUGIN_HOOK),
        "plugin_sha256": tree_sha256(PLUGIN),
        "pyproject_sha256": file_sha256(ROOT / "pyproject.toml"),
        "readme_sha256": file_sha256(ROOT / "README.md"),
        "runner_sha256": file_sha256(runner),
        "source_package_sha256": tree_sha256(ROOT / "glossabet"),
        "wheel_sha256": file_sha256(wheel),
    }


def source_python_files() -> dict[str, bytes]:
    package = ROOT / "glossabet"
    return {
        path.relative_to(ROOT).as_posix(): path.read_bytes()
        for path in walk_paths(package, excluded_directory="__pycache__")
        if path.name.endswith(".py")
    }


def artifact_errors(recorded: object) -> list[str]:
    """Verify current delivery deterministically, without an agent or network."""
    errors: list[str] = []
    plugin_skill = PLUGIN / "skills" / "glossabet" / "SKILL.md"
    runner = (
        PLUGIN / "skills" / "glossabet" / "scripts" / "run_glossabet.py"
    )
    guessed_root_runner = PLUGIN / "scripts" / "run_glossabet.py"
    try:
        wheel = plugin_wheel()
        snapshot = artifact_snapshot()
    except (AgentEvaluationError, OSError) as exc:
        return [f"current plugin artifact is unreadable: {exc}"]

    if recorded != snapshot:
        errors.append("current deterministic plugin artifact identity is stale")
    try:
        if (
            plugin_skill.is_symlink()
            or plugin_skill.read_bytes() != CANONICAL_SKILL.read_bytes()
        ):
            errors.append("checked-in plugin skill differs from the canonical skill")
        if runner.is_symlink() or not runner.is_file():
            errors.append("checked-in skill-local runner is missing or symlinked")
        if guessed_root_runner.exists() or guessed_root_runner.is_symlink():
            errors.append("an ambiguous plugin-root runner exists")
        manifest = read_json(
            PLUGIN / ".codex-plugin" / "plugin.json",
            "checked-in plugin manifest",
        )
        if (
            manifest.get("name") != "glossabet"
            or manifest.get("version") != __version__
        ):
            errors.append("checked-in plugin manifest name/version is stale")
        if manifest.get("hooks") != "./hooks/hooks.json":
            errors.append("checked-in plugin manifest does not expose its hook")
        if PLUGIN_HOOK.is_symlink() or not PLUGIN_HOOK.is_file():
            errors.append("checked-in plugin hook is missing or symlinked")
        elif read_json(PLUGIN_HOOK, "checked-in plugin hook") != (
            expected_hook_config()
        ):
            errors.append("checked-in plugin hook contract is stale")
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            source_files = source_python_files()
            wheel_python = {
                name
                for name in names
                if name.startswith("glossabet/") and name.endswith(".py")
            }
            if wheel_python != set(source_files) or any(
                archive.read(name) != content
                for name, content in source_files.items()
                if name in names
            ):
                errors.append("checked-in plugin wheel differs from package source")
            if "glossabet/agent/brief.py" not in names:
                errors.append("checked-in plugin wheel lacks the brief implementation")
            if (
                "glossabet/_skill/SKILL.md" not in names
                or archive.read("glossabet/_skill/SKILL.md")
                != CANONICAL_SKILL.read_bytes()
            ):
                errors.append("checked-in plugin wheel embeds a different skill")
            metadata_names = [
                name for name in names if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                errors.append("checked-in plugin wheel has ambiguous metadata")
            else:
                _headers, separator, description = archive.read(
                    metadata_names[0]
                ).partition(b"\n\n")
                if not separator or description != (ROOT / "README.md").read_bytes():
                    errors.append(
                        "checked-in plugin wheel embeds stale README metadata"
                    )
    except (AgentEvaluationError, OSError, KeyError, zipfile.BadZipFile) as exc:
        errors.append(f"current plugin structure check failed: {exc}")

    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        version = subprocess.run(
            [sys.executable, str(runner), "--version"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if (
            version.returncode != 0
            or version.stdout != f"glossabet {__version__}\n"
            or version.stderr != ""
        ):
            errors.append(
                "checked-in skill-local runner failed its exact version check"
            )
        brief = subprocess.run(
            [
                sys.executable,
                str(runner),
                "brief",
                str(ROOT / "examples" / "payment-service"),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if (
            brief.returncode != 0
            or brief.stderr != ""
            or not brief.stdout.startswith("Glossabet vocabulary brief v1 (emitted by ")
            or "coverage: complete=true" not in brief.stdout
            or len(brief.stdout.encode("utf-8")) > 4_096
        ):
            errors.append(
                "checked-in plugin wheel failed the bounded brief smoke check"
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"current plugin execution check failed: {exc}")
    return errors


def artifact_shape_errors(recorded: object) -> list[str]:
    """Check the recorded artifact identity is well-formed without comparing
    it to the current tree; the release gate performs that comparison."""
    keys = ARTIFACT_IDENTITY_KEYS
    if (
        not isinstance(recorded, dict)
        or set(recorded) != keys
        or not isinstance(recorded.get("engine_version"), str)
        or not recorded.get("engine_version")
        or any(not is_sha256_hex(recorded[key]) for key in keys - {"engine_version"})
    ):
        return ["recorded plugin artifact identity is malformed"]
    return []
