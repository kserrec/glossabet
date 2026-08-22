"""Repository walk: path roles, exclusions, and monorepo detection.

Sensitive and self-output exclusions are non-overridable trust boundaries.
Repository configuration can add ignores or override conservative path roles;
tests and fixtures stay inventoried, while generated and vendored content is
pruned before a lexical read and reported.
"""

from __future__ import annotations

import errno
import json
import os
import re
from collections.abc import Mapping, Sized
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from glossabet.corpus.config import EXCLUDED_CONTENT_ROLES, RepositoryConfig
from glossabet.runtime.artifacts import REPORT_FILE

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
        r"\.(pem|key|p12|pfx|jks|keystore|der|p8|ppk|kdbx|asc|gpg|pgp)$",
        r"^id_(rsa|dsa|ecdsa|ed25519)$",
        r"^\.(netrc|npmrc|pypirc|htpasswd|dockercfg)$",
        r"secret", r"credential",
    )
]

# Tool artifacts, not repo content: glossabet's own outputs (so the glossary
# can't echo through the evidence and blind drift detection) and graphify's
# outputs (so its generated reports can't leak into doc vocabulary — the
# graph is consumed through the adapter, never the lexical walk).
SELF_DIRS = frozenset({
    "glossabet-out",
    ".glossabet",
    # Pre-rename artifacts remain excluded so an old local run cannot echo
    # back into evidence after upgrading to Glossabet.
    "glossarize-out",
    ".glossarize",
    "graphify-out",
})
# Excluded at any depth: a monorepo sub-project's settled glossary echoes
# through evidence exactly like the root one would.
SELF_FILES = frozenset({"GLOSSARY.md"})
# Also excluded at any depth, for a different reason: GLOSSARY.md is
# maintainer-authored and is kept out so Glossabet can validate it
# independently; GLOSSABET.md is Glossabet's own derived vocabulary-health
# report (written by the skill at the scan root), kept out because a report's
# proposed names, explanations, and open questions must never count as
# repository vocabulary for the report's next run. Neither is a Glossabet
# machine-state file: deleting either changes no canonical state.
SELF_REPORT_FILES = frozenset({REPORT_FILE})

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


def _resolves_outside_root(full: str, root: Path) -> bool:
    """True if the path's real target lies outside the repo root."""
    try:
        Path(os.path.realpath(full)).relative_to(root)
    except ValueError:
        return True
    return False


# The one content rule for a symlinked repository path, shared by the walk
# and by root GLOSSARY.md discovery (which must declare readable exactly what
# the walk would have read — the skill reads what the engine declares
# readable). Reasons are the reported vocabulary of both.
LINK_ESCAPES_REPOSITORY = "symlink-escapes-repository"
LINK_TO_SENSITIVE_FILE = "symlink-to-sensitive-file"
LINK_TO_EXCLUDED_CONTENT = "symlink-to-excluded-content"


def _target_relative(full: str, root: Path) -> str | None:
    """The link target's repository-relative POSIX path, or ``None`` when it
    resolves outside the root."""
    try:
        return Path(os.path.realpath(full)).relative_to(root).as_posix()
    except ValueError:
        return None


def entry_named_exactly(root: Path, name: str) -> bool | None:
    """Whether ``root`` holds a directory entry spelled exactly ``name`` — as
    the walk's fixed-name rules see it — not a path lookup, which on a
    case-insensitive filesystem would also find ``glossary.md`` or
    ``agents.md``, files the walk treats as ordinary evidence. The path lookup
    is the cheap fast path (absent → done, no directory scan); the exact-name
    confirmation iterates ``scandir`` under the walk-entry cap instead of
    materializing the whole listing, so a root with millions of entries costs
    no memory.

    Returns True/False when the answer is known, and None when something is
    there but its exact name could not be confirmed (the root cannot be
    listed, or the cap was reached first). Callers never report None as
    absent: a false absence claim is the one failure to avoid.
    """
    if not os.path.lexists(os.path.join(root, name)):
        return False
    try:
        with os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_WALK_ENTRIES:
                    return None
                if entry.name == name:
                    return True
    except OSError:
        return None
    return False


def glossary_link_refusal(full: str, root: Path) -> str | None:
    """Why a symlinked root ``GLOSSARY.md`` may not be read as the repository
    glossary, or ``None``. The discovery channel exists to read that file,
    so only the rules that protect *what* is read apply: an escaping target,
    a sensitive target, or Glossabet's own output posing as the glossary. A
    link into ``docs/GLOSSARY.md`` or a hidden/vendored directory is the
    maintainers' choice and is followed."""
    target = _target_relative(full, root)
    if target is None:
        return LINK_ESCAPES_REPOSITORY
    parts = target.split("/")
    if any(is_sensitive(part) for part in parts):
        return LINK_TO_SENSITIVE_FILE
    if any(part in SELF_DIRS for part in parts[:-1]) or parts[-1] in SELF_REPORT_FILES:
        return LINK_TO_EXCLUDED_CONTENT
    return None


