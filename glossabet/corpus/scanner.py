"""Repository walk: deterministic traversal, file and directory
classification, and monorepo detection.

Path trust rules live in ``path_policy`` and budget accounting in
``walk_budget``; this module orchestrates them and remains the public facade
for every name the rest of the package imports from the scanner. Sensitive
and self-output exclusions are non-overridable trust boundaries. Repository
configuration can add ignores or override conservative path roles; tests and
fixtures stay inventoried, while generated and vendored content is pruned
before a lexical read and reported.
"""

from __future__ import annotations

import errno
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from glossabet.corpus.config import EXCLUDED_CONTENT_ROLES, RepositoryConfig
from glossabet.corpus.path_policy import (
    LINK_ESCAPES_REPOSITORY,
    LINK_TO_EXCLUDED_CONTENT,
    LINK_TO_SENSITIVE_FILE,
    SELF_DIRS,
    SELF_FILES,
    SELF_REPORT_FILES,
    WORKSPACE_MANIFESTS,
    _resolves_outside_root,
    _target_relative,
    entry_named_exactly,
    glossary_link_refusal,
    is_sensitive,
    symlink_content_refusal,
)
from glossabet.corpus.walk_budget import (
    BUDGET_PATH_SAMPLE,
    EXCLUSION_KINDS,
    MAX_DIRECTORY_ENTRIES,
    MAX_FILE_BYTES,
    MAX_SOURCE_BYTES,
    MAX_SOURCE_FILES,
    MAX_WALK_ENTRIES,
    SKIPPED_SELF_GLOSSARIES,
    BudgetLimits,
    BudgetSkipped,
    BudgetUsed,
    CorpusBudget,
    CorpusBudgetEvidence,
    ExclusionKind,
    PathReasonSample,
    SkippedPaths,
    WalkRemainder,
    exclusion_sentences,
)

__all__ = [
    # Orchestration owners.
    "CODE_LANGUAGES", "DOC_EXTENSIONS", "PACKAGE_MANIFESTS",
    "MONOREPO_SUBROOT_THRESHOLD", "MONOREPO_CODE_FILE_THRESHOLD",
    "MonorepoEvidence", "WalkResult", "walk_repository", "detect_monorepo",
    # Compatibility exports owned by glossabet.corpus.path_policy.
    "LINK_ESCAPES_REPOSITORY", "LINK_TO_EXCLUDED_CONTENT",
    "LINK_TO_SENSITIVE_FILE", "SELF_DIRS", "SELF_FILES", "SELF_REPORT_FILES",
    "WORKSPACE_MANIFESTS", "entry_named_exactly", "glossary_link_refusal",
    "is_sensitive", "symlink_content_refusal",
    # Compatibility exports owned and read by glossabet.corpus.walk_budget;
    # scanner aliases are not a second source for runtime bounds.
    "BUDGET_PATH_SAMPLE", "EXCLUSION_KINDS", "MAX_DIRECTORY_ENTRIES",
    "MAX_FILE_BYTES", "MAX_SOURCE_BYTES", "MAX_SOURCE_FILES",
    "MAX_WALK_ENTRIES", "SKIPPED_SELF_GLOSSARIES", "BudgetLimits",
    "BudgetSkipped", "BudgetUsed", "CorpusBudget", "CorpusBudgetEvidence",
    "ExclusionKind", "PathReasonSample", "SkippedPaths", "WalkRemainder",
    "exclusion_sentences",
]

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

PACKAGE_MANIFESTS = frozenset({
    "package.json", "pyproject.toml", "setup.py", "Cargo.toml", "go.mod",
    "pom.xml", "build.gradle", "dune-project", "mix.exs", "Gemfile",
})
MONOREPO_SUBROOT_THRESHOLD = 3
MONOREPO_CODE_FILE_THRESHOLD = 5000


class MonorepoEvidence(TypedDict):
    """The persisted ``monorepo`` section."""

    detected: bool
    reasons: list[str]
    sub_roots: list[str]


