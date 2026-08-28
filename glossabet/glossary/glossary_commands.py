"""The `show` and `save` commands over the persistent glossary."""

from __future__ import annotations

import sys

from glossabet.command_run import GLOSSARY_OPTIONAL, open_run
from glossabet.glossary.model import ConceptRecord, GlossaryDocument
from glossabet.glossary.store import (
    GLOSSARY_FILE,
    GlossaryError,
    concept_scope,
    save_glossary,
)
from glossabet.runtime.artifacts import (
    MAX_JSON_BYTES,
    OUT_DIR,
    READ_OVERSIZED,
    ArtifactError,
    parse_bounded_json,
)
from glossabet.runtime.display import escape_terminal_text, join_escaped, print_error


def show_command(path_arg: str) -> int:
    run = open_run(path_arg, glossary=GLOSSARY_OPTIONAL)
    if run.glossary is None:
        print(
            "no glossary yet — run /glossabet and settle terms to create "
            f"{OUT_DIR}/{GLOSSARY_FILE}"
        )
        return 0
    _print_glossary(run.glossary)
    return 0


def _print_glossary(glossary: GlossaryDocument) -> None:
    concepts = sorted(glossary["concepts"], key=lambda c: c["id"])
    by_status: dict[str, list[ConceptRecord]] = {}
    for concept in concepts:
        by_status.setdefault(concept["status"], []).append(concept)
    counts = ", ".join(
        f"{len(v)} {k}" for k, v in sorted(by_status.items())
    )
    print(f"glossary: {counts}")
    for status in ("canonical", "proposed", "deprecated", "discouraged",
                   "alias", "unknown"):
        group = by_status.get(status)
        if not group:
            continue
        print(f"\n== {status} ==")
        for concept in group:
            term = escape_terminal_text(concept["term"])
            definition = escape_terminal_text(concept["definition"])
            print(f"{term} — {definition}")
            scope = concept_scope(concept)
            if scope is not None:
                print("    scope: " + join_escaped(scope))
            for alias in concept.get("aliases", []):
                alias_term = escape_terminal_text(alias["term"])
                alias_status = escape_terminal_text(alias["status"])
                note = (
                    f" ({escape_terminal_text(alias['note'])})"
                    if alias.get("note") else ""
                )
                print(f"    alias: {alias_term} [{alias_status}]{note}")
            if concept.get("notes"):
                print(f"    note: {escape_terminal_text(concept['notes'])}")


def _read_glossary_from_stdin() -> tuple[bool, object]:
    """Return ``(read, value)`` for one bounded, unvalidated JSON document.

    The boolean owns the input channel outcome so a successfully parsed JSON
    ``null`` remains data for the glossary schema validator rather than being
    confused with a read or parse failure.
    """
    if sys.stdin.isatty():
        print_error("save requires one glossary JSON document on standard input")
        return False, None
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    try:
        raw = stream.read(MAX_JSON_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        print_error(f"cannot read glossary JSON from standard input: {exc}")
        return False, None
    parsed = parse_bounded_json(raw, MAX_JSON_BYTES)
    if parsed.status == READ_OVERSIZED:
        print_error(
            "glossary JSON on standard input is larger than "
            f"{MAX_JSON_BYTES} bytes"
        )
        return False, None
    if not parsed.ok:
        print_error(
            f"glossary JSON on standard input is unreadable ({parsed.error})"
        )
        return False, None
    return True, parsed.value


def save_command(path_arg: str) -> int:
    """Validate JSON from stdin and persist it through the safe writer."""
    run = open_run(path_arg)
    read, document = _read_glossary_from_stdin()
    if not read:
        return 1
    try:
        path = save_glossary(run.root, document)
    except (GlossaryError, ArtifactError) as exc:
        print_error(exc)
        return 1
    print("saved glossary: " + escape_terminal_text(str(path)))
    return 0
