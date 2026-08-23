"""Repository fixtures for the Claude scenarios and the write-diff snapshot
that proves the model left them untouched. The only process spawned here
is ``git``, confined to the fixture directory.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path

from evaluation.claude.contract import (
    CANONICAL_DEFINITION,
    CANONICAL_TERM,
    PROPOSED_TERM,
    SOURCE_CANARY,
    fail,
    write_json,
)
from evaluation.harness.io import dotenv_part


def snapshot(root: Path) -> dict[str, tuple]:
    """Hash a fixture without descending into Git or any dotenv path."""
    snapshot: dict[str, tuple] = {}
    for current, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if name not in {".git", "__pycache__"} and not dotenv_part(name)
        )
        for name in sorted(names):
            if dotenv_part(name) or name.endswith(".pyc"):
                continue
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if path.is_symlink():
                snapshot[relative] = ("symlink", os.readlink(path))
            else:
                snapshot[relative] = (
                    "file",
                    info.st_size,
                    stat.S_IMODE(info.st_mode),
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
    return snapshot


def fixture_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=",
            "-c",
            "core.hooksPath=/dev/null",
            *arguments,
        ],
        cwd=root,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        },
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        fail(result.stderr.strip() or result.stdout.strip() or "git failed")
    return result.stdout.strip()


def create_fixture(root: Path, kind: str) -> None:
    root.mkdir(parents=True)
    (root / "payment.py").write_text(
        "from dataclasses import dataclass\n\n"
        "@dataclass(frozen=True)\n"
        "class ChargeIntent:\n"
        "    order_key: str\n"
        "    amount_cents: int\n\n"
        f'SOURCE_NOTE = "{SOURCE_CANARY}"\n',
        encoding="utf-8",
    )
    if kind == "managed-glossary":
        glossary = root / "glossabet-out" / "glossary.json"
        write_json(
            glossary,
            {
                "schema_version": 1,
                "concepts": [
                    {
                        "id": "copper-finch",
                        "term": CANONICAL_TERM,
                        "definition": CANONICAL_DEFINITION,
                        "status": "canonical",
                    },
                    {
                        "id": "silver-heron",
                        "term": PROPOSED_TERM,
                        "definition": "An unsettled alternate name.",
                        "status": "proposed",
                    },
                ],
            },
        )
    elif kind != "no-glossary":
        fail(f"unknown Claude fixture kind: {kind}")
    fixture_git(root, "init", "-q")
    fixture_git(root, "add", "-A")
    fixture_git(
        root,
        "-c",
        "user.email=claude-eval@example.invalid",
        "-c",
        "user.name=Claude Eval",
        "commit",
        "-qm",
        "fixture",
    )
