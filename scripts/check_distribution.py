#!/usr/bin/env python3
"""Validate release archives using only the Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tarfile
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = "./hooks/hooks.json"
SESSION_START_COMMAND = (
    'python3 -B "$PLUGIN_ROOT/skills/glossabet/scripts/run_glossabet.py" brief .'
)
SESSION_START_COMMAND_WINDOWS = (
    'py -3 -B "%PLUGIN_ROOT%\\skills\\glossabet\\scripts\\run_glossabet.py" brief .'
)


# Version-independent files every published source distribution must carry.
SDIST_REQUIRED_RELATIVE = frozenset({
    ".github/workflows/quality.yml",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "DISTRIBUTION.md",
    "LICENSE",
    "NAME-CLEARANCE.md",
    "PRIVACY.md",
    "README.md",
    "RELEASING.md",
    "SECURITY.md",
    "docs/WALKTHROUGH.md",
    "examples/payment-service/glossabet-out/glossary.json",
    "examples/payment-service/src/payment_service.py",
    "evaluation/agent-history.json",
    "evaluation/agent-prompt.md",
    "evaluation/agent-response-schema.json",
    "evaluation/agent-results.json",
    "evaluation/agent-scenarios.json",
    "evaluation/fixtures/structural-complete/README.md",
    "evaluation/fixtures/structural-complete/core.py",
    "evaluation/fixtures/structural-complete/graphify-out/graph.json",
    "evaluation/fixtures/structural-complete/tenant_a/code.py",
    "evaluation/fixtures/structural-complete/tenant_b/code.py",
    "evaluation/fixtures/structural-complete/tenant_c/code.py",
    "evaluation/fixtures/structural-complete/tenant_d/code.py",
    "evaluation/fixtures/structural-complete/tenant_e/code.py",
    "evaluation/fixtures/structural-truncation/README.md",
    "evaluation/fixtures/structural-truncation/graphify-out/graph.json",
    "evaluation/fixtures/structural-truncation/main.py",
    "evaluation/review.py",
    "evaluation/reviewer-packet.json",
    "evaluation/reviewer-prompt.md",
    "evaluation/reviewer-response-schema.json",
    "evaluation/reviewer-results.json",
    "evaluation/results.json",
    "evaluation/run.py",
    "glossabet/agent/context_sync.py",
    "glossabet/install/installer.py",
    "plugins/glossabet/.codex-plugin/plugin.json",
    "plugins/glossabet/hooks/hooks.json",
    "plugins/glossabet/skills/glossabet/scripts/run_glossabet.py",
    "plugins/glossabet/skills/glossabet/SKILL.md",
    "pyproject.toml",
    "scripts/check_distribution.py",
    "scripts/check_workflows.py",
    "scripts/agent_eval.py",
    "scripts/build_plugin.py",
    "scripts/plugin_smoke.py",
    "scripts/run_walkthrough.py",
    "scripts/wheel_smoke.py",
    "skill/SKILL.md",
    "tests/test_context_sync.py",
    "tests/test_install.py",
    "tests/test_agent_evaluation.py",
    "tests/test_evaluation.py",
    "tests/test_plugin.py",
    "tests/test_release.py",
    "tests/test_reviewer_evaluation.py",
    "tests/test_walkthrough.py",
})


def _fail(message: str) -> None:
    raise SystemExit(f"distribution check failed: {message}")


def _one(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        _fail(f"expected exactly one {label}, found {len(paths)}")
    return paths[0]


def _dotenv_part(name: str) -> bool:
    return (
        name == ".env"
        or name.endswith(".env")
        or name.startswith(".env.")
        or ".env." in name
    )


def _check_names(names: list[str], label: str) -> None:
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            _fail(f"{label} contains an unsafe member path: {name}")
        if any(_dotenv_part(part) for part in path.parts):
            _fail(f"{label} contains a forbidden dotenv path: {name}")


# A published artifact must never carry a local absolute home path: those leak
# a username and the maintainer's directory layout permanently on PyPI. The
# username segment must be path-like (word chars), so this pattern's own
# source text (which contains the literal "/home/") is not a match. The
# superuser home directory on Linux (where a CI or container build may run)
# has no separate username segment, so it is matched as a whole path element;
# a negative lookbehind keeps an ordinary nested directory of that name (for
# example "/usr/<name>/") from matching, and its spelling is split across two
# byte-literals so this file does not flag itself when the sdist (which ships
# scripts/) is scanned.
_LOCAL_PATH_RE = re.compile(
    # A home directory with or without a trailing separator: a recorded
    # working directory that *is* the home directory leaks the username just
    # as a path beneath it does. (Spelled without an example so this file
    # does not flag itself in the sdist.)
    rb"(?<![\w.-])(?:/home/|/Users/)[\w.-]+(?![\w.-])"
    rb"|(?<![\w/.-])/roo" rb"t(?![\w.-])"
    rb"|[A-Za-z]:\\Users\\[\w.-]+"
)


def _check_no_local_paths(data: bytes, member: str, label: str) -> None:
    match = _LOCAL_PATH_RE.search(data)
    if match is not None:
        _fail(
            f"{label} member {member} leaks a local home path: "
            f"{match.group().decode('utf-8', 'replace')!r}"
        )


def _source_version() -> str:
    text = (ROOT / "glossabet" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if match is None:
        _fail("could not read __version__ from glossabet/__init__.py")
    return match.group(1)


def _check_wheel(wheel: Path, version: str, canonical_skill: bytes) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        _check_names(names, "wheel")
        required = {
            "glossabet/__main__.py",
            "glossabet/agent/brief.py",
            "glossabet/cli.py",
            "glossabet/agent/context_sync.py",
            "glossabet/install/installer.py",
            "glossabet/_skill/SKILL.md",
            f"glossabet-{version}.dist-info/METADATA",
            f"glossabet-{version}.dist-info/WHEEL",
            f"glossabet-{version}.dist-info/entry_points.txt",
            f"glossabet-{version}.dist-info/licenses/LICENSE",
        }
        missing = sorted(required - set(names))
        if missing:
            _fail(f"wheel is missing: {', '.join(missing)}")
        if archive.read("glossabet/_skill/SKILL.md") != canonical_skill:
            _fail("wheel skill differs from canonical skill/SKILL.md")

        metadata_name = f"glossabet-{version}.dist-info/METADATA"
        metadata = BytesParser(policy=policy.default).parsebytes(
            archive.read(metadata_name)
        )
        expected = {
            "Name": "glossabet",
            "Version": version,
            "License-Expression": "Apache-2.0",
            "Requires-Python": ">=3.10",
        }
        for field, value in expected.items():
            if metadata[field] != value:
                _fail(
                    f"wheel metadata {field} is {metadata[field]!r}, expected {value!r}"
                )
        if metadata.get_all("Requires-Dist", []) != []:
            _fail("wheel unexpectedly declares a runtime dependency")
        project_urls = metadata.get_all("Project-URL", [])
        if not any(
            value == "Repository, https://github.com/kserrec/glossabet"
            for value in project_urls
        ):
            _fail("wheel metadata is missing the repository URL")
        entry_points = archive.read(
            f"glossabet-{version}.dist-info/entry_points.txt"
        ).decode("utf-8")
        if "glossabet = glossabet.cli:main" not in entry_points:
            _fail("wheel is missing the glossabet console entry point")


def _check_plugin_bundle(
    *,
    manifest_bytes: bytes,
    hooks_bytes: bytes,
    skill_bytes: bytes,
    runner_bytes: bytes,
    wheel_bytes: bytes,
    version: str,
    canonical_skill: bytes,
    label: str,
    current: bool = True,
) -> None:
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeError, ValueError, RecursionError) as exc:
        _fail(f"{label} plugin manifest is invalid JSON: {exc}")
    if manifest.get("name") != "glossabet":
        _fail(f"{label} plugin manifest does not match the package name")
    if current and manifest.get("version") != version:
        _fail(f"{label} plugin manifest does not match the package version")
    if manifest.get("skills") != "./skills/":
        _fail(f"{label} plugin manifest does not expose its skills directory")
    if manifest.get("hooks") != HOOK_PATH:
        _fail(f"{label} plugin manifest does not expose its hooks file")
    try:
        hooks = json.loads(hooks_bytes)
    except (UnicodeError, ValueError, RecursionError) as exc:
        _fail(f"{label} plugin hooks are invalid JSON: {exc}")
    expected_handler = {
        "type": "command",
        "command": SESSION_START_COMMAND,
        "commandWindows": SESSION_START_COMMAND_WINDOWS,
        "timeout": 30,
        "statusMessage": "Loading settled repository vocabulary",
        "additionalContextLimit": 0,
    }
    try:
        groups = hooks["hooks"]["SessionStart"]
        matcher = groups[0]["matcher"]
        handlers = groups[0]["hooks"]
    except (KeyError, IndexError, TypeError):
        _fail(f"{label} plugin has no usable SessionStart hook")
    if (
        set(hooks) != {"description", "hooks"}
        or set(hooks["hooks"]) != {"SessionStart"}
        or len(groups) != 1
        or matcher != "^(startup|resume|clear|compact)$"
        or handlers != [expected_handler]
    ):
        _fail(f"{label} plugin SessionStart hook is stale or unbounded")
    if current and skill_bytes != canonical_skill:
        _fail(f"{label} plugin skill differs from canonical skill/SKILL.md")
    if current:
        expected_runner = f'EXPECTED_VERSION = "{version}"'.encode()
        if expected_runner not in runner_bytes:
            _fail(f"{label} plugin runner does not match the package version")
    # The runner refuses to execute a wheel whose bytes do not match this
    # pinned digest; the shipped runner and wheel must therefore agree. This
    # binding is self-consistent within the artifact, so it holds in both
    # modes.
    pinned = re.search(
        rb'EXPECTED_WHEEL_SHA256 = \(\s*"([0-9a-f]{64})"', runner_bytes
    )
    if pinned is None:
        _fail(f"{label} plugin runner does not pin an expected wheel digest")
    elif pinned.group(1).decode() != hashlib.sha256(wheel_bytes).hexdigest():
        _fail(f"{label} plugin runner's pinned wheel digest does not match the wheel")

    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
        metadata_names = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            _fail(f"{label} plugin wheel has ambiguous metadata")
        try:
            metadata = BytesParser(policy=policy.default).parsebytes(
                archive.read(metadata_names[0])
            )
            bundled_skill = archive.read("glossabet/_skill/SKILL.md")
        except KeyError as exc:
            _fail(f"{label} plugin wheel is missing {exc}")
        if metadata["Name"] != "glossabet":
            _fail(f"{label} plugin wheel has the wrong package name")
        if current and metadata["Version"] != version:
            _fail(f"{label} plugin wheel has the wrong package version")
        if metadata.get_all("Requires-Dist", []) != []:
            _fail(f"{label} plugin wheel declares a runtime dependency")
        if current and bundled_skill != canonical_skill:
            _fail(f"{label} plugin wheel embeds a mismatched skill")


def _check_source_plugin(
    wheel: Path, version: str, canonical_skill: bytes
) -> None:
    root = ROOT / "plugins" / "glossabet"
    skill = root / "skills" / "glossabet"
    asset = skill / "assets" / f"glossabet-{version}-py3-none-any.whl"
    _check_plugin_bundle(
        manifest_bytes=(root / ".codex-plugin" / "plugin.json").read_bytes(),
        hooks_bytes=(root / "hooks" / "hooks.json").read_bytes(),
        skill_bytes=(skill / "SKILL.md").read_bytes(),
        runner_bytes=(skill / "scripts" / "run_glossabet.py").read_bytes(),
        wheel_bytes=asset.read_bytes(),
        version=version,
        canonical_skill=canonical_skill,
        label="source",
    )
    if asset.read_bytes() != wheel.read_bytes():
        _fail("source plugin wheel differs from the release wheel")


def _check_sdist(
    sdist: Path,
    wheel: Path,
    version: str,
    canonical_skill: bytes,
    *,
    current: bool,
) -> None:
    prefix = f"glossabet-{version}/"
    with tarfile.open(sdist, mode="r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        _check_names(names, "source distribution")
        for member in members:
            if member.issym() or member.islnk() or member.isdev():
                _fail(f"source distribution contains a link/device: {member.name}")
            if member.isfile():
                handle = archive.extractfile(member)
                if handle is not None:
                    _check_no_local_paths(
                        handle.read(), member.name, "source distribution"
                    )

        required_relative = SDIST_REQUIRED_RELATIVE
        required = {prefix + name for name in required_relative}
        missing = sorted(required - set(names))
        if missing:
            _fail(f"source distribution is missing: {', '.join(missing)}")

        skill_member = archive.getmember(prefix + "skill/SKILL.md")
        handle = archive.extractfile(skill_member)
        if handle is None or handle.read() != canonical_skill:
            _fail("source distribution skill differs from canonical skill/SKILL.md")

        def member_bytes(relative: str) -> bytes:
            member = archive.getmember(prefix + relative)
            extracted = archive.extractfile(member)
            if extracted is None:
                _fail(f"source distribution member is unreadable: {relative}")
            return extracted.read()

        asset_prefix = prefix + "plugins/glossabet/skills/glossabet/assets/"
        asset_names = [
            name
            for name in names
            if name.startswith(asset_prefix + "glossabet-")
            and name.endswith("-py3-none-any.whl")
        ]
        if len(asset_names) != 1:
            _fail(
                "source distribution must bundle exactly one plugin wheel, "
                f"found {len(asset_names)}"
            )
        if current and asset_names[0] != (
            asset_prefix + f"glossabet-{version}-py3-none-any.whl"
        ):
            _fail("source-distribution plugin wheel does not match the version")
        # The bundled plugin snapshots the checked-in tree, which may
        # honestly lag engine source between releases: its structure and
        # contracts are always validated, while equality with the current
        # source and release wheel is a release-gate question (--current),
        # like the plugin git-diff step.
        plugin_wheel = member_bytes(asset_names[0][len(prefix):])
        _check_plugin_bundle(
            manifest_bytes=member_bytes(
                "plugins/glossabet/.codex-plugin/plugin.json"
            ),
            hooks_bytes=member_bytes(
                "plugins/glossabet/hooks/hooks.json"
            ),
            skill_bytes=member_bytes(
                "plugins/glossabet/skills/glossabet/SKILL.md"
            ),
            runner_bytes=member_bytes(
                "plugins/glossabet/skills/glossabet/scripts/run_glossabet.py"
            ),
            wheel_bytes=plugin_wheel,
            version=version,
            canonical_skill=canonical_skill,
            label="source distribution",
            current=current,
        )
        if current and plugin_wheel != wheel.read_bytes():
            _fail("source-distribution plugin wheel differs from the release wheel")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument(
        "--tag",
        help="also require this release tag to equal v<package version>",
    )
    parser.add_argument(
        "--current",
        action="store_true",
        help=(
            "additionally require the checked-in plugin to match the "
            "current source (the release gate)"
        ),
    )
    args = parser.parse_args()

    dist = args.dist_dir.resolve()
    wheel = _one(sorted(dist.glob("*.whl")), "wheel")
    sdist = _one(sorted(dist.glob("*.tar.gz")), "source distribution")
    version = _source_version()
    if args.tag is not None and args.tag != f"v{version}":
        _fail(f"tag {args.tag!r} does not match package version v{version}")
    canonical_skill = (ROOT / "skill" / "SKILL.md").read_bytes()

    _check_wheel(wheel, version, canonical_skill)
    if args.current:
        _check_source_plugin(wheel, version, canonical_skill)
    _check_sdist(sdist, wheel, version, canonical_skill, current=args.current)

    for artifact in (wheel, sdist):
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        print(f"{artifact.name}  sha256:{digest}")
    print("distribution check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
