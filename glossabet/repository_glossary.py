"""Safe discovery of a repository's own root ``GLOSSARY.md``.

A hand-maintained ``GLOSSARY.md`` is maintainer-authored evidence of prior
naming intent. It is deliberately *not* lexical evidence (``scanner.SELF_FILES``
keeps it out of vocabulary counts, or the glossary would be evidence for
itself) and it is deliberately *not* Glossabet's structured state
(``glossabet-out/glossary.json``). This module answers only: does the exact
scan root have one, can it be read safely and completely, and what exactly
would be read (size + SHA-256)? No content leaves here — the agent context
carries metadata only, so the skill's independent baseline is built from a
glossary-blind context and reading the Markdown is a deliberate later step.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import unicodedata

from glossabet.artifacts import READ_OVERSIZED, read_bounded_bytes
from glossabet.scanner import (
    MAX_FILE_BYTES,
    MAX_WALK_ENTRIES,
    _resolves_outside_root,
    is_sensitive,
)

REPOSITORY_GLOSSARY_FILE = "GLOSSARY.md"
MAX_REPOSITORY_GLOSSARY_BYTES = MAX_FILE_BYTES
# Phase 32: the divergence check does one folded substring search per settled
# term or alias against the (≤ 2 MB) Markdown. Both factors are capped so the
# work is at most MAX_DIVERGENCE_TERMS × MAX_DIVERGENCE_TEXT_CHARS character
# comparisons (~1–2 s): the term count, and the *normalized* text length —
# NFKC can expand a code point up to 18×, so the bound is applied after
# folding and before any search. A capped run says so (`complete: false`)
# and never reads as a clean bill.
MAX_DIVERGENCE_TERMS = 500
MAX_DIVERGENCE_TEXT_CHARS = 2 * MAX_FILE_BYTES
REASON_TEXT_EXCEEDS_BOUND = "normalized-text-exceeds-bound"
SUPERSEDED_ALIAS_STATUSES = frozenset({"alias", "discouraged", "deprecated"})

REASON_SYMLINK_ESCAPES = "symlink-escapes-repository"
REASON_SYMLINK_SENSITIVE = "symlink-to-sensitive-file"
REASON_NOT_REGULAR = "not-a-regular-file"
REASON_OVERSIZED = "oversized"
REASON_UNREADABLE = "unreadable"
REASON_LISTING_UNCONFIRMED = "root-listing-unconfirmed"


def _unreadable(reason: str, size: int | None) -> dict:
    section: dict = {
        "present": True,
        "path": REPOSITORY_GLOSSARY_FILE,
        "readable": False,
        "reason": reason,
    }
    if size is not None:
        section["bytes"] = size
    return section


def _entry_named_exactly(root: Path, full: str) -> bool | None:
    """Presence is the exact directory-entry name, as in the scanner's
    SELF_FILES exclusion — not a path lookup, which on a case-insensitive
    filesystem would also find "glossary.md", a file the walk still counts as
    ordinary evidence. The path lookup is the cheap fast path (absent → done,
    no directory scan); the exact-name confirmation iterates ``scandir`` under
    the walk-entry cap instead of materializing the whole listing, so a root
    with millions of entries costs no memory.

    Returns True/False when the answer is known, and None when something is
    there but its exact name could not be confirmed (the root cannot be
    listed, or the cap was reached first). None is never reported as absent:
    a false absence claim is the one failure this channel must not produce.
    """
    if not os.path.lexists(full):
        return False
    try:
        with os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_WALK_ENTRIES:
                    return None
                if entry.name == REPOSITORY_GLOSSARY_FILE:
                    return True
    except OSError:
        return None
    return False


def _read_repository_glossary(root: Path) -> tuple[dict, bytes | None]:
    """Discovery record plus the complete bytes when — and only when — the
    file was read safely and completely."""
    root = root.resolve()
    path = root / REPOSITORY_GLOSSARY_FILE
    full = str(path)
    named_exactly = _entry_named_exactly(root, full)
    if named_exactly is False:
        return {"present": False}, None
    if named_exactly is None:
        return _unreadable(REASON_LISTING_UNCONFIRMED, None), None
    if os.path.islink(full):
        # Same two rules as walked files: an escaping link is not repository
        # content, and a link with an innocent name pointing at an in-repo
        # sensitive file (GLOSSARY.md -> .env) would otherwise be declared
        # readable — and the skill reads what the engine declares readable.
        if _resolves_outside_root(full, root):
            return _unreadable(REASON_SYMLINK_ESCAPES, None), None
        if is_sensitive(os.path.basename(os.path.realpath(full))):
            return _unreadable(REASON_SYMLINK_SENSITIVE, None), None
    if not os.path.isfile(full):
        return _unreadable(REASON_NOT_REGULAR, None), None
    read = read_bounded_bytes(full, MAX_REPOSITORY_GLOSSARY_BYTES)
    if read.status == READ_OVERSIZED:
        return _unreadable(REASON_OVERSIZED, read.size), None
    if not read.ok:  # unreadable, or the entry vanished between checks
        return _unreadable(REASON_UNREADABLE, None), None
    payload = read.payload
    return {
        "present": True,
        "path": REPOSITORY_GLOSSARY_FILE,
        "readable": True,
        # Reading through a confined symlink is fine (its target is repository
        # content); *writing* through one is not — the skill must know.
        "symlink": os.path.islink(full),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }, payload


def discover_repository_glossary(root: Path) -> dict:
    """Tri-state description of ``<root>/GLOSSARY.md``.

    - absent → ``{"present": False}``
    - present, safely and completely read → ``present/path/readable=True/
      bytes/sha256`` (digest of the exact bytes read)
    - present but not safely readable → ``present/path/readable=False/
      reason`` (+ ``bytes`` when known); never reported as absent, so a
      partial or refused read can never support an absence claim.

    Presence is judged from the directory entry itself (``lexists``), so a
    dangling or escaping symlink is still *present*. Symlinks follow the
    walked-file rule: confined inside the root they are followed, escaping
    ones are refused. The bound is applied to the bytes actually read
    (``cap + 1``), not to a racy ``stat``.
    """
    return _read_repository_glossary(root)[0]


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def _fold(text: str) -> str:
    """NFKC + casefold, with every whitespace run collapsed to one space so a
    multi-word term still matches when the Markdown hard-wraps it."""
    return _collapse_whitespace(_normalize(text))


def _superseded_aliases(concept: dict) -> list[tuple[str, str]]:
    return [
        (alias["term"], alias["status"])
        for alias in concept.get("aliases", [])
        if alias.get("status") in SUPERSEDED_ALIAS_STATUSES
    ]


def _divergence_result(
    missing: list[str],
    superseded: list[dict],
    checked: int,
    skipped: int,
    reason: str | None = None,
) -> dict:
    result: dict = {
        "canonical_missing_from_markdown": sorted(missing),
        "superseded_terms_still_present": superseded,
        "checked_terms": checked,
        "skipped_terms": skipped,
        "complete": skipped == 0,
    }
    if reason is not None:
        result["reason"] = reason
    result["term_cap"] = MAX_DIVERGENCE_TERMS
    result["text_cap"] = MAX_DIVERGENCE_TEXT_CHARS
    return result


def repository_glossary_divergence(glossary: dict, payload: bytes) -> dict:
    """The one reconciliation signal the engine can give without parsing
    Markdown: is each settled term lexically present in the document?

    ``canonical_missing_from_markdown`` lists canonical concept terms whose
    NFKC+casefold form occurs nowhere in the folded document text.
    ``superseded_terms_still_present`` lists ``alias``/``discouraged``/
    ``deprecated`` alias terms of canonical concepts that *do* occur while
    the concept's canonical term does not — the document still leads with a
    word the structured state has moved past. Presence is a lenient
    substring test (so "payment services" counts as "payment service"):
    the check errs toward *not* reporting a term missing. Definitions are
    never compared and no document structure is inferred; meaning-level
    reconciliation is the skill's job.
    """
    canonical = sorted(
        (c for c in glossary["concepts"] if c.get("status") == "canonical"),
        key=lambda c: c["id"],
    )
    # The bound is judged as early as the expansion can be seen: NFKC can
    # grow a code point 18× and casefold a further 3×, and each of casefold
    # and the whitespace collapse allocates ~170 MB on an already-expanded
    # 12 M-character string. So: NFKC → check → casefold → check → collapse,
    # and only then any search.
    nfkc = unicodedata.normalize(
        "NFKC", payload.decode("utf-8", errors="replace")
    )
    normalized = nfkc.casefold() if len(nfkc) <= MAX_DIVERGENCE_TEXT_CHARS else nfkc
    if len(normalized) > MAX_DIVERGENCE_TEXT_CHARS:
        return _divergence_result(
            [],
            [],
            checked=0,
            skipped=sum(1 + len(_superseded_aliases(c)) for c in canonical),
            reason=REASON_TEXT_EXCEEDS_BOUND,
        )
    text = _collapse_whitespace(normalized)
    missing: list[str] = []
    superseded: list[dict] = []
    checked = 0
    skipped = 0

    def check(candidate: str) -> bool | None:
        """Presence of one term, or None once the term cap is spent."""
        nonlocal checked, skipped
        if checked >= MAX_DIVERGENCE_TERMS:
            skipped += 1
            return None
        checked += 1
        return _fold(candidate) in text

    for concept in canonical:
        term = concept["term"]
        term_present = check(term)
        if term_present is False:
            missing.append(term)
        for alias_term, alias_status in _superseded_aliases(concept):
            if check(alias_term) and term_present is False:
                superseded.append(
                    {
                        "concept": concept["id"],
                        "term": alias_term,
                        "status": alias_status,
                        "canonical_term": term,
                    }
                )
    return _divergence_result(missing, superseded, checked, skipped)


def repository_glossary_section(
    root: Path, evidence: dict, glossary: dict | None = None
) -> dict:
    """The agent-context section: discovery plus nested exclusions.

    ``nested_ignored`` lists every non-root ``GLOSSARY.md`` the walk saw and
    excluded from lexical evidence. They are reported, never consulted or
    merged: only the exact scan root's file is this scan's repository
    glossary. When structured state also exists and the Markdown was read
    completely, ``divergence`` carries the lexical term-presence check; it
    is *absent* (never an empty, clean-looking result) otherwise.
    """
    section, payload = _read_repository_glossary(root)
    if glossary is not None and payload is not None:
        section["divergence"] = repository_glossary_divergence(glossary, payload)
    nested = [
        rel
        for rel in evidence["skipped"]["self_glossaries"]
        if rel != REPOSITORY_GLOSSARY_FILE
    ]
    section["nested_ignored"] = sorted(nested)
    return section
