"""Corpus budget accounting: the immutable work ceilings, the ledger that
charges and reclassifies admitted files, and the serialized coverage shapes
(``skipped.corpus_budget``, the exclusion ledger, ``evidence["skipped"]``).

Every cap is stated and every drop is reported: capped or filtered output
never reads as complete. The limits are module constants read at call time
so one knob governs the walk, the budget, and the reported ``limits``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sized
from dataclasses import dataclass, field
from typing import TypedDict

MAX_FILE_BYTES = 2_000_000
# Phase 15 calibration: 84 source files / 659,141 bytes took a 0.32-second
# median cold scan on the reference host. These immutable safety ceilings
# retain roughly 119x file and 49x byte headroom while bounding lexical work.
MAX_SOURCE_FILES = 10_000
MAX_SOURCE_BYTES = 32_000_000
MAX_WALK_ENTRIES = 100_000
MAX_DIRECTORY_ENTRIES = 10_000
BUDGET_PATH_SAMPLE = 20


class PathReasonSample(TypedDict):
    """One ``{path, reason}`` record of a budget sample."""

    path: str
    reason: str


class BudgetLimits(TypedDict):
    file_bytes: int
    walk_entries: int
    directory_entries: int
    source_files: int
    source_bytes: int


class BudgetUsed(TypedDict):
    walk_entries: int
    source_files: int
    source_bytes: int


class BudgetSkipped(TypedDict):
    source_files: int
    production_source_files: int
    source_bytes: int
    sample: list[PathReasonSample]
    sample_truncated: bool


class WalkRemainder(TypedDict):
    truncated: bool
    minimum_entries_omitted: int
    exact: bool
    sample: list[PathReasonSample]
    sample_truncated: bool


class CorpusBudgetEvidence(TypedDict):
    """The persisted ``skipped.corpus_budget`` record."""

    complete: bool
    production_complete: bool
    limits: BudgetLimits
    used: BudgetUsed
    skipped: BudgetSkipped
    walk_remainder: WalkRemainder


class SkippedPaths(TypedDict):
    """The walk's path exclusions of ``evidence["skipped"]``: one sorted
    list per ``EXCLUSION_KINDS`` entry, keyed by that entry's ``key``. The
    keys here and the ledger are pinned to each other by a test."""

    sensitive: list[str]
    oversized: list[str]
    symlinks_escaping_repo: list[str]
    symlinks_to_excluded_content: list[str]
    symlinked_directories: list[str]
    unreadable: list[str]
    configured: list[str]
    generated: list[str]
    vendored: list[str]
    self_glossaries: list[str]
    self_reports: list[str]



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

    def as_evidence(self) -> CorpusBudgetEvidence:
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

    # -- inclusion decisions: the one place the ceilings are compared ------

    @property
    def walk_entries_exhausted(self) -> bool:
        """Whether the cross-repository walk-entry ceiling has been reached."""
        return self.walk_entries >= MAX_WALK_ENTRIES

    @staticmethod
    def directory_snapshot_full(entry_count: int) -> bool:
        """Whether one directory listing has reached the per-directory
        ceiling (the snapshot is then abandoned as a whole)."""
        return entry_count >= MAX_DIRECTORY_ENTRIES

    def truncate_directory(self, relative: str) -> None:
        """Record an abandoned over-full directory snapshot: at least
        ``MAX_DIRECTORY_ENTRIES + 1`` entries went unlisted."""
        self.truncate_walk(
            relative, MAX_DIRECTORY_ENTRIES + 1, "directory-entry-limit"
        )

    @staticmethod
    def oversized(size: int) -> bool:
        """Whether one file exceeds the per-file byte ceiling."""
        return size > MAX_FILE_BYTES

    def source_refusal(self, size: int) -> str | None:
        """The budget reason a source file of ``size`` bytes may not join the
        corpus — per-file, source-file, or source-byte ceiling, in that
        order — or ``None`` when it fits."""
        if size > MAX_FILE_BYTES:
            return "file-size-limit"
        if self.source_files >= MAX_SOURCE_FILES:
            return "source-file-limit"
        if self.source_bytes + size > MAX_SOURCE_BYTES:
            return "source-byte-limit"
        return None


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


def exclusion_sentences(skipped: Mapping[str, object]) -> list[str]:
    """Human sentences for every non-empty exclusion kind in an evidence
    ``skipped`` section, in ledger order."""
    sentences = []
    for kind in EXCLUSION_KINDS:
        paths = skipped.get(kind.key)
        if isinstance(paths, Sized) and len(paths):
            sentences.append(kind.sentence.format(n=len(paths)))
    return sentences


