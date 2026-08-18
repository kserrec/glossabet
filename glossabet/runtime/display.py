"""Terminal-safe rendering for repository-controlled text.

Repositories can choose file names, glossary text, Graphify labels, and error
payloads.  None of those values may be allowed to write terminal control or
bidirectional-format characters verbatim.  The command entry point wraps both
standard streams so even an unexpected exception is rendered safely.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator, TextIO


_BIDI_FORMAT_CHARACTERS = frozenset(
    {
        "\u061c",  # ARABIC LETTER MARK
        "\u200e",  # LEFT-TO-RIGHT MARK
        "\u200f",  # RIGHT-TO-LEFT MARK
        "\u202a",  # LEFT-TO-RIGHT EMBEDDING
        "\u202b",  # RIGHT-TO-LEFT EMBEDDING
        "\u202c",  # POP DIRECTIONAL FORMATTING
        "\u202d",  # LEFT-TO-RIGHT OVERRIDE
        "\u202e",  # RIGHT-TO-LEFT OVERRIDE
        "\u2066",  # LEFT-TO-RIGHT ISOLATE
        "\u2067",  # RIGHT-TO-LEFT ISOLATE
        "\u2068",  # FIRST STRONG ISOLATE
        "\u2069",  # POP DIRECTIONAL ISOLATE
    }
)
_LINE_SEPARATORS = frozenset({"\u2028", "\u2029"})


def is_terminal_control(character: str) -> bool:
    """Whether one character can alter terminal state or visual ordering."""
    codepoint = ord(character)
    return (
        codepoint < 0x20
        or 0x7F <= codepoint <= 0x9F
        or character in _BIDI_FORMAT_CHARACTERS
        or character in _LINE_SEPARATORS
    )


def contains_terminal_control(text: str, *, allow_layout: bool = False) -> bool:
    """Return whether ``text`` contains unsafe terminal-facing characters.

    Human prose may deliberately contain a line feed or tab; identity fields
    (terms, ids, paths, and bindings) may not contain either.
    """
    for character in text:
        if allow_layout and character in "\n\t":
            continue
        if is_terminal_control(character):
            return True
    return False


def escape_terminal_text(text: str, *, preserve_line_feeds: bool = False) -> str:
    """Render unsafe characters as visible ASCII escape spellings."""
    rendered: list[str] = []
    for character in text:
        if preserve_line_feeds and character == "\n":
            rendered.append(character)
            continue
        if not is_terminal_control(character):
            rendered.append(character)
            continue
        codepoint = ord(character)
        if character == "\n":
            rendered.append("\\n")
        elif character == "\r":
            rendered.append("\\r")
        elif character == "\t":
            rendered.append("\\t")
        elif codepoint <= 0xFF:
            rendered.append(f"\\x{codepoint:02x}")
        elif codepoint <= 0xFFFF:
            rendered.append(f"\\u{codepoint:04x}")
        else:
            rendered.append(f"\\U{codepoint:08x}")
    return "".join(rendered)


def join_escaped(values, separator: str = ", ") -> str:
    """Join repository-controlled strings for one terminal line, escaping each."""
    return separator.join(escape_terminal_text(value) for value in values)


def print_error(error: object) -> None:
    """Print one command error to stderr with unsafe characters escaped."""
    print("glossabet: " + escape_terminal_text(str(error)), file=sys.stderr)


class _SafeTerminalStream:
    """Text stream proxy that neutralizes controls in every write."""

    _glossabet_terminal_safe = True

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        safe = escape_terminal_text(text, preserve_line_feeds=True)
        return self._stream.write(safe)

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


@contextmanager
def safe_terminal_streams() -> Iterator[None]:
    """Protect stdout/stderr for one complete CLI invocation."""
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    stdout = (
        original_stdout
        if getattr(original_stdout, "_glossabet_terminal_safe", False)
        else _SafeTerminalStream(original_stdout)
    )
    stderr = (
        original_stderr
        if getattr(original_stderr, "_glossabet_terminal_safe", False)
        else _SafeTerminalStream(original_stderr)
    )
    try:
        sys.stdout = stdout
        sys.stderr = stderr
        yield
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
