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

# Which agent host owns which root context file. Only these two exact root
# names are ever written by sync-context or stripped from evidence.
AGENT_TARGETS = {
    "codex": "AGENTS.md",
    "claude": "CLAUDE.md",
}

START_MARKER = "<!-- glossabet:managed-context:start -->"
END_MARKER = "<!-- glossabet:managed-context:end -->"
MARKER_PREFIX = "<!-- glossabet:managed-context"
METADATA_RE = re.compile(
    r"<!-- glossabet:managed-context "
    r"format=(?P<format>[0-9]{1,9}) "
    r"glossary-sha256=(?P<glossary>[0-9a-f]{64}) "
    r"content-sha256=(?P<content>[0-9a-f]{64}) -->"
)
BLOCK_RE = re.compile(
    rf"(?m)^{re.escape(START_MARKER)}\r?\n"
    rf"(?P<metadata>{METADATA_RE.pattern})\r?\n"
    rf"(?P<body>.*?)"
    rf"^{re.escape(END_MARKER)}(?=\r?$)",
    re.DOTALL,
)


def strip_managed_context_for_evidence(relative: str, text: str) -> str:
    """Remove one exactly bounded managed block from root host-file evidence.

    The surrounding hand-written instructions remain lexical evidence. Even a
    body whose stamp was edited is removed when its two exact outer markers
    still define one unambiguous region; malformed marker layouts are left
    untouched and separately flagged by drift/validate.
    """
    if relative not in AGENT_TARGETS.values():
        return text
    if text.count(START_MARKER) != 1 or text.count(END_MARKER) != 1:
        return text
    start = text.find(START_MARKER)
    end = text.find(END_MARKER, start + len(START_MARKER))
    if start < 0 or end < 0:
        return text
    end += len(END_MARKER)
    return text[:start] + text[end:]
