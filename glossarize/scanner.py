"""Repository walk: classification, exclusions, and monorepo detection.

Three exclusion rules are load-bearing (PLAN.md principles 3 and 4):
sensitive files never enter evidence, Glossarize's own outputs never enter
evidence (contamination), and noise directories are pruned during the walk.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

CODE_LANGUAGES = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".go": "go", ".rs": "rust",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".rb": "ruby", ".cs": "csharp", ".swift": "swift",
    ".php": "php", ".ml": "ocaml", ".mli": "ocaml", ".hs": "haskell",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".clj": "clojure",
    ".lua": "lua", ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".pl": "perl", ".r": "r", ".jl": "julia", ".zig": "zig", ".nim": "nim",
    ".dart": "dart", ".sql": "sql", ".vue": "vue", ".svelte": "svelte",
}

DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}

NOISE_DIRS = frozenset({
    "node_modules", "__pycache__", "_build", "build", "dist", "target",
    "vendor", "venv", "env", "coverage", "_opam", "deps", "out",
})

# Filename patterns that must never enter evidence.
_SENSITIVE_RES = [
    re.compile(p) for p in (
        r"^\.env$", r"\.env$", r"^\.env\.", r"\.env\.",
        r"\.(pem|key|p12|pfx|jks|keystore|der)$",
        r"^id_(rsa|dsa|ecdsa|ed25519)$",
        r"^\.(netrc|npmrc|pypirc|htpasswd)$",
        r"secret", r"credential",
    )
]

# Tool artifacts, not repo content: glossarize's own outputs (so the glossary
# can't echo through the evidence and blind drift detection) and graphify's
# outputs (so its generated reports can't leak into doc vocabulary — the
# graph is consumed through the adapter, never the lexical walk).
SELF_DIRS = frozenset({"glossarize-out", ".glossarize", "graphify-out"})
# Excluded at any depth: a monorepo sub-project's settled glossary echoes
# through evidence exactly like the root one would.
SELF_FILES = frozenset({"GLOSSARY.md"})

MAX_FILE_BYTES = 2_000_000

PACKAGE_MANIFESTS = frozenset({
    "package.json", "pyproject.toml", "setup.py", "Cargo.toml", "go.mod",
    "pom.xml", "build.gradle", "dune-project", "mix.exs", "Gemfile",
})
WORKSPACE_MANIFESTS = frozenset({
    "pnpm-workspace.yaml", "lerna.json", "go.work",
    "WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel",
})
MONOREPO_SUBROOT_THRESHOLD = 3
MONOREPO_CODE_FILE_THRESHOLD = 5000


def is_sensitive(name: str) -> bool:
    lower = name.lower()
    return any(p.search(lower) for p in _SENSITIVE_RES)


def _escapes(full: str, root: Path) -> bool:
    """True if the path's real target lies outside the repo root."""
    try:
        Path(os.path.realpath(full)).relative_to(root)
    except ValueError:
        return True
    return False


@dataclass
class WalkResult:
    code_files: list[tuple[str, str]] = field(default_factory=list)  # (relpath, language)
    doc_files: list[str] = field(default_factory=list)
    other_files: int = 0
    skipped_sensitive: list[str] = field(default_factory=list)
    skipped_oversized: list[str] = field(default_factory=list)
    skipped_symlinks: list[str] = field(default_factory=list)
    sub_roots: list[str] = field(default_factory=list)
    workspace_manifests: list[str] = field(default_factory=list)


def walk_repository(root: Path) -> WalkResult:
    result = WalkResult()
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        is_root = rel_dir == "."
        kept_dirs = []
        for d in sorted(dirnames):
            # Sensitive classification precedes every other prune so the
            # exclusion is reported, never silent (mirrors the file rule).
            if is_sensitive(d):
                result.skipped_sensitive.append(
                    d if is_root else f"{rel_dir}/{d}"
                )
                continue
            if d.startswith(".") or d in NOISE_DIRS or d in SELF_DIRS:
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs
        if not is_root and any(
            m in filenames for m in PACKAGE_MANIFESTS
        ):
            result.sub_roots.append(rel_dir)
        for fname in sorted(filenames):
            rel = fname if is_root else f"{rel_dir}/{fname}"
            # Sensitive classification precedes the hidden-file skip so that
            # exclusions like .env are reported, never silently dropped.
            if is_sensitive(fname):
                result.skipped_sensitive.append(rel)
                continue
            if fname.startswith(".") and fname not in WORKSPACE_MANIFESTS:
                continue
            if fname in SELF_FILES:
                continue
            if is_root and fname in WORKSPACE_MANIFESTS:
                result.workspace_manifests.append(fname)
            ext = os.path.splitext(fname)[1].lower()
            full = os.path.join(dirpath, fname)
            if ext in CODE_LANGUAGES or ext in DOC_EXTENSIONS:
                # A symlink resolving outside the repo is not repo content:
                # reading it would ingest arbitrary host files into evidence
                # (os.walk's followlinks=False guards dirs, not files).
                if os.path.islink(full) and _escapes(full, root):
                    result.skipped_symlinks.append(rel)
                    continue
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                if size > MAX_FILE_BYTES:
                    result.skipped_oversized.append(rel)
                    continue
                if ext in CODE_LANGUAGES:
                    result.code_files.append((rel, CODE_LANGUAGES[ext]))
                else:
                    result.doc_files.append(rel)
            else:
                result.other_files += 1
    return result


def _read_root_manifest(
    root: Path, path: Path, walk: WalkResult
) -> str | None:
    """Read a root manifest under the same bounds as walked source files."""
    rel = path.name
    if path.is_symlink() and _escapes(str(path), root):
        if rel not in walk.skipped_symlinks:
            walk.skipped_symlinks.append(rel)
        return None
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            if rel not in walk.skipped_oversized:
                walk.skipped_oversized.append(rel)
            return None
        return path.read_text(errors="ignore")
    except OSError:
        return None


def _root_workspace_config(root: Path, walk: WalkResult) -> list[str]:
    """Workspace declarations that need bounded inspection at the root."""
    reasons = []
    cargo = root / "Cargo.toml"
    cargo_text = _read_root_manifest(root, cargo, walk)
    if cargo_text is not None and "[workspace]" in cargo_text:
        reasons.append("Cargo.toml declares [workspace]")
    pkg = root / "package.json"
    package_text = _read_root_manifest(root, pkg, walk)
    if package_text is not None:
        try:
            data = json.loads(package_text)
            if isinstance(data, dict) and "workspaces" in data:
                reasons.append("package.json declares workspaces")
        except (ValueError, RecursionError):
            pass
    return reasons


def detect_monorepo(root: Path, walk: WalkResult) -> dict:
    reasons = [f"workspace manifest {m}" for m in sorted(walk.workspace_manifests)]
    reasons += _root_workspace_config(root.resolve(), walk)
    sub_roots = sorted(set(walk.sub_roots))
    if len(sub_roots) >= MONOREPO_SUBROOT_THRESHOLD:
        reasons.append(
            f"{len(sub_roots)} sub-projects with their own package manifests"
        )
    if len(walk.code_files) >= MONOREPO_CODE_FILE_THRESHOLD:
        reasons.append(f"very large repository ({len(walk.code_files)} code files)")
    return {
        "detected": bool(reasons),
        "reasons": reasons,
        "sub_roots": sub_roots,
    }
