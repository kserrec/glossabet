"""Repository walk: path roles, exclusions, and monorepo detection.

Sensitive and self-output exclusions are non-overridable trust boundaries.
Repository configuration can add ignores or override conservative path roles;
tests and fixtures stay inventoried, while generated and vendored content is
pruned before a lexical read and reported.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from glossarize.config import EXCLUDED_CONTENT_ROLES, RepositoryConfig

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
# Phase 15 calibration: 84 source files / 659,141 bytes took a 0.32-second
# median cold scan on the reference host. These immutable safety ceilings
# retain roughly 119x file and 49x byte headroom while bounding lexical work.
MAX_SOURCE_FILES = 10_000
MAX_SOURCE_BYTES = 32_000_000
MAX_WALK_ENTRIES = 100_000
MAX_DIRECTORY_ENTRIES = 10_000
BUDGET_PATH_SAMPLE = 20

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
class CorpusBudget:
    walk_entries: int = 0
    source_files: int = 0
    source_bytes: int = 0
    skipped_source_files: int = 0
    skipped_source_bytes: int = 0
    skipped_sample: list[dict] = field(default_factory=list)
    walk_truncated: bool = False
    walk_truncations: int = 0
    minimum_entries_omitted: int = 0
    walk_sample: list[dict] = field(default_factory=list)

    def include_source(self, size: int) -> None:
        self.source_files += 1
        self.source_bytes += size

    def skip_source(self, relative: str, size: int, reason: str) -> None:
        self.skipped_source_files += 1
        self.skipped_source_bytes += size
        if len(self.skipped_sample) < BUDGET_PATH_SAMPLE:
            self.skipped_sample.append({"path": relative, "reason": reason})

    def truncate_walk(
        self, relative: str, minimum_omitted: int, reason: str
    ) -> None:
        self.walk_truncated = True
        self.walk_truncations += 1
        self.minimum_entries_omitted += minimum_omitted
        if len(self.walk_sample) < BUDGET_PATH_SAMPLE:
            self.walk_sample.append({"path": relative, "reason": reason})

    def as_evidence(self) -> dict:
        complete = not self.walk_truncated and not self.skipped_source_files
        return {
            "complete": complete,
            "limits": {
                "walk_entries": MAX_WALK_ENTRIES,
                "directory_entries": MAX_DIRECTORY_ENTRIES,
                "source_files": MAX_SOURCE_FILES,
                "source_bytes": MAX_SOURCE_BYTES,
            },
            "used": {
                "walk_entries": self.walk_entries,
                "source_files": self.source_files,
                "source_bytes": self.source_bytes,
            },
            "skipped": {
                "source_files": self.skipped_source_files,
                "source_bytes": self.skipped_source_bytes,
                "sample": list(self.skipped_sample),
                "sample_truncated": (
                    self.skipped_source_files > len(self.skipped_sample)
                ),
            },
            "walk_remainder": {
                "truncated": self.walk_truncated,
                "minimum_entries_omitted": self.minimum_entries_omitted,
                "exact": not self.walk_truncated,
                "sample": list(self.walk_sample),
                "sample_truncated": self.walk_truncations > len(self.walk_sample),
            },
        }


@dataclass
class WalkResult:
    # (repository-relative path, language, configured/default role)
    code_files: list[tuple[str, str, str]] = field(default_factory=list)
    # (repository-relative path, configured/default role)
    doc_files: list[tuple[str, str]] = field(default_factory=list)
    other_files: int = 0
    skipped_sensitive: list[str] = field(default_factory=list)
    skipped_oversized: list[str] = field(default_factory=list)
    skipped_symlinks: list[str] = field(default_factory=list)
    skipped_configured: list[str] = field(default_factory=list)
    skipped_generated: list[str] = field(default_factory=list)
    skipped_vendored: list[str] = field(default_factory=list)
    sub_roots: list[str] = field(default_factory=list)
    workspace_manifests: list[str] = field(default_factory=list)
    corpus_budget: CorpusBudget = field(default_factory=CorpusBudget)


def _record_role_skip(result: WalkResult, relative: str, role: str) -> None:
    target = (
        result.skipped_generated if role == "generated"
        else result.skipped_vendored
    )
    target.append(relative)


def _bounded_directory_entries(
    path: Path, relative: str, budget: CorpusBudget
) -> list[os.DirEntry] | None:
    """Return a deterministic directory snapshot within the per-dir ceiling.

    If a directory crosses the ceiling, skip it as a whole. Selecting the first
    entries returned by the filesystem would be bounded but nondeterministic;
    all-or-nothing preserves the evidence determinism contract.
    """
    entries: list[os.DirEntry] = []
    try:
        with os.scandir(path) as iterator:
            for entry in iterator:
                if len(entries) >= MAX_DIRECTORY_ENTRIES:
                    budget.truncate_walk(
                        relative,
                        MAX_DIRECTORY_ENTRIES + 1,
                        "directory-entry-limit",
                    )
                    return None
                entries.append(entry)
    except OSError:
        return []
    return sorted(entries, key=lambda entry: entry.name)


def walk_repository(root: Path, config: RepositoryConfig) -> WalkResult:
    result = WalkResult()
    root = root.resolve()
    pending: list[tuple[Path, str]] = [(root, ".")]
    stop_walk = False
    while pending and not stop_walk:
        dirpath, rel_dir = pending.pop()
        entries = _bounded_directory_entries(dirpath, rel_dir, result.corpus_budget)
        if entries is None:
            continue
        is_root = rel_dir == "."
        directories = []
        files = []
        for entry in entries:
            try:
                is_directory = entry.is_dir(follow_symlinks=False)
                is_directory_symlink = (
                    entry.is_symlink() and entry.is_dir(follow_symlinks=True)
                )
            except OSError:
                is_directory = is_directory_symlink = False
            if is_directory or is_directory_symlink:
                directories.append((entry, is_directory_symlink))
            else:
                files.append(entry)

        kept_dirs: list[tuple[Path, str]] = []
        for index, (entry, is_directory_symlink) in enumerate(directories):
            if result.corpus_budget.walk_entries >= MAX_WALK_ENTRIES:
                result.corpus_budget.truncate_walk(
                    rel_dir,
                    len(directories) - index + len(files),
                    "walk-entry-limit",
                )
                stop_walk = True
                break
            result.corpus_budget.walk_entries += 1
            d = entry.name
            relative = d if is_root else f"{rel_dir}/{d}"
            # Sensitive classification precedes every other prune so the
            # exclusion is reported, never silent (mirrors the file rule).
            if is_sensitive(d):
                result.skipped_sensitive.append(relative)
                continue
            if config.is_ignored(relative):
                result.skipped_configured.append(relative)
                continue
            if d.startswith(".") or d in SELF_DIRS:
                continue
            role = config.role_for(relative, is_dir=True)
            if (
                role in EXCLUDED_CONTENT_ROLES
                and not config.has_explicit_descendant(relative)
            ):
                _record_role_skip(result, relative, role)
                continue
            if not is_directory_symlink:
                kept_dirs.append((Path(entry.path), relative))
        if stop_walk:
            break
        filenames = [entry.name for entry in files]
        if not is_root and any(
            m in filenames for m in PACKAGE_MANIFESTS
        ):
            result.sub_roots.append(rel_dir)
        for index, entry in enumerate(files):
            if result.corpus_budget.walk_entries >= MAX_WALK_ENTRIES:
                result.corpus_budget.truncate_walk(
                    rel_dir,
                    len(files) - index,
                    "walk-entry-limit",
                )
                stop_walk = True
                break
            result.corpus_budget.walk_entries += 1
            fname = entry.name
            rel = fname if is_root else f"{rel_dir}/{fname}"
            # Sensitive classification precedes the hidden-file skip so that
            # exclusions like .env are reported, never silently dropped.
            if is_sensitive(fname):
                result.skipped_sensitive.append(rel)
                continue
            if config.is_ignored(rel):
                result.skipped_configured.append(rel)
                continue
            if fname.startswith(".") and fname not in WORKSPACE_MANIFESTS:
                continue
            if fname in SELF_FILES:
                continue
            role = config.role_for(rel)
            if role in EXCLUDED_CONTENT_ROLES:
                _record_role_skip(result, rel, role)
                continue
            if is_root and fname in WORKSPACE_MANIFESTS:
                result.workspace_manifests.append(fname)
            ext = os.path.splitext(fname)[1].lower()
            full = entry.path
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
                if result.corpus_budget.source_files >= MAX_SOURCE_FILES:
                    result.corpus_budget.skip_source(rel, size, "source-file-limit")
                    continue
                if result.corpus_budget.source_bytes + size > MAX_SOURCE_BYTES:
                    result.corpus_budget.skip_source(rel, size, "source-byte-limit")
                    continue
                result.corpus_budget.include_source(size)
                if ext in CODE_LANGUAGES:
                    result.code_files.append((rel, CODE_LANGUAGES[ext], role))
                else:
                    result.doc_files.append((rel, role))
            else:
                result.other_files += 1
        pending.extend(reversed(kept_dirs))
    return result


def _read_root_manifest(
    root: Path, path: Path, walk: WalkResult
) -> str | None:
    """Read a root manifest under the same bounds as walked source files."""
    rel = path.name
    if rel in walk.skipped_configured:
        return None
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
