"""Path trust policy: names that never enter evidence, Glossabet's own
outputs, the exact-name rules of the repository root, and the one content
rule for a symlinked repository path.

These rules sit beneath the walk. They classify names and resolved targets
only; they never read repository content, build evidence, or discover the
repository glossary (that channel depends on them).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from glossabet.corpus import walk_budget
from glossabet.corpus.config import EXCLUDED_CONTENT_ROLES, RepositoryConfig
from glossabet.runtime.artifacts import REPORT_FILE

# Filename patterns that must never enter evidence.
_SENSITIVE_RES = [
    re.compile(p) for p in (
        r"^\.env$", r"\.env$", r"^\.env\.", r"\.env\.",
        r"\.(pem|key|p12|pfx|jks|keystore|der|p8|ppk|kdbx|asc|gpg|pgp)$",
        r"^id_(rsa|dsa|ecdsa|ed25519)$",
        r"^\.(netrc|npmrc|pypirc|htpasswd|dockercfg)$",
        r"secret", r"credential",
    )
]

# Tool artifacts, not repo content: glossabet's own outputs (so the glossary
# can't echo through the evidence and blind drift detection) and graphify's
# outputs (so its generated reports can't leak into doc vocabulary — the
# graph is consumed through the adapter, never the lexical walk).
SELF_DIRS = frozenset({
    "glossabet-out",
    ".glossabet",
    # Pre-rename artifacts remain excluded so an old local run cannot echo
    # back into evidence after upgrading to Glossabet.
    "glossarize-out",
    ".glossarize",
    "graphify-out",
})
# Excluded at any depth: a monorepo sub-project's settled glossary echoes
# through evidence exactly like the root one would.
SELF_FILES = frozenset({"GLOSSARY.md"})
# Also excluded at any depth, for a different reason: GLOSSARY.md is
# maintainer-authored and is kept out so Glossabet can validate it
# independently; GLOSSABET.md is Glossabet's own derived vocabulary-health
# report (written by the skill at the scan root), kept out because a report's
# proposed names, explanations, and open questions must never count as
# repository vocabulary for the report's next run. Neither is a Glossabet
# machine-state file: deleting either changes no canonical state.
SELF_REPORT_FILES = frozenset({REPORT_FILE})

WORKSPACE_MANIFESTS = frozenset({
    "pnpm-workspace.yaml", "lerna.json", "go.work",
    "WORKSPACE", "WORKSPACE.bazel", "MODULE.bazel",
})


def is_sensitive(name: str) -> bool:
    lower = name.lower()
    return any(p.search(lower) for p in _SENSITIVE_RES)


def _resolves_outside_root(full: str, root: Path) -> bool:
    """True if the path's real target lies outside the repo root."""
    try:
        Path(os.path.realpath(full)).relative_to(root)
    except ValueError:
        return True
    return False


# The one content rule for a symlinked repository path, shared by the walk
# and by root GLOSSARY.md discovery (which must declare readable exactly what
# the walk would have read — the skill reads what the engine declares
# readable). Reasons are the reported vocabulary of both.
LINK_ESCAPES_REPOSITORY = "symlink-escapes-repository"
LINK_TO_SENSITIVE_FILE = "symlink-to-sensitive-file"
LINK_TO_EXCLUDED_CONTENT = "symlink-to-excluded-content"


def _target_relative(full: str, root: Path) -> str | None:
    """The link target's repository-relative POSIX path, or ``None`` when it
    resolves outside the root."""
    try:
        return Path(os.path.realpath(full)).relative_to(root).as_posix()
    except ValueError:
        return None


def _same_known_identity(left: os.stat_result, right: os.stat_result) -> bool:
    """Whether two path-based observations prove one filesystem entry."""
    return (
        left.st_ino != 0
        and right.st_ino != 0
        and os.path.samestat(left, right)
    )


def _listed_name_state(
    root: Path, name: str, lookup: os.stat_result,
) -> bool | None:
    """Confirm exact spelling or one identity-bound alternate in one scan."""
    matching_alternate = False
    folded_name = name.casefold()
    try:
        with os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index >= walk_budget.MAX_WALK_ENTRIES:
                    return None
                entry_path = os.path.join(root, entry.name)
                if entry.name == name:
                    # A DirEntry can retain a name after that entry is renamed
                    # or removed. Require its path spelling to resolve now;
                    # the second scan below catches a case-only rename on a
                    # filesystem whose lookup is case-insensitive.
                    try:
                        os.lstat(entry_path)
                    except (OSError, ValueError):
                        return None
                    return True
                if entry.name.casefold() == folded_name:
                    try:
                        alternate = os.lstat(entry_path)
                    except (OSError, ValueError):
                        continue
                    if _same_known_identity(lookup, alternate):
                        matching_alternate = True
    except OSError:
        return None
    return False if matching_alternate else None


