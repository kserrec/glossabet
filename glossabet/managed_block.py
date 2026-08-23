"""The dependency-free managed-context block format.

Agent context management writes and inspects the block, while corpus
extraction strips the block before treating host instructions as evidence.
This root module lets those independent features share the exact wire format
without either feature depending on the other.
"""

from __future__ import annotations

import re

MANAGED_BLOCK_FORMAT_VERSION = 1

# sync-context writes only the root file. Evidence stripping applies to a
# matching file at any depth because a subproject's managed vocabulary must
# not echo into its parent repository's scan.
AGENT_TARGETS = {
    "codex": "AGENTS.md",
    "claude": "CLAUDE.md",
}

# A case-insensitive filesystem may retain a differently cased spelling of a
# previously written target. Stripping is the conservative direction.
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
# its block at byte 0, and a BOM-adding editor round-trip must remain repairable.
BLOCK_RE = re.compile(
    rf"(?m)^\ufeff?{re.escape(START_MARKER)}\r?\n"
    rf"(?P<metadata>{METADATA_RE.pattern})\r?\n"
    rf"(?P<body>.*?)"
    rf"^{re.escape(END_MARKER)}(?=\r?$)",
    re.DOTALL,
)


def strip_managed_context_for_evidence(relative: str, text: str) -> str:
    """Remove one exactly bounded managed block from host-file evidence.

    Hand-written surrounding instructions remain evidence. If each outer
    marker occurs exactly once, the bounded region is removed even when its
    metadata or layout is malformed. That is conservative: generated
    canonical vocabulary must never echo into evidence, while managed-context
    inspection reports malformed layout separately. Ambiguous marker layouts
    are left untouched.
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
