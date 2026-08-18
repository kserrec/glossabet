"""Per-file extraction for the evidence build: read a source file, extract
its lexical entry (identifiers and imports for code, words for docs), and
reuse a valid cache entry instead of re-extracting when one exists.

`build_evidence` folds the entries this module returns into the scan's
vocabularies; this module knows nothing about the evidence schema."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from glossabet.corpus.cache import entry_if_valid
from glossabet.corpus.imports import extract_imports
from glossabet.agent.managed_block import strip_managed_context_for_evidence
from glossabet.corpus.tokenize import doc_words, iter_identifiers


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


def extract_code_entry(text: str, language: str) -> dict:
    identifiers: Counter = Counter()
    for name in iter_identifiers(text, language):
        identifiers[name] += 1
    return {
        "kind": "code",
        "language": language,
        "identifiers": dict(sorted(identifiers.items())),
        "imports": extract_imports(text, language),
    }


def extract_doc_entry(text: str) -> dict:
    words = doc_words(text)
    counts = Counter(words)
    return {
        "kind": "doc",
        "words": dict(sorted(counts.items())),
        "word_total": len(words),
    }


class SourceExtractor:
    """Extract inventoried files one at a time, reusing the cache when valid.

    ``code_entry`` / ``doc_entry`` return the file's entry (with
    ``content_sha256`` and ``size`` attached) or ``None`` when the file could
    not be read — in which case the corpus budget has already been told, so
    the omission is confessed rather than silently dropped. ``cache_files``
    collects every entry for the next cache save; ``reused`` / ``extracted``
    count how each entry was obtained.
    """

    def __init__(self, root: Path, cached: dict | None, corpus_budget) -> None:
        self._root = root
        self._cached = cached
        self._budget = corpus_budget
        self.cache_files: dict[str, dict] = {}
        self.reused = 0
        self.extracted = 0

    def code_entry(self, rel: str, language: str, role: str) -> dict | None:
        return self._entry(
            rel, "code", role, lambda text: extract_code_entry(text, language)
        )

    def doc_entry(self, rel: str, role: str) -> dict | None:
        return self._entry(rel, "doc", role, extract_doc_entry)

    def _entry(self, rel: str, kind: str, role: str, extractor) -> dict | None:
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
        content, content_sha256, text = source
        entry = entry_if_valid(self._cached, rel, kind, content_sha256)
        if entry is None:
            if kind == "doc":
                text = strip_managed_context_for_evidence(rel, text)
            entry = extractor(text)
            self.extracted += 1
        else:
            entry = dict(entry)
            self.reused += 1
        entry["content_sha256"] = content_sha256
        entry["size"] = len(content)
        self.cache_files[rel] = entry
        return entry