def symlink_content_refusal(
    full: str, root: Path, config: RepositoryConfig | None = None
) -> str | None:
    """Why a symlinked path is not repository content, or ``None`` when its
    confined target may be read like an ordinary file.

    A link resolving outside the repo is not repo content: reading it would
    ingest arbitrary host files into evidence (``os.walk``'s
    ``followlinks=False`` guards dirs, not files). A link with an innocent
    name pointing at content every other rule excludes (``notes.py -> .env``,
    ``x.md -> GLOSSARY.md``, ``y.js -> node_modules/...``) would otherwise
    launder that content into evidence, so the resolved target's complete
    repository-relative path is classified by the same rules the walk applies
    to the paths it meets directly: sensitive names anywhere in the path,
    Glossabet's own directories and files, hidden components, configured
    ignores, and generated/vendored roles (``config`` supplies the last two;
    without it those two rules are not applied).
    """
    target = _target_relative(full, root)
    if target is None:
        return LINK_ESCAPES_REPOSITORY
    parts = target.split("/")
    directories, name = parts[:-1], parts[-1]
    if any(is_sensitive(part) for part in parts):
        return LINK_TO_SENSITIVE_FILE
    if (
        any(part in SELF_DIRS for part in directories)
        or name in SELF_FILES
        or name in SELF_REPORT_FILES
        or any(part.startswith(".") for part in directories)
        or (name.startswith(".") and name not in WORKSPACE_MANIFESTS)
    ):
        return LINK_TO_EXCLUDED_CONTENT
    if config is not None and (
        config.is_ignored(target)
        or config.role_for(target) in EXCLUDED_CONTENT_ROLES
    ):
        return LINK_TO_EXCLUDED_CONTENT
    return None


class PathReasonSample(TypedDict):
    """One ``{path, reason}`` record of a budget sample."""

    path: str
    reason: str


class MonorepoEvidence(TypedDict):
    """The persisted ``monorepo`` section."""

    detected: bool
    reasons: list[str]
    sub_roots: list[str]


