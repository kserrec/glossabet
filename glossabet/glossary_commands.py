"""The `show` and `save` commands over the persistent glossary."""

from __future__ import annotations

import sys

from glossabet.artifacts import (
    MAX_JSON_BYTES,
    OUT_DIR,
    READ_OVERSIZED,
    ArtifactError,
    parse_bounded_json,
)
from glossabet.display import escape_terminal_text, print_error
from glossabet.engine_run import GLOSSARY_OPTIONAL, open_run
from glossabet.glossary import (
    GLOSSARY_FILE,
    GlossaryError,
    concept_scope,
    save_glossary,
)


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


def _print_glossary(glossary: dict) -> None:
    concepts = sorted(glossary["concepts"], key=lambda c: c["id"])
    by_status: dict[str, list[dict]] = {}
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
                print(
                    "    scope: "
                    + ", ".join(escape_terminal_text(path) for path in scope)
                )
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


def _read_glossary_from_stdin() -> dict | None:
    """One bounded glossary JSON document from standard input, or ``None``
    after reporting why there is none usable."""
    if sys.stdin.isatty():
        print(
            "glossabet: save requires one glossary JSON document on "
            "standard input",
            file=sys.stderr,
        )
        return None
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    try:
        raw = stream.read(MAX_JSON_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        print(
            "glossabet: cannot read glossary JSON from standard input: "
            + escape_terminal_text(str(exc)),
            file=sys.stderr,
        )
        return None
    parsed = parse_bounded_json(raw, MAX_JSON_BYTES)
    if parsed.status == READ_OVERSIZED:
        print(
            "glossabet: glossary JSON on standard input is larger than "
            f"{MAX_JSON_BYTES} bytes",
            file=sys.stderr,
        )
        return None
    if not parsed.ok:
        print(
            "glossabet: glossary JSON on standard input is unreadable ("
            + escape_terminal_text(parsed.error) + ")",
            file=sys.stderr,
        )
        return None
    return parsed.value


def save_command(path_arg: str) -> int:
    """Validate JSON from stdin and persist it through the safe writer."""
    run = open_run(path_arg)
    document = _read_glossary_from_stdin()
    if document is None:
        return 1
    try:
        path = save_glossary(run.root, document)
    except (GlossaryError, ArtifactError) as exc:
        print_error(exc)
        return 1
    print("saved glossary: " + escape_terminal_text(str(path)))
    return 0
