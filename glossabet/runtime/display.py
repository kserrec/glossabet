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
# Characters that render as nothing yet make two strings distinct — a
# spoofing and silent-duplicate vector in identity fields, and a way to hide
# text from the human whose approval is the product's trust anchor while a
# model still reads it. This is Unicode's Default_Ignorable_Code_Point
# property (zero-width space/joiners, soft hyphen, BOM, Hangul fillers,
# Mongolian vowel separator, interlinear annotation, variation selectors,
# the TAG block, ...) rather than an enumeration, so a variation is not one
# code point away. ZWNJ/ZWJ (U+200C/U+200D) are excluded on purpose: they are
# legitimate inside Persian, Indic, and emoji text.
_DEFAULT_IGNORABLE_RANGES = (
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160),
    (0x17B4, 0x17B5), (0x180B, 0x180F), (0x200B, 0x200B), (0x200E, 0x200F),
    (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164), (0xFE00, 0xFE0F),
    (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF),
)


def _is_default_ignorable(codepoint: int) -> bool:
    return any(start <= codepoint <= end for start, end in _DEFAULT_IGNORABLE_RANGES)


def is_terminal_control(character: str) -> bool:
    """Whether one character can alter terminal state or visual ordering."""
    codepoint = ord(character)
    return (
        codepoint < 0x20
        or 0x7F <= codepoint <= 0x9F
        # A lone surrogate (from a JSON \udXXX escape or a surrogate-escaped
        # non-UTF-8 filename) cannot be encoded by any UTF-8 stream.
        or 0xD800 <= codepoint <= 0xDFFF
        or character in _BIDI_FORMAT_CHARACTERS
        or character in _LINE_SEPARATORS
        or _is_default_ignorable(codepoint)
        # Interlinear annotation anchors/separators (Cf, not in the
        # default-ignorable list) hide their annotation text likewise.
        or 0xFFF9 <= codepoint <= 0xFFFB
    )


# Default-ignorable characters that are ordinary display hints inside prose
# (emoji presentation "❤️" = U+2764 U+FE0F, keycaps, Mongolian free variation
# selectors) but still spoof-capable in an identity field: allowed in prose,
# refused in terms/ids/aliases/paths.
_PROSE_TOLERATED = frozenset(chr(cp) for cp in (
    0xFE0E, 0xFE0F, 0x180B, 0x180C, 0x180D,
))


def first_terminal_control(text: str, *, allow_layout: bool = False) -> str | None:
    """The first unsafe terminal-facing character in ``text``, or ``None``.

    Human prose may deliberately contain a line feed, a tab, or an emoji
    presentation selector; identity fields (terms, ids, paths, and bindings)
    may contain none of them.
    """
    for character in text:
        if allow_layout and (character in "\n\t" or character in _PROSE_TOLERATED):
            continue
        if is_terminal_control(character):
            return character
    return None


def contains_terminal_control(text: str, *, allow_layout: bool = False) -> bool:
    """Return whether ``text`` contains unsafe terminal-facing characters."""
    return first_terminal_control(text, allow_layout=allow_layout) is not None


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
        # A piped/redirected stdout on Windows is encoded with the ANSI code
        # page (cp1252, cp932, ...) with strict errors: one em dash or accented
        # letter would raise and read as an internal defect. Anything the
        # stream cannot encode is rendered as a visible escape instead.
        encoding = getattr(self._stream, "encoding", None)
        if encoding:
            try:
                safe.encode(encoding)
            except UnicodeEncodeError:
                safe = safe.encode(encoding, "backslashreplace").decode(
                    encoding, "replace"
                )
            except LookupError:
                pass  # an unknown codec name: nothing we can pre-check
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