@dataclass
class CorpusBudget:
    walk_entries: int = 0
    source_files: int = 0
    source_bytes: int = 0
    skipped_source_files: int = 0
    skipped_source_bytes: int = 0
    skipped_production_source_files: int = 0
    skipped_sample: list[PathReasonSample] = field(default_factory=list)
    walk_truncated: bool = False
    walk_truncations: int = 0
    minimum_entries_omitted: int = 0
    walk_sample: list[PathReasonSample] = field(default_factory=list)
    # Walk-time size of every admitted file, so a later read failure
    # reclassifies exactly the bytes that were charged (a fresh stat could
    # differ, or fail, if the file changed or vanished in between).
    admitted_sizes: dict[str, int] = field(default_factory=dict)

    def include_source(self, relative: str, size: int) -> None:
        self.source_files += 1
        self.source_bytes += size
        self.admitted_sizes[relative] = size

    def skip_source(
        self,
        relative: str,
        size: int,
        reason: str,
        *,
        production: bool,
    ) -> None:
        self.skipped_source_files += 1
        self.skipped_source_bytes += size
        if production:
            self.skipped_production_source_files += 1
        if len(self.skipped_sample) < BUDGET_PATH_SAMPLE:
            self.skipped_sample.append({"path": relative, "reason": reason})

    def reclassify_unread(
        self,
        relative: str,
        reason: str,
        *,
        production: bool,
    ) -> None:
        """Move one walk-admitted file to the skipped ledger.

        The walk admits files by stat alone; a later read failure means the
        file never actually joined the corpus. Keeping it on both sides
        would make used + skipped exceed the inventory, and the bytes moved
        are the ones the walk charged.
        """
        size = self.admitted_sizes.pop(relative, 0)
        self.source_files -= 1
        self.source_bytes -= size
        self.skip_source(relative, size, reason, production=production)

    def truncate_walk(
        self, relative: str, minimum_omitted: int, reason: str
    ) -> None:
        self.walk_truncated = True
        self.walk_truncations += 1
        self.minimum_entries_omitted += minimum_omitted
        if len(self.walk_sample) < BUDGET_PATH_SAMPLE:
            self.walk_sample.append({"path": relative, "reason": reason})

    def as_evidence(self) -> dict[str, object]:
        complete = not self.walk_truncated and not self.skipped_source_files
        production_complete = (
            not self.walk_truncated
            and not self.skipped_production_source_files
        )
        return {
            "complete": complete,
            "production_complete": production_complete,
            "limits": {
                "file_bytes": MAX_FILE_BYTES,
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
                "production_source_files": (
                    self.skipped_production_source_files
                ),
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


@dataclass(frozen=True)
class ExclusionKind:
    """One reason the walk leaves a path out of lexical evidence: its stable
    key under ``evidence["skipped"]``, the ``WalkResult`` list that collects
    it, and the sentence the scan reports it with. Every exclusion is
    reported — capped or filtered output never reads as complete — and this
    ledger is the only place the key, the sentence, and the collection are
    spelled, so adding a kind is one entry here."""
    key: str
    attribute: str
    sentence: str  # ``{n}`` is the path count


EXCLUSION_KINDS: tuple[ExclusionKind, ...] = (
    ExclusionKind("sensitive", "skipped_sensitive",
                  "excluded {n} sensitive path(s) from evidence"),
    ExclusionKind("oversized", "skipped_oversized",
                  "skipped {n} oversized file(s) (>2MB)"),
    ExclusionKind("symlinks_escaping_repo", "skipped_symlinks",
                  "skipped {n} symlink(s) resolving outside the repository"),
    # A confined link whose target the walk itself would exclude (Glossabet's
    # own files, hidden, ignored, generated, vendored): the target's own
    # exclusion is what applies, reported here so it is never silent.
    ExclusionKind("symlinks_to_excluded_content",
                  "skipped_symlinks_to_excluded",
                  "skipped {n} symlink(s) whose target is excluded content"),
    # A confined directory symlink is never descended into (its real path is
    # walked); reported so the non-descent is not silent.
    ExclusionKind("symlinked_directories", "skipped_symlinked_directories",
                  "did not descend into {n} symlinked director(ies) inside "
                  "the repository (content is read at its real path, if that "
                  "path is not itself excluded)"),
    # Entries the walk met but could not stat or read at all: dangling
    # links, permission denied. Not source evidence and not silently gone.
    ExclusionKind("unreadable", "skipped_unreadable",
                  "skipped {n} unreadable path(s) (dangling link or "
                  "permission denied)"),
    ExclusionKind("configured", "skipped_configured",
                  "ignored {n} configured path(s)"),
    ExclusionKind("generated", "skipped_generated",
                  "excluded {n} generated path(s) from lexical analysis"),
    ExclusionKind("vendored", "skipped_vendored",
                  "excluded {n} vendored path(s) from lexical analysis"),
    # Every GLOSSARY.md the walk saw and excluded (root and nested), so the
    # self-file exclusion is never silent; the root file's safe discovery is
    # a separate channel (glossabet.repository_glossary).
    ExclusionKind("self_glossaries", "skipped_self_glossaries",
                  "excluded {n} GLOSSARY.md file(s) from lexical evidence "
                  "(never evidence for itself)"),
    # Every GLOSSABET.md the walk saw and excluded (root and nested):
    # derived Glossabet report output.
    ExclusionKind("self_reports", "skipped_self_reports",
                  "excluded {n} GLOSSABET.md report(s) from lexical evidence "
                  "(derived Glossabet output)"),
)
SKIPPED_SELF_GLOSSARIES = "self_glossaries"


def exclusion_sentences(skipped: Mapping[str, Sized]) -> list[str]:
    """Human sentences for every non-empty exclusion kind in an evidence
    ``skipped`` section, in ledger order."""
    return [
        kind.sentence.format(n=len(skipped[kind.key]))
        for kind in EXCLUSION_KINDS
        if skipped.get(kind.key)
    ]


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

    def skipped_as_evidence(self) -> dict[str, list[str]]:
        """The path exclusions of ``evidence["skipped"]``, keyed and sorted
        as the ledger dictates (the caller adds its non-walk entries)."""
        return {
            kind.key: sorted(getattr(self, kind.attribute))
            for kind in EXCLUSION_KINDS
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
                if len(entries) >= MAX_DIRECTORY_ENTRIES:
                    budget.truncate_walk(
                        relative,
                        MAX_DIRECTORY_ENTRIES + 1,
                        "directory-entry-limit",
                    )
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
        if result.corpus_budget.walk_entries >= MAX_WALK_ENTRIES:
            result.corpus_budget.truncate_walk(
                rel_dir,
                len(directories) - index + file_count,
                "walk-entry-limit",
            )
            return kept, True
        result.corpus_budget.walk_entries += 1
        # After fixed tool namespaces, sensitive classification precedes
        # every repository-controlled prune so the exclusion is reported,
        # never silent (mirrors the file rule).
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
        if result.corpus_budget.walk_entries >= MAX_WALK_ENTRIES:
            result.corpus_budget.truncate_walk(
                rel_dir,
                len(files) - index,
                "walk-entry-limit",
            )
            return True
        result.corpus_budget.walk_entries += 1
        # After the fixed glossary filename, sensitive classification
        # precedes the hidden-file skip so exclusions are reported rather
        # than silently dropped.
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
        if os.path.islink(full):
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
            size = os.path.getsize(full)
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
        if size > MAX_FILE_BYTES:
            result.skipped_oversized.append(rel)
            result.corpus_budget.skip_source(
                rel,
                size,
                "file-size-limit",
                production=role == "production",
            )
            continue
        if result.corpus_budget.source_files >= MAX_SOURCE_FILES:
            result.corpus_budget.skip_source(
                rel,
                size,
                "source-file-limit",
                production=role == "production",
            )
            continue
        if result.corpus_budget.source_bytes + size > MAX_SOURCE_BYTES:
            result.corpus_budget.skip_source(
                rel,
                size,
                "source-byte-limit",
                production=role == "production",
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
        if refusal is not None:  # escaping, sensitive, or Glossabet's own output
            return None
    if not path.is_file():
        return None
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
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
