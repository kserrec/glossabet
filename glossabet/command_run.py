"""Open one repository command under an explicit glossary policy.

Every repository command opens a run first. A user error while opening —
not a directory, unreadable or invalid glossary, or a required glossary that
is absent — becomes one ``RunError``. The CLI reports that error through its
ordinary artifact boundary, so command modules do not repeat the policy.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from glossabet.corpus.path_policy import entry_named_exactly
from glossabet.glossary.model import GlossaryDocument
from glossabet.glossary.store import GLOSSARY_FILE, GlossaryError, load_glossary
from glossabet.runtime.artifacts import OUT_DIR, ArtifactError

GLOSSARY_NONE = "none"          # the command never reads the glossary
GLOSSARY_OPTIONAL = "optional"  # absent is fine; malformed is a user error
GLOSSARY_REQUIRED = "required"  # absent is a user error too

# Exact current files are the narrow proof that a similarly named ancestor is
# Glossabet-owned output. The directory name alone cannot claim an arbitrary
# user path, and no artifact content is read to make this boundary decision.
_OUTPUT_ARTIFACT_NAMES = frozenset(
    {"drift.json", "evidence.json", "glossary.json", "validation.json"}
)


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


def _has_output_artifact(directory: Path) -> bool | None:
    """Whether one exact regular current artifact proves tool ownership."""
    uncertain = False
    for artifact_name in sorted(_OUTPUT_ARTIFACT_NAMES):
        exact_name = entry_named_exactly(directory, artifact_name)
        if exact_name is True:
            try:
                artifact = (directory / artifact_name).lstat()
            except OSError:
                # The confirmed entry vanished or became uninspectable before
                # its kind could be checked. That race proves neither state.
                uncertain = True
                continue
            if stat.S_ISREG(artifact.st_mode):
                return True
        if exact_name is None:
            uncertain = True
    return None if uncertain else False


def _inside_glossabet_output(root: Path) -> bool | None:
    """Whether a named ancestor is proven to be current Glossabet output.

    ``None`` means an apparent artifact or required filesystem identity could
    not be confirmed. Identity is needed only for a case-preserved spelling;
    an exact lowercase component already names the path Glossabet addresses.
    """
    uncertain = False
    for ancestor in (root, *root.parents):
        if ancestor.name.casefold() != OUT_DIR.casefold():
            continue
        artifact_state = _has_output_artifact(ancestor)
        if artifact_state is None:
            uncertain = True
            continue
        if not artifact_state:
            continue
        if ancestor.name == OUT_DIR:
            return True
        try:
            expected_name = (ancestor.parent / OUT_DIR).lstat()
        except FileNotFoundError:
            # A differently cased physical name on a case-sensitive
            # filesystem is not the directory Glossabet addresses as OUT_DIR.
            continue
        except OSError:
            uncertain = True
            continue
        if not stat.S_ISDIR(expected_name.st_mode):
            # Artifact writes reject every symlink component. A lowercase
            # symlink (or other non-directory entry) therefore cannot bind a
            # differently cased directory to Glossabet's output path.
            continue
        try:
            actual_name = ancestor.lstat()
        except OSError:
            uncertain = True
            continue
        if not stat.S_ISDIR(actual_name.st_mode):
            # ``root.resolve()`` produced a real directory. A different kind
            # here means it changed during inspection, so neither state is
            # proven.
            uncertain = True
            continue
        if expected_name.st_ino == 0 or actual_name.st_ino == 0:
            # ``samestat`` compares only st_dev/st_ino. Some supported
            # platforms report zero when file identity is unavailable; two
            # unknown identities comparing equal is not proof of sameness.
            uncertain = True
            continue
        if not os.path.samestat(expected_name, actual_name):
            # Both case variants can coexist on a case-sensitive filesystem;
            # only the exact lowercase lookup's directory is tool-owned.
            continue
        return True
    return None if uncertain else False


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
    output_state = _inside_glossabet_output(root)
    if output_state is None:
        raise RunError(
            f"cannot confirm whether {path_arg} is inside a {OUT_DIR}/ output "
            "directory because output-directory ownership could not be proved "
            "from the required artifact and filesystem identity checks"
        )
    if output_state:
        # Proven Glossabet output is never a repository: scanning it would
        # write glossabet-out/glossabet-out/... and read its own artifacts as
        # evidence.
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