@dataclass
class WalkResult:
    # (repository-relative path, language, configured/default role)
    code_files: list[tuple[str, str, str]] = field(default_factory=list)
    # (repository-relative path, configured/default role)
    doc_files: list[tuple[str, str]] = field(default_factory=list)
    other_files: int = 0
    # One list per EXCLUSION_KINDS entry, by that entry's ``attribute``.
    skipped_sensitive: list[str] = field(default_factory=list)
    skipped_oversized: list[str] = field(default_factory=list)
    skipped_symlinks: list[str] = field(default_factory=list)
    skipped_symlinks_to_excluded: list[str] = field(default_factory=list)
    skipped_symlinked_directories: list[str] = field(default_factory=list)
    skipped_unreadable: list[str] = field(default_factory=list)
    skipped_configured: list[str] = field(default_factory=list)
    skipped_generated: list[str] = field(default_factory=list)
    skipped_vendored: list[str] = field(default_factory=list)
    skipped_self_glossaries: list[str] = field(default_factory=list)
    skipped_self_reports: list[str] = field(default_factory=list)
    sub_roots: list[str] = field(default_factory=list)
    workspace_manifests: list[str] = field(default_factory=list)
    corpus_budget: CorpusBudget = field(default_factory=CorpusBudget)

    def skipped_as_evidence(self) -> SkippedPaths:
        """The path exclusions of ``evidence["skipped"]``, keyed and sorted
        as the ledger dictates (the caller adds its non-walk entries). Spelled
        in ``EXCLUSION_KINDS`` order; ``test_scanner`` pins the two."""
        return {
            "sensitive": sorted(self.skipped_sensitive),
            "oversized": sorted(self.skipped_oversized),
            "symlinks_escaping_repo": sorted(self.skipped_symlinks),
            "symlinks_to_excluded_content": sorted(
                self.skipped_symlinks_to_excluded
            ),
            "symlinked_directories": sorted(self.skipped_symlinked_directories),
            "unreadable": sorted(self.skipped_unreadable),
            "configured": sorted(self.skipped_configured),
            "generated": sorted(self.skipped_generated),
            "vendored": sorted(self.skipped_vendored),
            "self_glossaries": sorted(self.skipped_self_glossaries),
            "self_reports": sorted(self.skipped_self_reports),
        }


def _record_role_skip(result: WalkResult, relative: str, role: str) -> None:
    target = (
        result.skipped_generated if role == "generated"
        else result.skipped_vendored
    )
    target.append(relative)


def _bounded_directory_entries(
    path: Path, relative: str, budget: CorpusBudget
) -> list[os.DirEntry[str]] | None:
    """Return a deterministic directory snapshot within the per-dir ceiling.

    If a directory crosses the ceiling, skip it as a whole. Selecting the first
    entries returned by the filesystem would be bounded but nondeterministic;
    all-or-nothing preserves the evidence determinism contract.
    """
    entries: list[os.DirEntry[str]] = []
    try:
        with os.scandir(path) as iterator:
            for entry in iterator:
                if budget.directory_snapshot_full(len(entries)):
                    budget.truncate_directory(relative)
                    return None
                entries.append(entry)
    except OSError:
        # An unlistable directory has an unknown number of entries: the walk
        # is no longer exact, and says so, rather than reading as complete.
        budget.truncate_walk(relative, 0, "unreadable-directory")
        return None
    return sorted(entries, key=lambda entry: entry.name)


def _partition_entries(
    entries: list[os.DirEntry[str]],
) -> tuple[list[tuple[os.DirEntry[str], bool]], list[os.DirEntry[str]]]:
    """Split one directory snapshot into (directories, files).

    Directories carry whether they are reached through a symlink; symlinked
    directories are classified but never descended into.
    """
    directories: list[tuple[os.DirEntry[str], bool]] = []
    files: list[os.DirEntry[str]] = []
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
    return directories, files


