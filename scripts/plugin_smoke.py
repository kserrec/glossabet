#!/usr/bin/env python3
"""Install, update, and remove the local Glossabet plugin through Codex."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "glossabet"
HOOK_TERM = "Payment Service"
HOOK_DEFINITION = "The boundary that owns payment attempts."
HOOK_PROPOSED_TERM = "Gateway Route"
HOOK_SOURCE_CANARY = "PLUGIN_SMOKE_SOURCE_TEXT_MUST_NOT_REACH_CONTEXT"


def _fail(message: str) -> None:
    raise RuntimeError(f"plugin smoke failed: {message}")


def _run(
    command: list[str], *, cwd: Path, parse_json: bool = False,
    echo_stdout: bool = True,
    timeout: int = 120,
) -> str | dict:
    print(f"$ {' '.join(command)}", flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if result.stdout and echo_stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode:
        _fail(f"command exited {result.returncode}: {' '.join(command)}")
    if not parse_json:
        return result.stdout
    try:
        parsed = json.loads(result.stdout)
    except (ValueError, RecursionError) as exc:
        _fail(f"command returned invalid JSON: {exc}")
    if not isinstance(parsed, dict):
        _fail("command JSON was not an object")
    return parsed


def _source_version(root: Path = ROOT) -> str:
    text = (root / "glossabet" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if match is None:
        _fail("could not read source version")
    return match.group(1)


def _next_patch(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        _fail(f"smoke requires a plain semantic version, got {version!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def _one(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        _fail(f"expected one {label}, found {len(paths)}")
    return paths[0]


def _dotenv_part(name: str) -> bool:
    return (
        name == ".env"
        or name.endswith(".env")
        or name.startswith(".env.")
        or ".env." in name
    )


def _extract_sdist(sdist: Path, destination: Path) -> Path:
    with tarfile.open(sdist, mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                _fail(f"source distribution has unsafe path: {member.name}")
            if member.issym() or member.islnk() or member.isdev():
                _fail(f"source distribution has link/device: {member.name}")
            if any(_dotenv_part(part) for part in path.parts):
                _fail(f"source distribution has forbidden dotenv path: {member.name}")
        archive.extractall(destination)
    roots = [path for path in destination.iterdir() if path.is_dir()]
    return _one(roots, "extracted source root")


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        _fail(f"expected one version marker in {path}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def _prepare_update(sdist: Path, workspace: Path, version: str) -> tuple[Path, str]:
    source = _extract_sdist(sdist, workspace / "update-source")
    next_version = _next_patch(version)
    _replace_once(
        source / "glossabet" / "__init__.py",
        f'__version__ = "{version}"',
        f'__version__ = "{next_version}"',
    )
    _replace_once(
        source / "PKG-INFO",
        f"Version: {version}",
        f"Version: {next_version}",
    )
    _replace_once(
        source / "skill" / "SKILL.md",
        f"matching Glossabet {version} engine",
        f"matching Glossabet {next_version} engine",
    )
    _replace_once(
        source / "skill" / "SKILL.md",
        f"`glossabet {version}`",
        f"`glossabet {next_version}`",
    )
    runner = (
        source
        / "plugins"
        / "glossabet"
        / "skills"
        / "glossabet"
        / "scripts"
        / "run_glossabet.py"
    )
    _replace_once(
        runner,
        f'EXPECTED_VERSION = "{version}"',
        f'EXPECTED_VERSION = "{next_version}"',
    )
    manifest_path = (
        source / "plugins" / "glossabet" / ".codex-plugin" / "plugin.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        _fail("source-distribution plugin manifest version is mismatched")
    manifest["version"] = next_version
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    update_dist = workspace / "update-dist"
    update_dist.mkdir()
    _run(
        [
            "uv", "build", "--wheel", "--no-sources", "--out-dir",
            str(update_dist),
        ],
        cwd=source,
    )
    _run(
        [sys.executable, str(source / "scripts" / "build_plugin.py"), str(update_dist)],
        cwd=source,
    )
    return source / "plugins" / "glossabet", next_version


def _marketplace_file(root: Path, name: str) -> None:
    path = root / ".agents" / "plugins" / "marketplace.json"
    path.parent.mkdir(parents=True)
    payload = {
        "name": name,
        "interface": {"displayName": "Glossabet lifecycle smoke"},
        "plugins": [
            {
                "name": "glossabet",
                "source": {"source": "local", "path": "./plugins/glossabet"},
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _verify_install(
    data: dict,
    version: str,
    canonical_skill: bytes,
    probe_root: Path,
    marketplace_name: str,
) -> Path:
    if data.get("version") != version:
        _fail(f"Codex installed version {data.get('version')!r}, expected {version}")
    installed = Path(str(data.get("installedPath", "")))
    if (
        not installed.is_absolute()
        or installed.name != version
        or installed.parent.name != "glossabet"
        or installed.parents[1].name != marketplace_name
        or installed.parents[2].name != "cache"
        or installed.parents[3].name != "plugins"
    ):
        _fail(f"Codex returned an unexpected install path: {installed}")
    skill_root = installed / "skills" / "glossabet"
    if (skill_root / "SKILL.md").read_bytes() != canonical_skill:
        _fail("installed skill differs from canonical source")
    runner = skill_root / "scripts" / "run_glossabet.py"
    installed_hook = installed / "hooks" / "hooks.json"
    source_hook = PLUGIN / "hooks" / "hooks.json"
    if (
        installed_hook.is_symlink()
        or not installed_hook.is_file()
        or installed_hook.read_bytes() != source_hook.read_bytes()
    ):
        _fail("installed session-start hook differs from source")
    output = _run([sys.executable, str(runner), "--version"], cwd=ROOT)
    if output != f"glossabet {version}\n":
        _fail("installed plugin runner returned the wrong engine version")

    sample = probe_root / f"repository-probe-{version}"
    sample.mkdir(exist_ok=True)
    (sample / "service.py").write_text(
        f'ambient_source_canary = "{HOOK_SOURCE_CANARY}"\n',
        encoding="utf-8",
    )
    glossary = sample / "glossabet-out" / "glossary.json"
    glossary.parent.mkdir()
    glossary.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "concepts": [
                    {
                        "id": "payment-service",
                        "term": HOOK_TERM,
                        "definition": HOOK_DEFINITION,
                        "status": "canonical",
                    },
                    {
                        "id": "gateway-route",
                        "term": HOOK_PROPOSED_TERM,
                        "definition": "A term that has not been settled.",
                        "status": "proposed",
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    context_text = _run(
        [sys.executable, str(runner), "inspect", str(sample), "--no-graphify"],
        cwd=ROOT,
        echo_stdout=False,
    )
    context = json.loads(str(context_text))
    if context.get("generator") != {"name": "glossabet", "version": version}:
        _fail("installed plugin engine emitted mismatched generator metadata")
    before = _snapshot_repository(sample)
    hook_config = json.loads(installed_hook.read_text(encoding="utf-8"))
    handler = hook_config["hooks"]["SessionStart"][0]["hooks"][0]
    hook_command = handler["commandWindows" if os.name == "nt" else "command"]
    hook_result = subprocess.run(
        hook_command,
        cwd=sample,
        env={**os.environ, "PLUGIN_ROOT": str(installed)},
        text=True,
        capture_output=True,
        shell=True,
        timeout=30,
    )
    if (
        hook_result.returncode != 0
        or hook_result.stderr != ""
        or "Glossabet vocabulary brief v1" not in hook_result.stdout
        or HOOK_TERM not in hook_result.stdout
        or HOOK_DEFINITION not in hook_result.stdout
        or HOOK_PROPOSED_TERM in hook_result.stdout
        or HOOK_SOURCE_CANARY in hook_result.stdout
    ):
        _fail("installed SessionStart command did not emit only canonical vocabulary")
    if _snapshot_repository(sample) != before:
        _fail("installed SessionStart hook changed the repository")
    return installed


def _snapshot_repository(root: Path) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    for current, directories, names in os.walk(root):
        directories[:] = sorted(
            name for name in directories if not _dotenv_part(name)
        )
        for name in sorted(names):
            if _dotenv_part(name):
                continue
            path = Path(current) / name
            if path.is_file() and not path.is_symlink():
                content = path.read_bytes()
                snapshot[path.relative_to(root).as_posix()] = (
                    len(content),
                    hashlib.sha256(content).hexdigest(),
                )
    return snapshot


def _current_bundle_matches(wheel: Path, version: str) -> None:
    asset = (
        PLUGIN
        / "skills"
        / "glossabet"
        / "assets"
        / f"glossabet-{version}-py3-none-any.whl"
    )
    if not asset.is_file():
        _fail("current plugin wheel is missing")
    if hashlib.sha256(asset.read_bytes()).digest() != hashlib.sha256(
        wheel.read_bytes()
    ).digest():
        _fail("current plugin wheel differs from the release-gate wheel")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args()

    dist = args.dist_dir.resolve()
    wheel = _one(sorted(dist.glob("glossabet-*.whl")), "wheel")
    sdist = _one(sorted(dist.glob("glossabet-*.tar.gz")), "source distribution")
    version = _source_version()
    _current_bundle_matches(wheel, version)
    canonical_skill = (ROOT / "skill" / "SKILL.md").read_bytes()

    marketplace_name = f"glossabet-smoke-{uuid.uuid4().hex[:12]}"
    plugin_id = f"glossabet@{marketplace_name}"
    marketplace_may_exist = False
    plugin_may_exist = False
    installed_market_cache: Path | None = None
    cleanup_errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="glossabet-plugin-smoke-") as raw:
        workspace = Path(raw)
        marketplace = workspace / "marketplace"
        (marketplace / "plugins").mkdir(parents=True)
        shutil.copytree(PLUGIN, marketplace / "plugins" / "glossabet")
        _marketplace_file(marketplace, marketplace_name)
        updated_plugin, next_version = _prepare_update(
            sdist, workspace, version
        )

        try:
            marketplace_may_exist = True
            added = _run(
                ["codex", "plugin", "marketplace", "add", str(marketplace), "--json"],
                cwd=ROOT,
                parse_json=True,
            )
            if added.get("marketplaceName") != marketplace_name:
                _fail("Codex added the marketplace under the wrong name")
            plugin_may_exist = True
            installed_data = _run(
                ["codex", "plugin", "add", plugin_id, "--json"],
                cwd=ROOT,
                parse_json=True,
            )
            installed = _verify_install(
                installed_data,
                version,
                canonical_skill,
                workspace,
                marketplace_name,
            )
            installed_market_cache = installed.parents[1]

            previous = marketplace / "plugins" / f"glossabet-{version}"
            os.replace(marketplace / "plugins" / "glossabet", previous)
            shutil.copytree(updated_plugin, marketplace / "plugins" / "glossabet")
            _run(
                ["codex", "plugin", "marketplace", "add", str(marketplace), "--json"],
                cwd=ROOT,
                parse_json=True,
            )
            updated_data = _run(
                ["codex", "plugin", "add", plugin_id, "--json"],
                cwd=ROOT,
                parse_json=True,
            )
            installed = _verify_install(
                updated_data,
                next_version,
                (updated_plugin / "skills" / "glossabet" / "SKILL.md").read_bytes(),
                workspace,
                marketplace_name,
            )
            if (installed_market_cache / "glossabet" / version).exists():
                _fail("Codex update left the old plugin version in its cache")
        finally:
            if plugin_may_exist:
                try:
                    _run(
                        ["codex", "plugin", "remove", plugin_id, "--json"],
                        cwd=ROOT,
                        parse_json=True,
                    )
                except Exception as exc:  # preserve the primary failure too
                    cleanup_errors.append(str(exc))
            if marketplace_may_exist:
                try:
                    _run(
                        [
                            "codex", "plugin", "marketplace", "remove",
                            marketplace_name, "--json",
                        ],
                        cwd=ROOT,
                        parse_json=True,
                    )
                except Exception as exc:
                    cleanup_errors.append(str(exc))
            if installed_market_cache is not None and installed_market_cache.exists():
                remaining = list(installed_market_cache.iterdir())
                if remaining:
                    cleanup_errors.append(
                        f"Codex removal left cache content: {remaining!r}"
                    )
                else:
                    installed_market_cache.rmdir()

        if cleanup_errors:
            _fail("; ".join(cleanup_errors))

        marketplaces = _run(
            ["codex", "plugin", "marketplace", "list", "--json"],
            cwd=ROOT,
            parse_json=True,
            echo_stdout=False,
        )
        if any(
            item.get("name") == marketplace_name
            for item in marketplaces.get("marketplaces", [])
            if isinstance(item, dict)
        ):
            _fail("temporary marketplace remains configured after removal")
        plugins = _run(
            ["codex", "plugin", "list", "--json"],
            cwd=ROOT,
            parse_json=True,
            echo_stdout=False,
        )
        if any(
            item.get("pluginId") == plugin_id
            for item in plugins.get("installed", [])
            if isinstance(item, dict)
        ):
            _fail("temporary plugin remains installed after removal")

    print(
        f"plugin smoke passed: Codex installed {version}, updated to "
        f"{next_version}, ran the SessionStart command and bundled CLI, "
        "and removed all test-owned state"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