def entry_named_exactly(root: Path, name: str) -> bool | None:
    """Whether ``root`` holds a directory entry spelled exactly ``name`` — as
    the walk's fixed-name rules see it — not a path lookup, which on a
    case-insensitive filesystem would also find ``glossary.md`` or
    ``agents.md``, files the walk treats as ordinary evidence. The path lookup
    is the cheap fast path (absent → done, no directory scan); the exact-name
    confirmation iterates ``scandir`` under the walk-entry cap instead of
    materializing the whole listing, so a root with millions of entries costs
    no memory.

    Returns True when two bounded listings confirm the exact entry and False
    when the path lookup is absent or both listings confirm an
    identity-bound, case-insensitive alternate spelling. A requested-path
    lookup between the listings binds the second observation. Returns None
    when those observations disagree or presence, spelling, or identity could
    not be confirmed. Callers never report None as absent: a false absence
    claim is the one failure to avoid.
    """
    lookup = os.path.join(root, name)
    try:
        initial = os.lstat(lookup)
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        # ``os.path.lexists`` cannot be used here: it converts every lstat
        # failure into False, collapsing an uninspectable lookup into absence.
        return None
    first = _listed_name_state(root, name, initial)
    if first is None:
        return None
    try:
        current = os.lstat(lookup)
    except (OSError, ValueError):
        return None
    second = _listed_name_state(root, name, current)
    return first if second == first else None


def glossary_link_refusal(full: str, root: Path) -> str | None:
    """Why a symlinked root ``GLOSSARY.md`` may not be read as the repository
    glossary, or ``None``. The discovery channel exists to read that file,
    so only the rules that protect *what* is read apply: an escaping target,
    a sensitive target, or Glossabet's own output posing as the glossary. A
    link into ``docs/GLOSSARY.md`` or a hidden/vendored directory is the
    maintainers' choice and is followed."""
    target = _target_relative(full, root)
    if target is None:
        return LINK_ESCAPES_REPOSITORY
    parts = target.split("/")
    if any(is_sensitive(part) for part in parts):
        return LINK_TO_SENSITIVE_FILE
    if any(part in SELF_DIRS for part in parts[:-1]) or parts[-1] in SELF_REPORT_FILES:
        return LINK_TO_EXCLUDED_CONTENT
    return None


def symlink_content_refusal(
    full: str, root: Path, config: RepositoryConfig | None = None
) -> str | None:
    """Why a symlinked path is not repository content, or ``None`` when its
    confined target may be read like an ordinary file.

    A link resolving outside the repo is not repo content: reading it would
    ingest arbitrary host files into evidence (``os.walk``'s
    ``followlinks=False`` guards dirs, not files). A link with an innocent
    name pointing at content every other rule excludes (``notes.py -> .env``,
    ``x.md -> GLOSSARY.md``, ``y.js -> node_modules/...``) would otherwise
    launder that content into evidence, so the resolved target's complete
    repository-relative path is classified by the same rules the walk applies
    to the paths it meets directly: sensitive names anywhere in the path,
    Glossabet's own directories and files, hidden components, configured
    ignores, and generated/vendored roles (``config`` supplies the last two;
    without it those two rules are not applied).
    """
    target = _target_relative(full, root)
    if target is None:
        return LINK_ESCAPES_REPOSITORY
    parts = target.split("/")
    directories, name = parts[:-1], parts[-1]
    if any(is_sensitive(part) for part in parts):
        return LINK_TO_SENSITIVE_FILE
    if (
        any(part in SELF_DIRS for part in directories)
        or name in SELF_FILES
        or name in SELF_REPORT_FILES
        or any(part.startswith(".") for part in directories)
        or (name.startswith(".") and name not in WORKSPACE_MANIFESTS)
    ):
        return LINK_TO_EXCLUDED_CONTENT
    if config is not None and (
        config.is_ignored(target)
        or config.role_for(target) in EXCLUDED_CONTENT_ROLES
    ):
        return LINK_TO_EXCLUDED_CONTENT
    return None
