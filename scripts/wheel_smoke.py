#!/usr/bin/env python3
"""Install a built wheel in isolation, exercise it, and uninstall it."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glossabet.agent_context import AGENT_CONTEXT_SCHEMA_VERSION  # noqa: E402


def _one_wheel(dist: Path) -> Path:
    wheels = sorted(dist.resolve().glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"wheel smoke: expected one wheel, found {len(wheels)}")
    return wheels[0]


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _capture(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    input_text: str | None = None,
) -> str:
    print(f"$ {' '.join(command)}", flush=True)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            input=input_text,
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        # check=True raises before the echo below; without this the child's
        # diagnostic dies with its temp dir and only the exit status is
        # ever seen.
        if exc.stdout:
            print(exc.stdout, end="", flush=True)
        if exc.stderr:
            print(exc.stderr, end="", file=sys.stderr, flush=True)
        raise
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist_dir", type=Path)
    args = parser.parse_args()
    wheel = _one_wheel(args.dist_dir)

    with tempfile.TemporaryDirectory(prefix="glossabet-wheel-smoke-") as raw:
        work = Path(raw)
        environment = work / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / ("glossabet.exe" if os.name == "nt" else "glossabet")

        env = os.environ.copy()
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)
        env["GLOSSABET_CACHE_DIR"] = str(work / "cache")
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

        destination = work / "skills" / "glossabet"
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

        boundary_repo = work / "agent-boundary"
        boundary_repo.mkdir()
        (boundary_repo / "service.py").write_text(
            "class PaymentService:\n    pass\n", encoding="utf-8"
        )
        glossary = {
            "schema_version": 1,
            "concepts": [
                {
                    "id": "payment-service",
                    "term": "Payment Service",
                    "definition": "The service that owns payment attempts.",
                    "status": "canonical",
                }
            ],
        }
        _capture(
            [str(cli), "save", str(boundary_repo)],
            cwd=work,
            env=env,
            input_text=json.dumps(glossary),
        )
        context_text = _capture(
            [str(cli), "inspect", str(boundary_repo), "--no-graphify"],
            cwd=work,
            env=env,
        )
        context = json.loads(context_text)
        if context.get("context_schema_version") != AGENT_CONTEXT_SCHEMA_VERSION:
            raise RuntimeError("wheel-installed inspect returned the wrong schema")
        if context.get("glossary", {}).get("concepts") != glossary["concepts"]:
            raise RuntimeError("wheel-installed inspect lost validated glossary state")
        brief_text = _capture(
            [str(cli), "brief", str(boundary_repo)],
            cwd=work,
            env=env,
        )
        if "Payment Service — The service that owns payment attempts." not in brief_text:
            raise RuntimeError("wheel-installed brief lost canonical glossary state")
        if len(brief_text.encode("utf-8")) > 4_096:
            raise RuntimeError("wheel-installed brief exceeded its byte limit")

        agents = boundary_repo / "AGENTS.md"
        human_context = b"# Human instructions\n\nPreserve this text.\n"
        agents.write_bytes(human_context)
        _run(
            [str(cli), "sync-context", str(boundary_repo)],
            cwd=work,
            env=env,
        )
        synchronized = agents.read_bytes()
        if not synchronized.startswith(human_context):
            raise RuntimeError("wheel-installed sync-context changed surrounding text")
        if b"Payment Service" not in synchronized:
            raise RuntimeError("wheel-installed sync-context lost canonical vocabulary")
        _run(
            [str(cli), "sync-context", str(boundary_repo)],
            cwd=work,
            env=env,
        )
        if agents.read_bytes() != synchronized:
            raise RuntimeError("wheel-installed sync-context was not idempotent")
        _run(
            [str(cli), "drift", str(boundary_repo)],
            cwd=work,
            env=env,
        )
        drift = json.loads(
            (boundary_repo / "glossabet-out" / "drift.json").read_text(
                encoding="utf-8"
            )
        )
        agents_status = next(
            target
            for target in drift["managed_context"]["targets"]
            if target["path"] == "AGENTS.md"
        )
        if agents_status["status"] != "current":
            raise RuntimeError("wheel-installed drift did not verify managed context")

        _run(
            [str(python), str(ROOT / "scripts" / "run_walkthrough.py")],
            cwd=work,
            env=env,
        )

        _run(
            [str(python), "-m", "pip", "uninstall", "-y", "glossabet"],
            cwd=work,
            env=env,
        )
        probe = (
            "import importlib.util; "
            "raise SystemExit(importlib.util.find_spec('glossabet') is not None)"
        )
        _run([str(python), "-c", probe], cwd=work, env=env)
        if cli.exists():
            raise RuntimeError("pip uninstall left the glossabet entry point behind")
        if not installed_skill.is_file():
            raise RuntimeError("pip uninstall unexpectedly removed the user-installed skill")
        if agents.read_bytes() != synchronized:
            raise RuntimeError("pip uninstall unexpectedly changed managed repository context")

    print(
        "wheel smoke passed: isolated install, skill install, agent boundary, "
        "managed context, walkthrough, package uninstall, and temporary cleanup completed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
