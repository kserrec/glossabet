"""One command preamble: resolve the repository root and decide, in one
place, whether this command needs a glossary and how a bad or missing one
is reported.

Every repository command opens a run first. A user error while opening —
not a directory, unreadable/invalid glossary, required glossary missing —
is one ``RunError``, an ``ArtifactError`` that `cli` reports through
``print_error`` and maps to exit 1. Command modules never re-spell that.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from glossabet.artifacts import OUT_DIR, ArtifactError
from glossabet.glossary import GLOSSARY_FILE, GlossaryError, load_glossary

GLOSSARY_NONE = "none"          # the command never reads the glossary
GLOSSARY_OPTIONAL = "optional"  # absent is fine; malformed is a user error
GLOSSARY_REQUIRED = "required"  # absent is a user error too


class RunError(ArtifactError):
    """A user error that stops the command before it does any work."""


@dataclass(frozen=True)
class Run:
    """An opened command run: the resolved root and the loaded glossary
    (``None`` when the command asked for none, or for optional and none
    exists)."""

    root: Path
    glossary: dict | None


def open_run(
    path_arg: str, *, glossary: str = GLOSSARY_NONE, missing: str = ""
) -> Run:
    """Open a run on ``path_arg`` under the given glossary policy.

    ``missing`` is the leading clause of the required-but-absent message,
    e.g. "no glossary to validate"; the sentence that follows tells the user
    how to create one.
    """
    root = Path(path_arg)
    if not root.is_dir():
        raise RunError("not a directory: " + path_arg)
    root = root.resolve()
    if glossary == GLOSSARY_NONE:
        return Run(root, None)
    try:
        loaded = load_glossary(root)
    except GlossaryError as exc:
        raise RunError(str(exc)) from exc
    if loaded is None and glossary == GLOSSARY_REQUIRED:
        raise RunError(
            f"{missing} — run /glossabet and settle terms first "
            f"({OUT_DIR}/{GLOSSARY_FILE})"
        )
    return Run(root, loaded)
