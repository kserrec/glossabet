"""The exact managed block Glossabet may place in a host instruction file.

Two modules need this and neither may depend on the other: ``context_sync``
(the command that writes the block) and ``evidence`` (the scanner's read
path, which must strip the block from root ``AGENTS.md``/``CLAUDE.md`` so
Glossabet's own generated vocabulary text never counts as repository
evidence). The markers, the metadata stamp, the block regex, and the host
file names live here, beneath both.
"""

from __future__ import annotations

import re

MANAGED_BLOCK_FORMAT_VERSION = 1

# Which agent host owns which context file. sync-context writes only the
# root file; evidence stripping applies to a file of that name at ANY depth,
# because a subproject's own sync-context block would otherwise echo its
# canonical vocabulary into the parent repository's scan.
AGENT_TARGETS = {
    "codex": "AGENTS.md",
    "claude": "CLAUDE.md",
}

# Stripping compares the file name case-insensitively: on a case-insensitive
# filesystem ``agents.md`` may carry a block once written as ``AGENTS.md``,
# and stripping is the safe direction.
_TARGET_NAMES_FOLDED = frozenset(name.lower() for name in AGENT_TARGETS.values())

START_MARKER = "<!-- glossabet:managed-context:start -->"
END_MARKER = "<!-- glossabet:managed-context:end -->"
MARKER_PREFIX = "<!-- glossabet:managed-context"
METADATA_RE = re.compile(
    r"<!-- glossabet:managed-context "
    r"format=(?P<format>[0-9]{1,9}) "
    r"glossary-sha256=(?P<glossary>[0-9a-f]{64}) "
    r"content-sha256=(?P<content>[0-9a-f]{64}) -->"
)
# A leading UTF-8 BOM is not part of the first line: a fresh host file has
# its block at byte 0, and a BOM-adding editor round-trip must not make it
# unrepairable.
BLOCK_RE = re.compile(
    rf"(?m)^\ufeff?{re.escape(START_MARKER)}\r?\n"
    rf"(?P<metadata>{METADATA_RE.pattern})\r?\n"
    rf"(?P<body>.*?)"
    rf"^{re.escape(END_MARKER)}(?=\r?$)",
    re.DOTALL,
)


def strip_managed_context_for_evidence(relative: str, text: str) -> str:
    """Remove one exactly bounded managed block from host-file evidence
    (``AGENTS.md``/``CLAUDE.md`` at any depth).

    The surrounding hand-written instructions remain lexical evidence.
    Whenever the two exact outer markers each occur once, the region between
    them is removed — even if the stamp inside was edited or the layout is
    one drift/validate would call malformed (trailing text after a marker,
    a metadata line the analyzer rejects). That is the safe direction:
    canonical vocabulary must never echo into evidence, and drift/validate
    report a malformed layout separately. Only a file with no marker pair, or
    duplicated/unmatched markers (no single unambiguous region), is left
    untouched.
    """
    if relative.rsplit("/", 1)[-1].lower() not in _TARGET_NAMES_FOLDED:
        return text
    if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
        return text
    start = text.find(START_MARKER)
    end = text.find(END_MARKER, start + len(START_MARKER))
    if start < 0 or end < 0:
        return text
    end += len(END_MARKER)
    return text[:start] + text[end:]
