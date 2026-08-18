"""Regenerate ``glossabet/corpus/unicode_marks.py`` from the running
interpreter's Unicode data. Run only when the project deliberately moves to
a newer Unicode version — the table is a static literal so tokenization is
identical across every supported Python."""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "glossabet" / "corpus" / "unicode_marks.py"


def mark_ranges() -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = prev = None
    for codepoint in range(sys.maxunicode + 1):
        if unicodedata.category(chr(codepoint)) in ("Mn", "Mc", "Me"):
            if start is None:
                start = codepoint
            prev = codepoint
        elif start is not None:
            ranges.append((start, prev))
            start = None
    if start is not None:
        ranges.append((start, prev))
    return ranges


def main() -> int:
    ranges = mark_ranges()
    text = TARGET.read_text(encoding="utf-8")
    head, _, tail = text.partition("MARK_RANGES: tuple[tuple[int, int], ...] = (\n")
    _, _, tail = tail.partition("\n)\n")
    rows = []
    for index in range(0, len(ranges), 4):
        chunk = ranges[index:index + 4]
        rows.append("    " + ", ".join(f"(0x{a:04X}, 0x{b:04X})" for a, b in chunk) + ",")
    head = head.replace(
        head[head.index('UNICODE_VERSION = "'):head.index('"\n', head.index('UNICODE_VERSION = "')) + 2],
        f'UNICODE_VERSION = "{unicodedata.unidata_version}"\n',
    )
    TARGET.write_text(
        head + "MARK_RANGES: tuple[tuple[int, int], ...] = (\n" + "\n".join(rows) + "\n)\n" + tail,
        encoding="utf-8",
    )
    print(f"wrote {len(ranges)} ranges for Unicode {unicodedata.unidata_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
