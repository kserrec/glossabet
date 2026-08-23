"""Open one repository command under an explicit glossary policy.

Every repository command opens a run first. A user error while opening —
not a directory, unreadable or invalid glossary, or a required glossary that
is absent — becomes one ``RunError``. The CLI reports that error through its
ordinary artifact boundary, so command modules do not repeat the policy.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from glossabet.glossary.model import GlossaryDocument
from glossabet.glossary.store import GLOSSARY_FILE, GlossaryError, load_glossary
from glossabet.runtime.artifacts import OUT_DIR, ArtifactError

GLOSSARY_NONE = "none"          # the command never reads the glossary
GLOSSARY_OPTIONAL = "optional"  # absent is fine; malformed is a user error
GLOSSARY_REQUIRED = "required"  # absent is a user error too


class RunError(ArtifactError):
    """A user error that stops the command before it does any work."""


@dataclass(frozen=True)
class Run:
    """A resolved repository root and the glossary selected by its policy."""

    root: Path
    glossary: GlossaryDocument | None

    @property
    def required_glossary(self) -> GlossaryDocument:
        """Return the glossary after a required-glossary run was opened."""
        if self.glossary is None:
            raise RunError("this command requires a glossary")
        return self.glossary


def open_run(
    path_arg: str, *, glossary: str = GLOSSARY_NONE, missing: str = ""
) -> Run:
    """Resolve ``path_arg`` and apply the requested glossary policy.

    ``missing`` is the leading clause of the required-but-absent message,
    such as ``"no glossary to validate"``. The rest of the message tells the
    user how to create one.
    """
    root = Path(path_arg)
    try:
        root_mode = root.stat().st_mode
    except PermissionError:
        raise
    except OSError:
        raise RunError("not a directory: " + path_arg) from None
    if not stat.S_ISDIR(root_mode):
        raise RunError("not a directory: " + path_arg)
    root = root.resolve()
    if OUT_DIR in root.parts:
        # Glossabet's output directory is never a repository: scanning it
        # would write glossabet-out/glossabet-out/... and read its own
        # artifacts as evidence.
        raise RunError(
            f"{path_arg} is inside a {OUT_DIR}/ output directory; "
            "run glossabet on the repository root instead"
        )
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
