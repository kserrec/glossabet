"""Bounded, read-only ambient vocabulary text from the validated glossary."""

from __future__ import annotations

import hashlib
import json
import sys

from glossabet.artifacts import ArtifactError, repo_root
from glossabet.display import escape_terminal_text
from glossabet.glossary import (
    GLOSSARY_SCHEMA_VERSION,
    GlossaryError,
    concept_scope,
    load_glossary,
)


BRIEF_FORMAT_VERSION = 1
MAX_BRIEF_BYTES = 4_096
MAX_BRIEF_ENTRY_BYTES = 1_024
MIN_BRIEF_ENTRY_BYTES = 32
_ELLIPSIS = "…"


class BriefError(ArtifactError):
    """A safe vocabulary brief could not be produced within its contract."""


def _git_stamp(root):
    """Lazy test seam around the hardened repository Git-state probe."""
    from glossabet.evidence import _git_stamp as evidence_git_stamp

    return evidence_git_stamp(root)


def _utf8_size(text: str) -> int:
    return len(text.encode("utf-8"))


def _truncate_utf8(text: str, limit: int) -> tuple[str, bool]:
    """Return a valid UTF-8 prefix with a visible marker when bytes are dropped."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    marker = _ELLIPSIS.encode("utf-8")
    if limit < len(marker):
        return "", True
    prefix = encoded[: limit - len(marker)].decode("utf-8", errors="ignore")
    return prefix + _ELLIPSIS, True


def _one_line(text: str) -> str:
    """Collapse allowed prose layout while retaining terminal-safe text."""
    return escape_terminal_text(" ".join(text.split()))


def glossary_sha256(glossary: dict) -> str:
    """Return the semantic digest used to bind every vocabulary projection."""
    canonical = json.dumps(
        glossary,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _git_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str) and value:
        return escape_terminal_text(value)
    return "unavailable"


def _entry_sort_key(concept: dict) -> tuple[str, str, str]:
    term = concept["term"]
    return (term.casefold(), term, concept["id"])


def _alias_sort_key(alias: dict) -> tuple[str, str, str]:
    term = alias["term"]
    return (term.casefold(), term, alias["status"])


def _render_entry(concept: dict, byte_limit: int) -> tuple[str, bool]:
    """Render one canonical concept without exceeding its assigned byte budget."""
    parts: list[str] = []
    truncated = False

    def append(piece: str) -> bool:
        nonlocal parts, truncated
        candidate = "".join(parts) + piece
        rendered, was_truncated = _truncate_utf8(candidate, byte_limit - 1)
        if was_truncated:
            parts = [rendered]
            truncated = True
            return False
        parts.append(piece)
        return True

    term = escape_terminal_text(concept["term"])
    definition = _one_line(concept["definition"])
    if not append(f"- {term} — {definition}"):
        return "".join(parts) + "\n", truncated

    scope = concept_scope(concept)
    scope_text = (
        "repository"
        if scope is None
        else ", ".join(escape_terminal_text(prefix) for prefix in scope)
    )
    if not append(f" | scope: {scope_text}"):
        return "".join(parts) + "\n", truncated

    aliases = sorted(concept.get("aliases", []), key=_alias_sort_key)
    if aliases:
        if not append(" | aliases: "):
            return "".join(parts) + "\n", truncated
        for index, alias in enumerate(aliases):
            separator = ", " if index else ""
            alias_term = escape_terminal_text(alias["term"])
            alias_status = escape_terminal_text(alias["status"])
            if not append(f"{separator}{alias_term} [{alias_status}]"):
                break
    return "".join(parts) + "\n", truncated


def _coverage_line(
    included: int,
    total: int,
    entries_truncated: int,
) -> str:
    omitted = total - included
    complete = omitted == 0 and entries_truncated == 0
    return (
        "coverage: complete="
        + ("true" if complete else "false")
        + f"; canonical_included={included}/{total}"
        + f"; canonical_omitted={omitted}"
        + f"; entries_truncated={entries_truncated}"
        + f"; max_bytes={MAX_BRIEF_BYTES}\n"
    )


def _build_digest(glossary: dict, state_line: str) -> str:
    """Build one bounded vocabulary projection with a caller-owned stamp."""
    canonical = sorted(
        (
            concept
            for concept in glossary["concepts"]
            if concept["status"] == "canonical"
        ),
        key=_entry_sort_key,
    )
    total = len(canonical)
    header = (
        f"Glossabet vocabulary brief v{BRIEF_FORMAT_VERSION}\n"
        "policy: read-only; vocabulary changes require a human /glossabet session\n"
        f"glossary: schema={GLOSSARY_SCHEMA_VERSION}; "
        f"sha256={glossary_sha256(glossary)}; canonical={total}\n"
        + state_line
    )
    if _utf8_size(header) + _utf8_size(_coverage_line(0, total, 0)) > MAX_BRIEF_BYTES:
        raise BriefError("vocabulary brief metadata exceeds its output limit")

    body: list[str] = []
    body_bytes = 0
    entries_truncated = 0
    included = 0
    header_bytes = _utf8_size(header)
    for concept in canonical:
        # Reserve the largest footer this entry can require before assigning
        # the remaining output bytes to the entry itself.
        worst_footer = _coverage_line(included + 1, total, entries_truncated + 1)
        available = (
            MAX_BRIEF_BYTES
            - header_bytes
            - body_bytes
            - _utf8_size(worst_footer)
        )
        entry_limit = min(MAX_BRIEF_ENTRY_BYTES, available)
        if entry_limit < MIN_BRIEF_ENTRY_BYTES:
            break
        entry, truncated = _render_entry(concept, entry_limit)
        next_truncated = entries_truncated + int(truncated)
        next_included = included + 1
        footer = _coverage_line(next_included, total, next_truncated)
        if (
            header_bytes
            + body_bytes
            + _utf8_size(entry)
            + _utf8_size(footer)
            > MAX_BRIEF_BYTES
        ):
            break
        body.append(entry)
        body_bytes += _utf8_size(entry)
        entries_truncated = next_truncated
        included = next_included

    output = header + "".join(body) + _coverage_line(
        included, total, entries_truncated
    )
    if _utf8_size(output) > MAX_BRIEF_BYTES:
        raise BriefError(
            f"vocabulary brief exceeds its {MAX_BRIEF_BYTES}-byte output limit"
        )
    return output


def build_brief(glossary: dict, git_stamp: dict) -> str:
    """Build deterministic ambient text from one already validated glossary."""
    return _build_digest(
        glossary,
        f"git: head={_git_value(git_stamp.get('head'))}; "
        f"dirty={_git_value(git_stamp.get('dirty'))}\n",
    )


def build_managed_brief(glossary: dict) -> str:
    """Build the stable projection embedded in a managed host-context block.

    A persistent file cannot truthfully carry live Git dirtiness: writing the
    file would change that state immediately. Its durable freshness boundary
    is therefore the semantic glossary digest, which is also repeated in the
    managed-block metadata.
    """
    return _build_digest(
        glossary,
        "sync: semantic glossary snapshot; refresh with glossabet sync-context\n",
    )


def brief_command(path_arg: str) -> int:
    """Print current canonical vocabulary without scanning or writing the repo."""
    root = repo_root(path_arg)
    if root is None:
        return 1
    try:
        glossary = load_glossary(root)
    except GlossaryError as exc:
        print("glossabet: " + escape_terminal_text(str(exc)), file=sys.stderr)
        return 1
    if glossary is None:
        return 0
    print(build_brief(glossary, _git_stamp(root)), end="")
    return 0
