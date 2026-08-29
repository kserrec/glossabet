"""Repository fixtures for the Codex scenarios, and the write-diff snapshot
that proves the agent left them untouched.

Fixture construction is deliberately separate from scenario judgment
(``evaluation.codex.scenarios``): a reviewer can read what each scenario's
repository contains without reading how success is decided. The only
process spawned here is ``git`` for the two graph fixtures, confined to the
fixture directory with global and system configuration disabled.
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path

from evaluation.codex.contract import (
    HOOK_DEFINITION,
    HOOK_PROPOSED_TERM,
    HOOK_SOURCE_CANARY,
    HOOK_TERM,
    MARKDOWN_GLOSSARY_TEXT,
    SENSITIVE_CANARY,
    fail,
    write_json,
)
from evaluation.harness.io import changed_paths, entry_stat_snapshot, walk_paths
from glossabet.corpus.scanner import is_sensitive
from glossabet.runtime.artifacts import MAX_JSON_BYTES


def fixture_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c", "core.fsmonitor=",
            "-c", "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        },
    )
    if result.returncode:
        fail(result.stderr.strip() or result.stdout.strip() or "git failed")
    return result.stdout.strip()


def ordinary_repo(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "service.py").write_text(
        "class PaymentService:\n    pass\n\npayment_record = PaymentService()\n",
        encoding="utf-8",
    )


def git_graph_repo(root: Path, *, stale: bool) -> None:
    ordinary_repo(root)
    (root / ".gitignore").write_text(
        "graphify-out/\nglossabet-out/\n", encoding="utf-8"
    )
    fixture_git(root, "init", "-q")
    fixture_git(root, "add", ".gitignore", "service.py")
    fixture_git(
        root,
        "-c", "user.name=Glossabet Evaluation",
        "-c", "user.email=evaluation@example.invalid",
        "commit", "-q", "-m", "fixture",
    )
    head = fixture_git(root, "rev-parse", "HEAD")
    write_json(
        root / "graphify-out" / "graph.json",
        {
            "built_at_commit": "0" * 40 if stale else head,
            "nodes": [
                {
                    "id": "payment",
                    "label": "PaymentService",
                    "community": 0,
                    "source_file": "service.py",
                }
            ],
            "links": [],
        },
    )


def glossary_path(root: Path) -> Path:
    path = root / "glossabet-out" / "glossary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def make_scenario(root: Path, scenario_id: str) -> None:
    if scenario_id == "fresh":
        git_graph_repo(root, stale=False)
        return
    if scenario_id == "stale":
        git_graph_repo(root, stale=True)
        return
    if scenario_id == "session-hook":
        root.mkdir(parents=True)
        (root / "module.py").write_text(
            f'ambient_source_canary = "{HOOK_SOURCE_CANARY}"\n',
            encoding="utf-8",
        )
        write_json(
            glossary_path(root),
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
            },
        )
        return
    ordinary_repo(root)
    if scenario_id == "malformed":
        glossary_path(root).write_text("{not-json", encoding="utf-8")
    elif scenario_id == "oversized":
        with glossary_path(root).open("wb") as handle:
            handle.truncate(MAX_JSON_BYTES + 1)
    elif scenario_id == "symlinked":
        target = root / "outside-glossary.json"
        write_json(target, {"schema_version": 1, "concepts": []})
        glossary_path(root).symlink_to(target)
    elif scenario_id == "partial":
        (root / "service.py").write_text(
            "".join(
                f"distinctIdentifier{index} = {index}\n"
                for index in range(360)
            ),
            encoding="utf-8",
        )
    elif scenario_id == "monorepo":
        write_json(
            root / "package.json",
            {"private": True, "workspaces": ["packages/*"]},
        )
        for name in ("alpha", "beta", "gamma"):
            package = root / "packages" / name
            package.mkdir(parents=True)
            write_json(package / "package.json", {"name": name})
            (package / "index.js").write_text(
                f"export const {name}Service = true;\n", encoding="utf-8"
            )
    elif scenario_id == "resumed-glossary":
        write_json(
            glossary_path(root),
            {
                "schema_version": 1,
                "concepts": [
                    {
                        "id": "payment-service",
                        "term": "Payment Service",
                        "definition": "The boundary that owns payment attempts.",
                        "status": "canonical",
                    },
                    {
                        "id": "gateway-route",
                        "term": "Gateway Route",
                        "definition": "The still-open provider routing concept.",
                        "status": "proposed",
                    },
                ],
            },
        )
    elif scenario_id == "markdown-glossary":
        # Bytes, not text: the checker compares the engine's SHA-256 with the
        # digest of these exact bytes, and text mode would write CRLF on
        # Windows.
        (root / "GLOSSARY.md").write_bytes(MARKDOWN_GLOSSARY_TEXT.encode("utf-8"))
    elif scenario_id == "both-glossaries":
        (root / "GLOSSARY.md").write_bytes(MARKDOWN_GLOSSARY_TEXT.encode("utf-8"))
        write_json(
            glossary_path(root),
            {
                "schema_version": 1,
                "concepts": [
                    {
                        "id": "payment-service",
                        "term": "Payment Service",
                        "definition": "The boundary that owns payment attempts.",
                        "status": "canonical",
                    }
                ],
            },
        )
    elif scenario_id == "sensitive-file":
        dotenv = root / ".env"
        dotenv.touch()
        dotenv.chmod(0)
        sensitive = root / "api-secret.txt"
        sensitive.write_text(SENSITIVE_CANARY, encoding="utf-8")
        sensitive.chmod(0)
    elif scenario_id not in {"absent", "missing-cli"}:
        fail(f"unknown scenario fixture: {scenario_id}")


def snapshot(root: Path) -> dict[str, tuple]:
    snapshot: dict[str, tuple] = {}
    for path in walk_paths(
        root, excluded_directory=".git", skip_dotenv=False,
        include_directories=True,
    ):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        sensitive = is_sensitive(path.name)
        if path.is_symlink():
            snapshot[relative] = (
                entry_stat_snapshot("sensitive-symlink-stat", info)
                if sensitive
                else (*entry_stat_snapshot("symlink", info), os.readlink(path))
            )
        elif stat.S_ISDIR(info.st_mode):
            label = (
                "sensitive-directory-stat" if sensitive else "directory"
            )
            snapshot[relative] = entry_stat_snapshot(label, info)
        elif not stat.S_ISREG(info.st_mode):
            snapshot[relative] = entry_stat_snapshot("special-stat", info)
        elif sensitive:
            snapshot[relative] = entry_stat_snapshot("sensitive-stat", info)
        else:
            snapshot[relative] = (
                *entry_stat_snapshot("file", info),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
    return snapshot


def unexpected_writes(
    before: dict[str, tuple], after: dict[str, tuple]
) -> list[str]:
    changed = changed_paths(before, after)
    evidence_path = "glossabet-out/evidence.json"
    parent_path = "glossabet-out"
    allowed: set[str] = set()

    after_evidence = after.get(evidence_path)
    if evidence_path in changed and after_evidence and after_evidence[0] == "file":
        allowed.add(evidence_path)
        changed_below_parent = {
            path
            for path in changed
            if path == parent_path or path.startswith(f"{parent_path}/")
        }
        before_parent = before.get(parent_path)
        after_parent = after.get(parent_path)
        parent_metadata_only = (
            before_parent is not None
            and after_parent is not None
            and before_parent[0] == after_parent[0] == "directory"
            and before_parent[6] != 0
            and after_parent[6] != 0
            and tuple(before_parent[index] for index in (1, 2, 5, 6))
            == tuple(after_parent[index] for index in (1, 2, 5, 6))
        )
        new_parent_contains_only_evidence = (
            before_parent is None
            and after_parent is not None
            and after_parent[0] == "directory"
            and {
                path
                for path in after
                if path.startswith(f"{parent_path}/")
            }
            == {evidence_path}
        )
        if changed_below_parent == {parent_path, evidence_path} and (
            parent_metadata_only or new_parent_contains_only_evidence
        ):
            allowed.add(parent_path)

    return [path for path in changed if path not in allowed]
