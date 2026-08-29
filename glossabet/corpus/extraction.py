"""Per-file extraction for the evidence build: read a source file, extract
its lexical entry (identifiers and imports for code, words for docs), and
reuse a valid cache entry instead of re-extracting when one exists.

`build_evidence` folds the entries this module returns into the scan's
vocabularies; this module knows nothing about the evidence schema."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from glossabet.corpus.cache import (
    CodeEntry,
    DocEntry,
    cached_code_entry,
    cached_doc_entry,
)
from glossabet.corpus.imports import extract_imports
from glossabet.corpus.tokenize import doc_words, iter_identifiers
from glossabet.managed_block import strip_managed_context_for_evidence


def read_source(path: Path) -> tuple[bytes, str, str] | str:
    """Content, its digest, and its decoded text — or the corpus-budget skip
    reason when the file cannot be read as UTF-8 text.

    A file that is not valid UTF-8 is confessed, never guessed: decoding
    with dropped or replaced bytes would invent identifiers and words
    (``naïve`` → ``nave``) and present them as repository vocabulary.
    """
    try:
        content = path.read_bytes()
    except OSError:
        return "unreadable"
    if b"\0" in content[:1024]:  # binary despite its extension
        return "binary-content"
    try:
        text = content.decode("utf-8-sig")  # a leading BOM is not content
    except UnicodeDecodeError:
        return "not-utf-8"
    return content, hashlib.sha256(content).hexdigest(), text


def extract_code_entry(
    text: str, language: str, *, content_sha256: str, size: int
) -> CodeEntry:
    identifiers: Counter[str] = Counter()
    for name in iter_identifiers(text, language):
        identifiers[name] += 1
    return {
        "kind": "code",
        "language": language,
        "identifiers": dict(sorted(identifiers.items())),
        "imports": extract_imports(text, language),
        "content_sha256": content_sha256,
        "size": size,
    }


def extract_doc_entry(text: str, *, content_sha256: str, size: int) -> DocEntry:
    words = doc_words(text)
    counts = Counter(words)
    return {
        "kind": "doc",
        "words": dict(sorted(counts.items())),
        "word_total": len(words),
        "content_sha256": content_sha256,
        "size": size,
    }


class UnreadReclassifier(Protocol):
    """Move a walk-admitted file that extraction could not read from the
    included corpus budget to the skipped budget."""

    def reclassify_unread(
        self, relative: str, reason: str, *, production: bool
    ) -> None: ...


class SourceExtractor:
    """Extract inventoried files one at a time, reusing the cache when valid.

    ``code_entry`` / ``doc_entry`` return the file's entry (with
    ``content_sha256`` and ``size`` attached) or ``None`` when the file could
    not be read — in which case the corpus budget has already been told, so
    the omission is confessed rather than silently dropped. ``cache_files``
    collects every entry for the next cache save; ``reused`` / ``extracted``
    count how each entry was obtained.
    """

    def __init__(
        self,
        root: Path,
        cached: Mapping[str, object] | None,
        corpus_budget: UnreadReclassifier,
    ) -> None:
        self._root = root
        self._cached = cached
        self._budget = corpus_budget
        self.cache_files: dict[str, CodeEntry | DocEntry] = {}
        self.reused = 0
        self.extracted = 0

    def code_entry(self, rel: str, language: str, role: str) -> CodeEntry | None:
        source = self._read(rel, role)
        if source is None:
            return None
        content, content_sha256, text = source
        entry = cached_code_entry(self._cached, rel, content_sha256)
        if entry is None:
            entry = extract_code_entry(
                text, language, content_sha256=content_sha256, size=len(content)
            )
            self.extracted += 1
        else:
            entry["size"] = len(content)
            self.reused += 1
        self.cache_files[rel] = entry
        return entry

    def doc_entry(self, rel: str, role: str) -> DocEntry | None:
        source = self._read(rel, role)
        if source is None:
            return None
        content, content_sha256, text = source
        entry = cached_doc_entry(self._cached, rel, content_sha256)
        if entry is None:
            text = strip_managed_context_for_evidence(rel, text)
            entry = extract_doc_entry(
                text, content_sha256=content_sha256, size=len(content)
            )
            self.extracted += 1
        else:
            entry["size"] = len(content)
            self.reused += 1
        self.cache_files[rel] = entry
        return entry

    def _read(self, rel: str, role: str) -> tuple[bytes, str, str] | None:
        source = read_source(self._root / rel)
        if isinstance(source, str):
            # An inventoried file the build could not read is an omission
            # the artifact must confess: silence here would let capped or
            # broken evidence read as complete. The walk already admitted
            # the file, so reclassify it from used to skipped rather than
            # counting it on both sides of the ledger.
            self._budget.reclassify_unread(
                rel, source, production=role == "production"
            )
            return None
        return source