def _classify_directories(
    directories: list[tuple[os.DirEntry[str], bool]],
    file_count: int,
    rel_dir: str,
    is_root: bool,
    root: Path,
    config: RepositoryConfig,
    result: WalkResult,
) -> tuple[list[tuple[Path, str]], bool]:
    """Classify one snapshot's subdirectories.

    Returns the subdirectories to descend into and whether the repository
    walk-entry budget was exhausted mid-snapshot.
    """
    kept: list[tuple[Path, str]] = []
    for index, (entry, is_directory_symlink) in enumerate(directories):
        name = entry.name
        relative = name if is_root else f"{rel_dir}/{name}"
        # Generated tool namespaces are not repository evidence. Prune
        # them before charging the cross-repository walk counter so the
        # first scan and later scans remain identical after Glossabet
        # creates its own output directory. The enclosing directory's
        # bounded scandir snapshot still limits the work needed to find
        # these fixed names.
        if name in SELF_DIRS:
            continue
        if result.corpus_budget.walk_entries_exhausted:
            result.corpus_budget.truncate_walk(
                rel_dir,
                len(directories) - index + file_count,
                "walk-entry-limit",
            )
            return kept, True
        result.corpus_budget.walk_entries += 1
        # After fixed tool namespaces, sensitive classification precedes
        # every repository-controlled prune so the exclusion is recorded
        # before any later prune (mirrors the file rule).
        if is_sensitive(name):
            result.skipped_sensitive.append(relative)
            continue
        if config.is_ignored(relative):
            result.skipped_configured.append(relative)
            continue
        if name.startswith("."):
            continue
        role = config.role_for(relative, is_dir=True)
        if (
            role in EXCLUDED_CONTENT_ROLES
            and not config.has_explicit_descendant(relative)
        ):
            _record_role_skip(result, relative, role)
            continue
        if is_directory_symlink:
            if _resolves_outside_root(entry.path, root):
                result.skipped_symlinks.append(relative)
            else:
                result.skipped_symlinked_directories.append(relative)
            continue
        kept.append((Path(entry.path), relative))
    return kept, False


def _classify_files(
    files: list[os.DirEntry[str]],
    rel_dir: str,
    is_root: bool,
    root: Path,
    config: RepositoryConfig,
    result: WalkResult,
) -> bool:
    """Route one snapshot's files into the walk result.

    Returns whether the repository walk-entry budget was exhausted
    mid-snapshot.
    """
    for index, entry in enumerate(files):
        fname = entry.name
        rel = fname if is_root else f"{rel_dir}/{fname}"
        if fname in SELF_FILES:
            result.skipped_self_glossaries.append(rel)
            continue
        if fname in SELF_REPORT_FILES:
            result.skipped_self_reports.append(rel)
            continue
        if result.corpus_budget.walk_entries_exhausted:
            result.corpus_budget.truncate_walk(
                rel_dir,
                len(files) - index,
                "walk-entry-limit",
            )
            return True
        result.corpus_budget.walk_entries += 1
        # After the fixed glossary filename, sensitive classification
        # precedes the hidden-file skip so the exclusion is recorded before
        # that later prune.
        if is_sensitive(fname):
            result.skipped_sensitive.append(rel)
            continue
        if config.is_ignored(rel):
            result.skipped_configured.append(rel)
            continue
        if fname.startswith(".") and fname not in WORKSPACE_MANIFESTS:
            continue
        role = config.role_for(rel)
        if role in EXCLUDED_CONTENT_ROLES:
            _record_role_skip(result, rel, role)
            continue
        if is_root and fname in WORKSPACE_MANIFESTS:
            result.workspace_manifests.append(fname)
        ext = os.path.splitext(fname)[1].lower()
        full = entry.path
        if ext not in CODE_LANGUAGES and ext not in DOC_EXTENSIONS:
            result.other_files += 1
            continue
        try:
            entry_info = entry.stat(follow_symlinks=False)
        except OSError as exc:
            result.skipped_unreadable.append(rel)
            if exc.errno != errno.ENOENT:
                result.corpus_budget.skip_source(
                    rel, 0, "unreadable", production=role == "production"
                )
            continue
        is_link = stat.S_ISLNK(entry_info.st_mode)
        if not is_link and not stat.S_ISREG(entry_info.st_mode):
            # Opening a FIFO can block indefinitely and devices/sockets are
            # not repository text. Only a regular file, or a link whose
            # regular target passes the content rules below, is source.
            result.skipped_unreadable.append(rel)
            result.corpus_budget.skip_source(
                rel, 0, "not-regular-file", production=role == "production"
            )
            continue
        if is_link:
            # The name check above sees only the link's own name; the shared
            # content rule also classifies the resolved target.
            refusal = symlink_content_refusal(full, root, config)
            if refusal == LINK_ESCAPES_REPOSITORY:
                result.skipped_symlinks.append(rel)
                continue
            if refusal == LINK_TO_SENSITIVE_FILE:
                result.skipped_sensitive.append(rel)
                continue
            if refusal == LINK_TO_EXCLUDED_CONTENT:
                result.skipped_symlinks_to_excluded.append(rel)
                continue
            # The content is the target's, so its role is the target's too:
            # ``src/data.py -> tests/fixtures/data.py`` is fixture content,
            # ``tests/x.py -> src/x.py`` is production content.
            target = _target_relative(full, root)
            if target is not None:
                role = config.role_for(target)
        try:
            content_info = os.stat(full) if is_link else entry_info
        except OSError as exc:
            result.skipped_unreadable.append(rel)
            if exc.errno != errno.ENOENT:
                # A real source-extension file the walk cannot stat (EACCES)
                # is inventory that went unread: charge the corpus ledger so
                # ``complete``/``production_complete`` turn false. A dangling
                # link (ENOENT) is not source and only needs the ledger.
                result.corpus_budget.skip_source(
                    rel, 0, "unreadable", production=role == "production"
                )
            continue
        if not stat.S_ISREG(content_info.st_mode):
            result.skipped_unreadable.append(rel)
            result.corpus_budget.skip_source(
                rel, 0, "not-regular-file", production=role == "production"
            )
            continue
        size = content_info.st_size
        refusal = result.corpus_budget.source_refusal(size)
        if refusal is not None:
            if refusal == "file-size-limit":
                result.skipped_oversized.append(rel)
            result.corpus_budget.skip_source(
                rel, size, refusal, production=role == "production"
            )
            continue
        result.corpus_budget.include_source(rel, size)
        if ext in CODE_LANGUAGES:
            result.code_files.append((rel, CODE_LANGUAGES[ext], role))
        else:
            result.doc_files.append((rel, role))
    return False


