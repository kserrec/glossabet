#!/usr/bin/env python3
"""Validate release archives using only the Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import re
import tarfile
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


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


def _source_version() -> str:
    text = (ROOT / "glossarize" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if match is None:
        _fail("could not read __version__ from glossarize/__init__.py")
    return match.group(1)


def _check_wheel(wheel: Path, version: str, canonical_skill: bytes) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        _check_names(names, "wheel")
        required = {
            "glossarize/__main__.py",
            "glossarize/cli.py",
            "glossarize/installer.py",
            "glossarize/_skill/SKILL.md",
            f"glossarize-{version}.dist-info/METADATA",
            f"glossarize-{version}.dist-info/WHEEL",
            f"glossarize-{version}.dist-info/entry_points.txt",
            f"glossarize-{version}.dist-info/licenses/LICENSE",
        }
        missing = sorted(required - set(names))
        if missing:
            _fail(f"wheel is missing: {', '.join(missing)}")
        if archive.read("glossarize/_skill/SKILL.md") != canonical_skill:
            _fail("wheel skill differs from canonical skill/SKILL.md")

        metadata_name = f"glossarize-{version}.dist-info/METADATA"
        metadata = BytesParser(policy=policy.default).parsebytes(
            archive.read(metadata_name)
        )
        expected = {
            "Name": "glossarize",
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
            value == "Repository, https://github.com/kserrec/glossarize"
            for value in project_urls
        ):
            _fail("wheel metadata is missing the repository URL")
        entry_points = archive.read(
            f"glossarize-{version}.dist-info/entry_points.txt"
        ).decode("utf-8")
        if "glossarize = glossarize.cli:main" not in entry_points:
            _fail("wheel is missing the glossarize console entry point")


def _check_sdist(sdist: Path, version: str, canonical_skill: bytes) -> None:
    prefix = f"glossarize-{version}/"
    with tarfile.open(sdist, mode="r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        _check_names(names, "source distribution")
        for member in members:
            if member.issym() or member.islnk() or member.isdev():
                _fail(f"source distribution contains a link/device: {member.name}")

        required_relative = {
            "CHANGELOG.md",
            "LICENSE",
            "PRIVACY.md",
            "README.md",
            "RELEASING.md",
            "SECURITY.md",
            "docs/WALKTHROUGH.md",
            "examples/payment-service/src/payment_service.py",
            "glossarize/installer.py",
            "pyproject.toml",
            "scripts/check_distribution.py",
            "scripts/run_walkthrough.py",
            "scripts/wheel_smoke.py",
            "skill/SKILL.md",
            "tests/test_install.py",
            "tests/test_walkthrough.py",
        }
        required = {prefix + name for name in required_relative}
        missing = sorted(required - set(names))
        if missing:
            _fail(f"source distribution is missing: {', '.join(missing)}")

        skill_member = archive.getmember(prefix + "skill/SKILL.md")
        handle = archive.extractfile(skill_member)
        if handle is None or handle.read() != canonical_skill:
            _fail("source distribution skill differs from canonical skill/SKILL.md")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    parser.add_argument(
        "--tag",
        help="also require this release tag to equal v<package version>",
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
    _check_sdist(sdist, version, canonical_skill)

    for artifact in (wheel, sdist):
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        print(f"{artifact.name}  sha256:{digest}")
    print("distribution check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
