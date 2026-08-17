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

from glossabet.scanner import MAX_FILE_BYTES, _resolves_outside_root

REPOSITORY_GLOSSARY_FILE = "GLOSSARY.md"
MAX_REPOSITORY_GLOSSARY_BYTES = MAX_FILE_BYTES
# Phase 32: the divergence check does one folded substring search per settled
# term or alias against the (≤ 2 MB) Markdown. The term count is capped so the
# work stays linear in the document; a capped run says so (`complete: false`)
# and never reads as a clean bill.
MAX_DIVERGENCE_TERMS = 2_000
SUPERSEDED_ALIAS_STATUSES = frozenset({"alias", "discouraged", "deprecated"})

REASON_SYMLINK_ESCAPES = "symlink-escapes-repository"
REASON_NOT_REGULAR = "not-a-regular-file"
REASON_OVERSIZED = "oversized"
REASON_UNREADABLE = "unreadable"


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


def _read_repository_glossary(root: Path) -> tuple[dict, bytes | None]:
    """Discovery record plus the complete bytes when — and only when — the
    file was read safely and completely."""
    root = root.resolve()
    path = root / REPOSITORY_GLOSSARY_FILE
    full = str(path)
    if not os.path.lexists(full):
        return {"present": False}, None
    if os.path.islink(full) and _resolves_outside_root(full, root):
        return _unreadable(REASON_SYMLINK_ESCAPES, None), None
    if not os.path.isfile(full):
        return _unreadable(REASON_NOT_REGULAR, None), None
    try:
        with open(full, "rb") as handle:
            payload = handle.read(MAX_REPOSITORY_GLOSSARY_BYTES + 1)
    except OSError:
        return _unreadable(REASON_UNREADABLE, None), None
    if len(payload) > MAX_REPOSITORY_GLOSSARY_BYTES:
        try:
            size: int | None = os.path.getsize(full)
        except OSError:
            size = None
        return _unreadable(REASON_OVERSIZED, size), None
    return {
        "present": True,
        "path": REPOSITORY_GLOSSARY_FILE,
        "readable": True,
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


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


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
    text = _fold(payload.decode("utf-8", errors="replace"))
    missing: list[str] = []
    superseded: list[dict] = []
    checked = 0
    skipped = 0
    for concept in sorted(glossary["concepts"], key=lambda c: c["id"]):
        if concept.get("status") != "canonical":
            continue
        term = concept["term"]
        entries: list[tuple[str, str | None]] = [(term, None)]
        for alias in concept.get("aliases", []):
            if alias.get("status") in SUPERSEDED_ALIAS_STATUSES:
                entries.append((alias["term"], alias["status"]))
        canonical_present: bool | None = None
        for candidate, alias_status in entries:
            if checked >= MAX_DIVERGENCE_TERMS:
                skipped += 1
                continue
            checked += 1
            present = _fold(candidate) in text
            if alias_status is None:
                canonical_present = present
                if not present:
                    missing.append(term)
            elif present and canonical_present is False:
                superseded.append(
                    {
                        "concept": concept["id"],
                        "term": candidate,
                        "status": alias_status,
                        "canonical_term": term,
                    }
                )
    return {
        "canonical_missing_from_markdown": sorted(missing),
        "superseded_terms_still_present": superseded,
        "checked_terms": checked,
        "skipped_terms": skipped,
        "complete": skipped == 0,
        "term_cap": MAX_DIVERGENCE_TERMS,
    }


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
