#!/usr/bin/env python3
"""Install a built wheel in isolation, exercise it, and uninstall it."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _one_wheel(dist: Path) -> Path:
    wheels = sorted(dist.resolve().glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"wheel smoke: expected one wheel, found {len(wheels)}")
    return wheels[0]


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args()
    wheel = _one_wheel(args.dist_dir)

    with tempfile.TemporaryDirectory(prefix="glossarize-wheel-smoke-") as raw:
        work = Path(raw)
        environment = work / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / ("glossarize.exe" if os.name == "nt" else "glossarize")

        env = os.environ.copy()
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
        env["GLOSSARIZE_CACHE_DIR"] = str(work / "cache")
        env["PIP_CACHE_DIR"] = str(work / "pip-cache")
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        env["PIP_NO_INDEX"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        _run(
            [
                str(python), "-m", "pip", "install", "--no-deps",
                "--no-index", str(wheel),
            ],
            cwd=work,
            env=env,
        )
        _run([str(cli), "--version"], cwd=work, env=env)

        destination = work / "skills" / "glossarize"
        _run(
            [
                str(cli), "install", "--agent", "codex",
                "--destination", str(destination),
            ],
            cwd=work,
            env=env,
        )
        installed_skill = destination / "SKILL.md"
        if installed_skill.read_bytes() != (ROOT / "skill" / "SKILL.md").read_bytes():
            raise RuntimeError("wheel-installed skill differs from the canonical skill")

        _run(
            [str(python), str(ROOT / "scripts" / "run_walkthrough.py")],
            cwd=work,
            env=env,
        )

        _run(
            [str(python), "-m", "pip", "uninstall", "-y", "glossarize"],
            cwd=work,
            env=env,
        )
        probe = (
            "import importlib.util; "
            "raise SystemExit(importlib.util.find_spec('glossarize') is not None)"
        )
        _run([str(python), "-c", probe], cwd=work, env=env)
        if cli.exists():
            raise RuntimeError("pip uninstall left the glossarize entry point behind")
        if not installed_skill.is_file():
            raise RuntimeError("pip uninstall unexpectedly removed the user-installed skill")

    print(
        "wheel smoke passed: isolated install, skill install, walkthrough, "
        "package uninstall, and temporary cleanup completed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