def walk_repository(root: Path, config: RepositoryConfig) -> WalkResult:
    result = WalkResult()
    root = root.resolve()
    pending: list[tuple[Path, str]] = [(root, ".")]
    while pending:
        dirpath, rel_dir = pending.pop()
        entries = _bounded_directory_entries(dirpath, rel_dir, result.corpus_budget)
        if entries is None:
            continue
        is_root = rel_dir == "."
        directories, files = _partition_entries(entries)
        kept_dirs, exhausted = _classify_directories(
            directories, len(files), rel_dir, is_root, root, config, result
        )
        if exhausted:
            break
        filenames = [entry.name for entry in files]
        if (
            not is_root
            and any(m in filenames for m in PACKAGE_MANIFESTS)
            # A fixture or test-data package (``tests/fixtures/x/package.json``)
            # is scaffolding, not a sub-project of the repository.
            and config.role_for(rel_dir, is_dir=True) == "production"
        ):
            result.sub_roots.append(rel_dir)
        if _classify_files(files, rel_dir, is_root, root, config, result):
            break
        pending.extend(reversed(kept_dirs))
    return result


def _read_root_manifest(
    root: Path, path: Path, walk: WalkResult, config: RepositoryConfig
) -> str | None:
    """Read a root manifest under the same bounds as walked source files."""
    rel = path.name
    if rel in (
        set(walk.skipped_configured)
        | set(walk.skipped_generated)
        | set(walk.skipped_vendored)
    ):
        return None
    if path.is_symlink():
        refusal = symlink_content_refusal(str(path), root, config)
        if refusal == LINK_ESCAPES_REPOSITORY and rel not in walk.skipped_symlinks:
            walk.skipped_symlinks.append(rel)
        if refusal is not None:
            return None
    if not path.is_file():
        return None
    try:
        if walk.corpus_budget.oversized(path.stat().st_size):
            if rel not in walk.skipped_oversized:
                walk.skipped_oversized.append(rel)
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _root_workspace_config(
    root: Path, walk: WalkResult, config: RepositoryConfig
) -> list[str]:
    """Workspace declarations that need bounded inspection at the root."""
    reasons = []
    cargo = root / "Cargo.toml"
    cargo_text = _read_root_manifest(root, cargo, walk, config)
    if cargo_text is not None and "[workspace]" in cargo_text:
        reasons.append("Cargo.toml declares [workspace]")
    pkg = root / "package.json"
    package_text = _read_root_manifest(root, pkg, walk, config)
    if package_text is not None:
        try:
            data = json.loads(package_text)
            if isinstance(data, dict) and "workspaces" in data:
                reasons.append("package.json declares workspaces")
        except (ValueError, RecursionError):
            pass
    return reasons


def detect_monorepo(
    root: Path, walk: WalkResult, config: RepositoryConfig
) -> MonorepoEvidence:
    reasons = [f"workspace manifest {m}" for m in sorted(walk.workspace_manifests)]
    reasons += _root_workspace_config(root.resolve(), walk, config)
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
