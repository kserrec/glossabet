"""Where deterministic evaluation input comes from, and how it is identified.

Manifest validation treats ``corpus.json`` as contributor-editable and
therefore hostile: every path is confined, every URL must be https, every
commit is a full object name, and Git runs with its code-execution
surfaces neutralized. Source and engine identity are framed digests so a
recorded result binds to exact bytes. Target repositories are static text
here — nothing from them is imported or executed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from evaluation.deterministic.contract import (
    EVALUATION_SCHEMA_VERSION,
    GIT_SAFE_CONFIG,
    PROJECT_ROOT,
    SOURCE_METADATA_KEYS,
    EvaluationError,
)
from evaluation.harness.identity import lane_source_paths
from evaluation.harness.io import dotenv_part, framed_digest, is_sha256_hex
from glossabet import __version__
from glossabet.analysis.evidence import (
    EVIDENCE_SCHEMA_VERSION,
    build_evidence,
)
from glossabet.analysis.graphify import GRAPH_PATH
from glossabet.corpus.cache import CACHE_ROOT_ENV
from glossabet.corpus.config import CONFIG_FILE
from glossabet.glossary.drift import DRIFT_SCHEMA_VERSION
from glossabet.glossary.reconcile import VALIDATION_SCHEMA_VERSION
from glossabet.runtime.artifacts import MAX_JSON_BYTES


def is_safe_relative(value: object) -> bool:
    """A manifest-supplied path that cannot escape the base it is joined onto.

    `corpus.json` is contributor-editable (a pull request adds a repo to the
    eval corpus), so `checkout_dir`/`path` are attacker-controlled. Joining an
    absolute path or one containing `..` onto the temp checkout root (or the
    project root) escapes it and lets a poisoned manifest create/overwrite
    files anywhere the maintainer can write. Require a non-empty relative path
    with no parent traversal, drive letters, or NUL.
    """
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    # OS-agnostic on purpose: Path.is_absolute() is not — on Windows
    # Path("/tmp/pwn").is_absolute() is False (no drive), so a POSIX absolute
    # path would slip through when the harness runs on Windows. Reject every
    # absolute/traversal form regardless of the running platform.
    if value[0] in "/\\":  # POSIX-absolute or a leading path separator
        return False
    if "\\" in value:  # backslash: Windows separator, never in a relative spec
        return False
    if len(value) >= 2 and value[1] == ":":  # Windows drive, e.g. C:\ or C:foo
        return False
    if ".." in value.split("/"):  # parent traversal
        return False
    return True


def is_commit_sha(value: object) -> bool:
    """git object name: 40 hex (SHA-1) or 64 hex (SHA-256). Rejects a value
    starting with `-` that git would parse as an option in a refspec slot."""
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", value) is not None


def digest_paths(root: Path, relative_paths: list[str]) -> str:
    """Hash path names and bytes with unambiguous framing."""
    base = root.resolve()
    records: list[tuple[str, bytes]] = []
    for relative in sorted(set(relative_paths)):
        rel = Path(relative)
        if (
            rel.is_absolute()
            or ".." in rel.parts
            or any(dotenv_part(part) for part in rel.parts)
        ):
            raise EvaluationError(f"unsafe corpus digest path: {relative}")
        path = (base / rel).resolve()
        try:
            path.relative_to(base)
        except ValueError as exc:
            raise EvaluationError(
                f"corpus digest path escapes its source root: {relative}"
            ) from exc
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise EvaluationError(
                f"could not hash evaluation input {relative}: {exc}"
            ) from exc
        records.append((rel.as_posix(), content))
    return framed_digest(records)


def engine_metadata() -> dict:
    source_paths = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "glossabet").glob("**/*.py")
        if not any(dotenv_part(part) for part in path.parts)
    ]
    source_paths.extend(lane_source_paths("deterministic"))
    return {
        "name": "glossabet",
        "version": __version__,
        "source_sha256": digest_paths(PROJECT_ROOT, source_paths),
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "drift_schema_version": DRIFT_SCHEMA_VERSION,
        "validation_schema_version": VALIDATION_SCHEMA_VERSION,
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
    }


def corpus_identity(root: Path, evidence: dict, *, graphify: bool = False) -> dict:
    paths = [
        item["path"]
        for entries in (evidence["files"]["code"], evidence["files"]["docs"])
        for item in entries
    ]
    if evidence["configuration"].get("present"):
        paths.append(CONFIG_FILE)
    if graphify and (root / GRAPH_PATH).is_file():
        paths.append(GRAPH_PATH)
    return {
        "sha256": digest_paths(root, paths),
        "files_hashed": len(set(paths)),
    }


def read_manifest(path: Path) -> tuple[dict, str]:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise EvaluationError(
            f"{path}: manifest exceeds {MAX_JSON_BYTES} bytes — refusing to load"
        )
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise EvaluationError(f"{path}: unreadable JSON ({exc})") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 6:
        raise EvaluationError(f"{path}: unsupported evaluation manifest")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise EvaluationError(f"{path}: sources must be a non-empty list")
    seen_source_ids: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            raise EvaluationError(f"{path}: every source needs a string id")
        source_id = source["id"]
        if not is_safe_relative(source_id) or "/" in source_id or source_id == ".":
            raise EvaluationError(
                f"{path}: source id must be a safe single path component"
            )
        if source_id in seen_source_ids:
            raise EvaluationError(f"{path}: duplicate source id {source_id!r}")
        seen_source_ids.add(source_id)
        digest = source.get("corpus_sha256")
        files = source.get("corpus_files")
        if (
            not isinstance(digest, str)
            or not is_sha256_hex(digest)
            or not isinstance(files, int)
            or isinstance(files, bool)
            or files < 0
        ):
            raise EvaluationError(
                f"{path}: {source['id']} needs a valid corpus digest/count"
            )
        if not isinstance(source.get("expectations", {}).get("register"), dict):
            raise EvaluationError(
                f"{path}: {source['id']} needs a register expectation"
            )
        if source.get("kind") == "local":
            if not is_safe_relative(source.get("path")):
                raise EvaluationError(
                    f"{path}: {source['id']} path must be a safe relative path"
                )
        else:
            url = source.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                # A non-https url (e.g. `ext::sh -c ...`) reaches
                # `git remote add` and can execute a shell at fetch time.
                raise EvaluationError(
                    f"{path}: {source['id']} url must be an https:// URL"
                )
            if not is_safe_relative(source.get("checkout_dir")):
                # Joined onto the temp checkout root; `..`/absolute escapes it.
                raise EvaluationError(
                    f"{path}: {source['id']} checkout_dir must be a safe "
                    "relative path"
                )
            if not is_commit_sha(source.get("commit")):
                raise EvaluationError(
                    f"{path}: {source['id']} commit must be a 40- or 64-char "
                    "hex object name"
                )
    if not isinstance(manifest.get("self_register"), dict):
        raise EvaluationError(f"{path}: self_register must be an object")
    if not isinstance(manifest.get("self_nominations"), dict):
        raise EvaluationError(f"{path}: self_nominations must be an object")
    return manifest, hashlib.sha256(raw).hexdigest()


def confined_git(args: list[str], cwd: Path, timeout: int = 120) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }
    proc = subprocess.run(
        ["git", *GIT_SAFE_CONFIG, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if proc.returncode:
        detail = proc.stderr.strip() or proc.stdout.strip() or "git failed"
        raise EvaluationError(detail)
    return proc.stdout.strip()


def fetch_source(source: dict, repositories_root: Path) -> Path:
    destination = repositories_root / source["checkout_dir"]
    # Defense in depth: read_manifest already rejects unsafe checkout_dir, but
    # never let a resolved destination escape its base even if that changes.
    try:
        destination.resolve().relative_to(repositories_root.resolve())
    except ValueError as exc:
        raise EvaluationError(
            f"{source['id']}: checkout_dir escapes the checkout root"
        ) from exc
    if destination.exists():
        raise EvaluationError(f"refusing to replace existing {destination}")
    destination.mkdir(parents=True)
    confined_git(["init", "-q"], destination)
    confined_git(["remote", "add", "origin", "--", source["url"]], destination)
    confined_git(["fetch", "--depth", "1", "origin", "--", source["commit"]], destination)
    confined_git(["checkout", "--detach", "--force", "FETCH_HEAD"], destination)
    return destination


def source_root(source: dict, repositories_root: Path | None,
                 fetch: bool) -> Path:
    if source.get("kind") == "local":
        resolved = (PROJECT_ROOT / source["path"]).resolve()
        try:
            resolved.relative_to(PROJECT_ROOT.resolve())
        except ValueError as exc:
            raise EvaluationError(
                f"{source['id']}: local path escapes the project root"
            ) from exc
        return resolved
    if repositories_root is None:
        raise EvaluationError("external sources require --fetch or --repositories-root")
    if not fetch:
        # --repositories-root branch: same escape guard as fetch_source.
        pre = (repositories_root / source["checkout_dir"]).resolve()
        try:
            pre.relative_to(repositories_root.resolve())
        except ValueError as exc:
            raise EvaluationError(
                f"{source['id']}: checkout_dir escapes the checkout root"
            ) from exc
    root = (
        fetch_source(source, repositories_root)
        if fetch else repositories_root / source["checkout_dir"]
    ).resolve()
    if not root.is_dir():
        raise EvaluationError(f"missing checkout for {source['id']}: {root}")
    actual = confined_git(["rev-parse", "HEAD"], root)
    if actual != source["commit"]:
        raise EvaluationError(
            f"{source['id']}: expected {source['commit']}, found {actual}"
        )
    return root


def check_license(source: dict, root: Path) -> None:
    base = PROJECT_ROOT if source.get("license_base") == "project" else root
    license_path = (base / source["license_path"]).resolve()
    try:
        license_path.relative_to(base.resolve())
    except ValueError as exc:
        raise EvaluationError(f"{source['id']}: license path escapes its base") from exc
    if not license_path.is_file():
        raise EvaluationError(f"{source['id']}: missing declared license file")


@contextmanager
def cache_at(path: Path):
    previous = os.environ.get(CACHE_ROOT_ENV)
    os.environ[CACHE_ROOT_ENV] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(CACHE_ROOT_ENV, None)
        else:
            os.environ[CACHE_ROOT_ENV] = previous


def timed_build(
    root: Path, *, cache: bool, graphify: bool = False
) -> tuple[dict, float, dict]:
    stats: dict = {}
    started = time.perf_counter()
    evidence = build_evidence(
        root,
        cache=cache,
        stats=stats,
        graphify=graphify,
    )
    elapsed = time.perf_counter() - started
    return evidence, elapsed, stats


def source_metadata(source: dict) -> dict:
    return {
        key: source[key] for key in SOURCE_METADATA_KEYS if key in source
    }


def manifest_corpus_identity(source: dict) -> dict:
    return {
        "sha256": source["corpus_sha256"],
        "files_hashed": source["corpus_files"],
    }
