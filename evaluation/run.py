#!/usr/bin/env python3
"""Reproduce Glossabet's pinned Phase 15/16 evaluation.

External source is checked out only into a caller-provided directory or a
temporary directory. Nothing is imported or executed from a target project.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from glossabet import __version__  # noqa: E402
from glossabet.artifacts import MAX_JSON_BYTES  # noqa: E402
from glossabet.cache import CACHE_ROOT_ENV  # noqa: E402
from glossabet.config import CONFIG_FILE  # noqa: E402
from glossabet.drift import (  # noqa: E402
    DRIFT_SCHEMA_VERSION,
    build_drift,
)
from glossabet.evidence import (  # noqa: E402
    SCHEMA_VERSION as EVIDENCE_SCHEMA_VERSION,
    build_evidence,
)
from glossabet.glossary import validate_glossary  # noqa: E402
from glossabet.graphify import GRAPH_PATH  # noqa: E402
from glossabet.importance import (  # noqa: E402
    NOMINATION_CANONICAL_NAME,
    NOMINATION_DISAMBIGUATION,
)
from glossabet.reconcile import (  # noqa: E402
    VALIDATION_SCHEMA_VERSION,
    build_validation,
)
from glossabet.tokenize import (  # noqa: E402
    STRUCTURED_IDENTIFIER_STYLES,
)

EVALUATION_SCHEMA_VERSION = 6
DEFAULT_MANIFEST = PROJECT_ROOT / "evaluation" / "corpus.json"
DEFAULT_RESULTS = PROJECT_ROOT / "evaluation" / "results.json"
RELEASE_RUNTIME_RUNS = 5
# Every metric the evaluator can gate on. Genuineness verification pins this
# exact set so a tampered artifact cannot simply drop the checks it fails;
# which targets those checks carry is verified against the manifest at the
# release gate.
RELEASE_THRESHOLD_NAMES = frozenset({
    "terminology_precision_min",
    "drift_precision_min",
    "drift_recall_min",
    "structural_precision_min",
    "structural_recall_min",
    "reviewer_usefulness_min",
    "false_alarms_per_1000_max",
    "cold_seconds_per_1000_source_files_max",
    "corpus_budget_truncations_max",
    "minimum_cache_reuse_min",
    "lexical_contract_min",
    "register_accuracy_min",
    "nomination_quality_min",
    "structural_contract_min",
})
# Neutralize repo-config code-execution surfaces and, critically, the ext::
# remote helper: a corpus url like `ext::sh -c '<payload>'` otherwise runs a
# shell at fetch time. The manifest validator additionally requires https.
GIT_SAFE_CONFIG = (
    "-c", "core.fsmonitor=",
    "-c", "core.hooksPath=/dev/null",
    "-c", "protocol.ext.allow=never",
)
DRIFT_SECTIONS = (
    "parallel_terms",
    "watched_terms_in_use",
    "canonical_fading",
    "canonical_overloaded",
)
SOURCE_METADATA_KEYS = (
    "kind",
    "path",
    "checkout_dir",
    "url",
    "commit",
    "primary_language",
    "license_spdx",
    "license_url",
    "provenance",
)
STRUCTURAL_SECTIONS = (
    "unnamed_structure",
    "boundary_mismatch",
    "overloaded_structural_region",
    "orphaned_concepts",
    "fragmentation",
)


class EvaluationError(ValueError):
    """The corpus, checkout, or labels cannot support a valid evaluation."""


def _dotenv_part(name: str) -> bool:
    return (
        name == ".env"
        or name.endswith(".env")
        or name.startswith(".env.")
        or ".env." in name
    )


def _hex_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_safe_relative(value: object) -> bool:
    """A manifest-supplied path that cannot escape the base it is joined onto.

    `corpus.json` is contributor-editable (a pull request adds a repo to the
    eval corpus), so `checkout_dir`/`path` are attacker-controlled. Joining an
    absolute path or one containing `..` onto the temp checkout root (or the
    project root) escapes it and lets a poisoned manifest create/overwrite
    files anywhere the maintainer can write. Require a non-empty relative path
    with no parent traversal, drive letters, or NUL.
    """
    if not isinstance(value, str) or not value or "\x00" in value:
        return False
    # OS-agnostic on purpose: Path.is_absolute() is not — on Windows
    # Path("/tmp/pwn").is_absolute() is False (no drive), so a POSIX absolute
    # path would slip through when the harness runs on Windows. Reject every
    # absolute/traversal form regardless of the running platform.
    if value[0] in "/\\":  # POSIX-absolute or a leading path separator
        return False
    if "\\" in value:  # backslash: Windows separator, never in a relative spec
        return False
    if len(value) >= 2 and value[1] == ":":  # Windows drive, e.g. C:\ or C:foo
        return False
    if ".." in value.split("/"):  # parent traversal
        return False
    return True


def _is_commit_sha(value: object) -> bool:
    """git object name: 40 hex (SHA-1) or 64 hex (SHA-256). Rejects a value
    starting with `-` that git would parse as an option in a refspec slot."""
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", value) is not None


def _digest_paths(root: Path, relative_paths: list[str]) -> str:
    """Hash path names and bytes with unambiguous framing."""
    base = root.resolve()
    digest = hashlib.sha256()
    for relative in sorted(set(relative_paths)):
        rel = Path(relative)
        if (
            rel.is_absolute()
            or ".." in rel.parts
            or any(_dotenv_part(part) for part in rel.parts)
        ):
            raise EvaluationError(f"unsafe corpus digest path: {relative}")
        path = (base / rel).resolve()
        try:
            path.relative_to(base)
        except ValueError as exc:
            raise EvaluationError(
                f"corpus digest path escapes its source root: {relative}"
            ) from exc
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise EvaluationError(
                f"could not hash evaluation input {relative}: {exc}"
            ) from exc
        name = rel.as_posix().encode("utf-8")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _engine_metadata() -> dict:
    source_paths = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in (PROJECT_ROOT / "glossabet").glob("**/*.py")
        if not any(_dotenv_part(part) for part in path.parts)
    ]
    source_paths.append("evaluation/run.py")
    return {
        "name": "glossabet",
        "version": __version__,
        "source_sha256": _digest_paths(PROJECT_ROOT, source_paths),
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "drift_schema_version": DRIFT_SCHEMA_VERSION,
        "validation_schema_version": VALIDATION_SCHEMA_VERSION,
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
    }


def _corpus_identity(root: Path, evidence: dict, *, graphify: bool = False) -> dict:
    paths = [
        item["path"]
        for kind in ("code", "docs")
        for item in evidence["files"][kind]
    ]
    if evidence.get("configuration", {}).get("present"):
        paths.append(CONFIG_FILE)
    if graphify and (root / GRAPH_PATH).is_file():
        paths.append(GRAPH_PATH)
    return {
        "sha256": _digest_paths(root, paths),
        "files_hashed": len(set(paths)),
    }


def _read_manifest(path: Path) -> tuple[dict, str]:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise EvaluationError(
            f"{path}: manifest exceeds {MAX_JSON_BYTES} bytes — refusing to load"
        )
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise EvaluationError(f"{path}: unreadable JSON ({exc})") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 5:
        raise EvaluationError(f"{path}: unsupported evaluation manifest")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise EvaluationError(f"{path}: sources must be a non-empty list")
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            raise EvaluationError(f"{path}: every source needs a string id")
        digest = source.get("corpus_sha256")
        files = source.get("corpus_files")
        if (
            not isinstance(digest, str)
            or not _hex_digest(digest)
            or not isinstance(files, int)
            or isinstance(files, bool)
            or files < 0
        ):
            raise EvaluationError(
                f"{path}: {source['id']} needs a valid corpus digest/count"
            )
        if not isinstance(source.get("expectations", {}).get("register"), dict):
            raise EvaluationError(
                f"{path}: {source['id']} needs a register expectation"
            )
        if source.get("kind") == "local":
            if not _is_safe_relative(source.get("path")):
                raise EvaluationError(
                    f"{path}: {source['id']} path must be a safe relative path"
                )
        else:
            url = source.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                # A non-https url (e.g. `ext::sh -c ...`) reaches
                # `git remote add` and can execute a shell at fetch time.
                raise EvaluationError(
                    f"{path}: {source['id']} url must be an https:// URL"
                )
            if not _is_safe_relative(source.get("checkout_dir")):
                # Joined onto the temp checkout root; `..`/absolute escapes it.
                raise EvaluationError(
                    f"{path}: {source['id']} checkout_dir must be a safe "
                    "relative path"
                )
            if not _is_commit_sha(source.get("commit")):
                raise EvaluationError(
                    f"{path}: {source['id']} commit must be a 40- or 64-char "
                    "hex object name"
                )
    if not isinstance(manifest.get("self_register"), dict):
        raise EvaluationError(f"{path}: self_register must be an object")
    if not isinstance(manifest.get("self_nominations"), dict):
        raise EvaluationError(f"{path}: self_nominations must be an object")
    return manifest, hashlib.sha256(raw).hexdigest()


def _git(args: list[str], cwd: Path, timeout: int = 120) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }
    proc = subprocess.run(
        ["git", *GIT_SAFE_CONFIG, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if proc.returncode:
        detail = proc.stderr.strip() or proc.stdout.strip() or "git failed"
        raise EvaluationError(detail)
    return proc.stdout.strip()


def _fetch(source: dict, repositories_root: Path) -> Path:
    destination = repositories_root / source["checkout_dir"]
    # Defense in depth: _read_manifest already rejects unsafe checkout_dir, but
    # never let a resolved destination escape its base even if that changes.
    try:
        destination.resolve().relative_to(repositories_root.resolve())
    except ValueError as exc:
        raise EvaluationError(
            f"{source['id']}: checkout_dir escapes the checkout root"
        ) from exc
    if destination.exists():
        raise EvaluationError(f"refusing to replace existing {destination}")
    destination.mkdir(parents=True)
    _git(["init", "-q"], destination)
    _git(["remote", "add", "origin", "--", source["url"]], destination)
    _git(["fetch", "--depth", "1", "origin", "--", source["commit"]], destination)
    _git(["checkout", "--detach", "--force", "FETCH_HEAD"], destination)
    return destination


def _source_root(source: dict, repositories_root: Path | None,
                 fetch: bool) -> Path:
    if source.get("kind") == "local":
        resolved = (PROJECT_ROOT / source["path"]).resolve()
        try:
            resolved.relative_to(PROJECT_ROOT.resolve())
        except ValueError as exc:
            raise EvaluationError(
                f"{source['id']}: local path escapes the project root"
            ) from exc
        return resolved
    if repositories_root is None:
        raise EvaluationError("external sources require --fetch or --repositories-root")
    if not fetch:
        # --repositories-root branch: same escape guard as _fetch.
        pre = (repositories_root / source["checkout_dir"]).resolve()
        try:
            pre.relative_to(repositories_root.resolve())
        except ValueError as exc:
            raise EvaluationError(
                f"{source['id']}: checkout_dir escapes the checkout root"
            ) from exc
    root = (
        _fetch(source, repositories_root)
        if fetch else repositories_root / source["checkout_dir"]
    ).resolve()
    if not root.is_dir():
        raise EvaluationError(f"missing checkout for {source['id']}: {root}")
    actual = _git(["rev-parse", "HEAD"], root)
    if actual != source["commit"]:
        raise EvaluationError(
            f"{source['id']}: expected {source['commit']}, found {actual}"
        )
    return root


def _check_license(source: dict, root: Path) -> None:
    base = PROJECT_ROOT if source.get("license_base") == "project" else root
    license_path = (base / source["license_path"]).resolve()
    try:
        license_path.relative_to(base.resolve())
    except ValueError as exc:
        raise EvaluationError(f"{source['id']}: license path escapes its base") from exc
    if not license_path.is_file():
        raise EvaluationError(f"{source['id']}: missing declared license file")


@contextmanager
def _cache_at(path: Path):
    previous = os.environ.get(CACHE_ROOT_ENV)
    os.environ[CACHE_ROOT_ENV] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(CACHE_ROOT_ENV, None)
        else:
            os.environ[CACHE_ROOT_ENV] = previous


def _timed_build(
    root: Path, *, cache: bool, graphify: bool = False
) -> tuple[dict, float, dict]:
    stats: dict = {}
    started = time.perf_counter()
    evidence = build_evidence(
        root,
        cache=cache,
        stats=stats,
        graphify=graphify,
    )
    elapsed = time.perf_counter() - started
    return evidence, elapsed, stats


def _terminology_keys(evidence: dict) -> set[str]:
    return set(_terminology_items(evidence))


def _terminology_items(evidence: dict) -> dict[str, tuple[str, dict]]:
    terminology = evidence["terminology"]
    items: dict[str, tuple[str, dict]] = {}
    for item in terminology["synonym_candidates"]["items"]:
        key = "synonym:" + ":".join(sorted((item["a"], item["b"])))
        items[key] = ("synonym-candidate", item)
    for item in terminology["overload_candidates"]["items"]:
        items[f"overload:{item['term']}"] = ("overload-candidate", item)
    return items


def _drift_key(section: str, finding: dict) -> tuple[str, str]:
    if section == "parallel_terms":
        return (
            "parallel-term",
            f"parallel-term:{finding['concept_id']}:{finding['new_term']}",
        )
    if section == "watched_terms_in_use":
        return (
            "watched-term-in-use",
            "watched-term-in-use:"
            f"{finding['concept_id']}:{finding['term'].casefold()}",
        )
    if section == "canonical_fading":
        return "canonical-fading", f"canonical-fading:{finding['concept_id']}"
    return (
        "canonical-overloaded",
        f"canonical-overloaded:{finding['concept_id']}",
    )


def _drift_keys(drift: dict) -> dict[str, str]:
    return {
        key: kind for key, (kind, _) in _drift_items(drift).items()
    }


def _drift_items(drift: dict) -> dict[str, tuple[str, dict]]:
    return {
        key: (kind, finding)
        for section in DRIFT_SECTIONS
        for finding in drift[section]["items"]
        for kind, key in [_drift_key(section, finding)]
    }


def _structural_key(section: str, finding: dict) -> str:
    if section == "unnamed_structure":
        return f"unnamed-structure:{finding['group']}"
    if section == "boundary_mismatch":
        a, b = sorted(finding["concepts"])
        return f"boundary-mismatch:{finding['group']}:{a}:{b}"
    if section == "overloaded_structural_region":
        return f"overloaded-structural-region:{finding['group']}"
    if section == "orphaned_concepts":
        return f"orphaned-concept:{finding['concept_id']}"
    return f"fragmentation:{finding['concept_id']}"


def _structural_keys(validation: dict) -> dict[str, tuple[str, dict]]:
    return {
        _structural_key(section, finding): (section, finding)
        for section in STRUCTURAL_SECTIONS
        for finding in validation[section]["items"]
    }


def _review_items(
    source_id: str,
    evidence: dict,
    drift: dict,
    validation: dict | None,
) -> list[dict]:
    items: list[dict] = []

    for key, (kind, finding) in sorted(_terminology_items(evidence).items()):
        if kind == "synonym-candidate":
            summary = (
                f"'{finding['a']}' and '{finding['b']}' may be parallel terms"
            )
        else:
            summary = f"'{finding['term']}' may carry unrelated meanings"
        items.append({
            "review_key": f"{source_id}|terminology|{key}",
            "source_id": source_id,
            "surface": "terminology",
            "finding_key": key,
            "kind": kind,
            "summary": summary,
            "evidence": finding,
        })

    for key, (kind, finding) in sorted(_drift_items(drift).items()):
        items.append({
            "review_key": f"{source_id}|drift|{key}",
            "source_id": source_id,
            "surface": "drift",
            "finding_key": key,
            "kind": kind,
            "summary": finding["summary"],
            "evidence": finding.get("evidence", {}),
        })

    if validation is not None:
        for key, (section, finding) in sorted(
            _structural_keys(validation).items()
        ):
            items.append({
                "review_key": f"{source_id}|structural|{key}",
                "source_id": source_id,
                "surface": "structural",
                "finding_key": key,
                "kind": finding["kind"],
                "summary": finding["summary"],
                "evidence": finding.get("evidence", {}),
            })
    return items


def _label_map(entries: list[dict]) -> dict[str, dict]:
    labels = {}
    for entry in entries:
        key = entry.get("key")
        if not isinstance(key, str) or not key or key in labels:
            raise EvaluationError("expectation keys must be unique non-empty strings")
        if not isinstance(entry.get("useful"), bool):
            raise EvaluationError(f"{key}: useful must be boolean")
        labels[key] = entry
    return labels


def _score(actual: set[str], labels: dict[str, dict],
           recall_expected: set[str]) -> dict:
    correct = set(labels)
    true_positive = sorted(actual & correct)
    false_positive = sorted(actual - correct)
    false_negative = sorted(recall_expected - actual)
    useful = sorted(key for key in actual if labels.get(key, {}).get("useful"))
    return {
        "actual": sorted(actual),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "useful": useful,
    }


def _lexical_score(evidence: dict, expectation: object) -> dict:
    if expectation is None:
        return {
            "configured": False,
            "checks": 0,
            "passed_checks": 0,
            "passed": None,
            "missing_tokens": [],
            "forbidden_tokens_present": [],
            "identifier_mismatches": [],
        }
    if not isinstance(expectation, dict):
        raise EvaluationError("lexical expectations must be an object")
    required = expectation.get("required_tokens", [])
    forbidden = expectation.get("forbidden_tokens", [])
    identifiers = expectation.get("required_identifiers", {})
    if (
        not isinstance(required, list)
        or not all(isinstance(token, str) for token in required)
        or len(set(required)) != len(required)
        or not isinstance(forbidden, list)
        or not all(isinstance(token, str) for token in forbidden)
        or len(set(forbidden)) != len(forbidden)
        or not isinstance(identifiers, dict)
        or not all(
            isinstance(name, str)
            and isinstance(tokens, list)
            and all(isinstance(token, str) for token in tokens)
            for name, tokens in identifiers.items()
        )
    ):
        raise EvaluationError("malformed lexical token/identifier expectations")

    actual_tokens = {
        item["term"] for item in evidence["vocabulary"]["tokens"]["items"]
    }
    actual_identifiers = {
        item["name"]: item["tokens"]
        for item in evidence["vocabulary"]["identifiers"]["items"]
    }
    missing = sorted(set(required) - actual_tokens)
    forbidden_present = sorted(set(forbidden) & actual_tokens)
    mismatches = [
        {
            "name": name,
            "expected": tokens,
            "actual": actual_identifiers.get(name),
        }
        for name, tokens in sorted(identifiers.items())
        if actual_identifiers.get(name) != tokens
    ]
    checks = len(required) + len(forbidden) + len(identifiers)
    failures = len(missing) + len(forbidden_present) + len(mismatches)
    return {
        "configured": True,
        "checks": checks,
        "passed_checks": checks - failures,
        "passed": failures == 0,
        "missing_tokens": missing,
        "forbidden_tokens_present": forbidden_present,
        "identifier_mismatches": mismatches,
    }


def _register_score(evidence: dict, expectation: object) -> dict:
    if not isinstance(expectation, dict):
        raise EvaluationError("register expectations must be an object")
    expected_style = expectation.get("dominant_style")
    expected_multi_word = expectation.get("predominantly_multi_word")
    if expected_style not in STRUCTURED_IDENTIFIER_STYLES:
        raise EvaluationError(
            "register dominant_style must name a structurally styled form"
        )
    if not isinstance(expected_multi_word, bool):
        raise EvaluationError(
            "register predominantly_multi_word must be boolean"
        )

    register = evidence["terminology"]["register"]
    styles = register["identifier_styles_pct"]
    lengths = register["token_count_distribution_pct"]
    ranked_styles = sorted(
        styles.items(), key=lambda item: (-item[1], item[0])
    )
    dominant_style = ranked_styles[0][0] if ranked_styles else None
    multi_word_pct = (
        round(100.0 - lengths.get("1", 0.0), 1) if lengths else None
    )
    predominantly_multi_word = (
        multi_word_pct > 50.0 if multi_word_pct is not None else None
    )
    checks = [
        {
            "name": "dominant_style",
            "expected": expected_style,
            "actual": dominant_style,
            "passed": dominant_style == expected_style,
        },
        {
            "name": "predominantly_multi_word",
            "expected": expected_multi_word,
            "actual": predominantly_multi_word,
            "passed": predominantly_multi_word == expected_multi_word,
        },
    ]
    passed = sum(check["passed"] for check in checks)
    return {
        "configured": True,
        "expected": {
            "dominant_style": expected_style,
            "predominantly_multi_word": expected_multi_word,
        },
        "actual": {
            "dominant_style": dominant_style,
            "predominantly_multi_word": predominantly_multi_word,
            "multi_word_pct": multi_word_pct,
            "composition": register["composition"],
        },
        "checks": len(checks),
        "passed_checks": passed,
        "passed": passed == len(checks),
        "failures": [check for check in checks if not check["passed"]],
    }


def _evaluate_self_register(expectation: object, evidence: dict) -> dict:
    return {
        "id": "glossabet",
        "source": {"kind": "local", "path": "."},
        **_register_score(evidence, expectation),
    }


def _nomination_score(evidence: dict, expectation: object) -> dict:
    if not isinstance(expectation, dict):
        raise EvaluationError("nomination expectations must be an object")
    required = expectation.get("required", [])
    forbidden = expectation.get("forbidden_terms", [])
    require_all_typed = expectation.get("require_all_typed")
    valid_kinds = {
        NOMINATION_CANONICAL_NAME,
        NOMINATION_DISAMBIGUATION,
    }
    if (
        not isinstance(required, list)
        or not all(
            isinstance(item, dict)
            and isinstance(item.get("term"), str)
            and item.get("nomination_kind") in valid_kinds
            for item in required
        )
        or len({item["term"] for item in required}) != len(required)
        or not isinstance(forbidden, list)
        or not all(isinstance(term, str) and term for term in forbidden)
        or len(set(forbidden)) != len(forbidden)
        or not isinstance(require_all_typed, bool)
    ):
        raise EvaluationError("malformed nomination expectations")

    candidates = {
        item["term"]: item
        for item in evidence["naming_candidates"]["terms"]
    }
    checks: list[dict] = []
    for expected in required:
        term = expected["term"]
        actual = candidates.get(term, {}).get("nomination_kind")
        checks.append({
            "name": f"required:{term}",
            "expected": expected["nomination_kind"],
            "actual": actual,
            "passed": actual == expected["nomination_kind"],
        })
    for term in forbidden:
        actual = term in candidates
        checks.append({
            "name": f"forbidden:{term}",
            "expected": False,
            "actual": actual,
            "passed": not actual,
        })
    if require_all_typed:
        untyped = sorted(
            term for term, item in candidates.items()
            if item.get("nomination_kind") not in valid_kinds
        )
        checks.append({
            "name": "all_candidates_typed",
            "expected": [],
            "actual": untyped,
            "passed": not untyped,
        })

    passed = sum(check["passed"] for check in checks)
    return {
        "id": "glossabet",
        "source": {"kind": "local", "path": "."},
        "configured": True,
        "expected": expectation,
        "actual": [
            {
                "term": term,
                "nomination_kind": item.get("nomination_kind"),
            }
            for term, item in sorted(candidates.items())
        ],
        "checks": len(checks),
        "passed_checks": passed,
        "passed": passed == len(checks),
        "failures": [check for check in checks if not check["passed"]],
    }


def _evaluate_self_nominations(expectation: object, evidence: dict) -> dict:
    return _nomination_score(evidence, expectation)


def _structural_contract_score(
    evidence: dict,
    validation: dict,
    expectation: dict,
) -> dict:
    contracts = expectation.get("contracts", {})
    if not isinstance(contracts, dict):
        raise EvaluationError("structural contracts must be an object")
    checks: list[dict] = []

    def check(name: str, actual: object, expected: object) -> None:
        checks.append({
            "name": name,
            "actual": actual,
            "expected": expected,
            "passed": actual == expected,
        })

    groups = evidence["structural_groups"].get("groups", [])
    group_by_label = {
        group.get("label"): group
        for group in groups
        if isinstance(group, dict) and isinstance(group.get("label"), str)
    }
    group_contracts = contracts.get("groups", [])
    if (
        not isinstance(group_contracts, list)
        or not all(isinstance(item, dict) for item in group_contracts)
    ):
        raise EvaluationError("structural contract groups must be a list of objects")
    for expected_group in group_contracts:
        label = expected_group.get("label")
        if not isinstance(label, str) or not label:
            raise EvaluationError("each structural group contract needs a label")
        group = group_by_label.get(label)
        check(f"group:{label}:present", group is not None, True)
        if group is None:
            continue
        if "size" in expected_group:
            check(f"group:{label}:size", group.get("size"), expected_group["size"])
        if "provenance" in expected_group:
            check(
                f"group:{label}:provenance",
                group.get("provenance"),
                expected_group["provenance"],
            )
        required_tokens = expected_group.get("required_member_tokens", [])
        if not isinstance(required_tokens, list):
            raise EvaluationError("required_member_tokens must be a list")
        member_tokens = set(group.get("member_tokens", []))
        for token in required_tokens:
            check(
                f"group:{label}:member-token:{token}",
                token in member_tokens,
                True,
            )
        excluded_sample = expected_group.get("excluded_members_sample", [])
        if not isinstance(excluded_sample, list):
            raise EvaluationError("excluded_members_sample must be a list")
        members_sample = set(group.get("members_sample", []))
        required_sample = expected_group.get("required_members_sample", [])
        if not isinstance(required_sample, list):
            raise EvaluationError("required_members_sample must be a list")
        for member in required_sample:
            check(
                f"group:{label}:sample-includes:{member}",
                member in members_sample,
                True,
            )
        for member in excluded_sample:
            check(
                f"group:{label}:sample-excludes:{member}",
                member not in members_sample,
                True,
            )

    coverage_contract = contracts.get("group_coverage", {})
    if not isinstance(coverage_contract, dict):
        raise EvaluationError("structural group_coverage contract must be an object")
    group_coverage = evidence["structural_groups"].get("coverage", {}).get(
        "groups", {}
    )
    for name, expected in sorted(coverage_contract.items()):
        check(f"group-coverage:{name}", group_coverage.get(name), expected)

    if "validation_total_findings_complete" in contracts:
        check(
            "validation:total-findings-complete",
            validation.get("total_findings_complete"),
            contracts["validation_total_findings_complete"],
        )
    partial_sections = contracts.get("partial_sections", [])
    if not isinstance(partial_sections, list):
        raise EvaluationError("structural partial_sections must be a list")
    for section in partial_sections:
        if section not in STRUCTURAL_SECTIONS:
            raise EvaluationError(f"unknown structural partial section: {section}")
        check(
            f"validation:{section}:complete",
            validation[section]["coverage"].get("complete"),
            False,
        )

    passed = sum(item["passed"] for item in checks)
    return {
        "checks": len(checks),
        "passed_checks": passed,
        "passed": passed == len(checks),
        "failures": [item for item in checks if not item["passed"]],
    }


def _structural_score(
    evidence: dict,
    glossary: dict,
    expectation: object,
) -> tuple[dict, dict | None]:
    if expectation is None:
        return ({
            "configured": False,
            "recall_complete": False,
            "actual": [],
            "true_positive": [],
            "false_positive": [],
            "false_negative": [],
            "useful": [],
            "contracts": {
                "checks": 0,
                "passed_checks": 0,
                "passed": None,
                "failures": [],
            },
        }, None)
    if not isinstance(expectation, dict):
        raise EvaluationError("structural expectations must be an object")
    recall_complete = expectation.get("recall_complete")
    if not isinstance(recall_complete, bool):
        raise EvaluationError("structural recall_complete must be boolean")
    labels = _label_map(expectation.get("correct", []))
    validation = build_validation(evidence, glossary)
    actual = _structural_keys(validation)
    score = _score(
        set(actual),
        labels,
        set(labels) if recall_complete else set(),
    )
    return ({
        "configured": True,
        "recall_complete": recall_complete,
        **score,
        "contracts": _structural_contract_score(
            evidence, validation, expectation
        ),
        "coverage": {
            "groups": evidence["structural_groups"]["coverage"]["groups"],
            "validation_complete": validation["total_findings_complete"],
        },
    }, validation)


def _truncations(evidence: dict) -> list[dict]:
    events = []
    for name in ("tokens", "identifiers", "doc_terms"):
        marker = evidence["vocabulary"][name]["truncated"]
        if marker:
            events.append({"surface": f"vocabulary.{name}", **marker})
    for name in (
        "synonym_candidates", "context_dispersion", "overload_candidates"
    ):
        dropped = evidence["terminology"][name]["dropped_items"]
        if dropped:
            events.append({"surface": f"terminology.{name}", "dropped_items": dropped})
    for name in ("edges_truncated", "external_truncated"):
        dropped = evidence["imports"][name]
        if dropped:
            events.append({"surface": f"imports.{name}", "dropped_items": dropped})
    budget = evidence.get("skipped", {}).get("corpus_budget")
    if budget and not budget.get("complete", True):
        events.append({"surface": "corpus_budget", **budget})
    structural = evidence.get("structural_groups", {})
    group_coverage = structural.get("coverage", {}).get("groups")
    if group_coverage and not group_coverage.get("complete", True):
        events.append({
            "surface": "structural_groups.groups",
            **group_coverage,
        })
    return events


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _source_metadata(source: dict) -> dict:
    return {
        key: source[key] for key in SOURCE_METADATA_KEYS if key in source
    }


def _manifest_corpus_identity(source: dict) -> dict:
    return {
        "sha256": source["corpus_sha256"],
        "files_hashed": source["corpus_files"],
    }


def _evaluate_source(source: dict, root: Path, runs: int,
                     cache_root: Path) -> dict:
    errors = validate_glossary(source["glossary"])
    if errors:
        raise EvaluationError(f"{source['id']}: invalid glossary: {'; '.join(errors)}")
    _check_license(source, root)
    structural_expectation = source["expectations"].get("structural")
    graphify = structural_expectation is not None

    cold_times = []
    cold_evidence = None
    for _ in range(runs):
        cold_evidence, elapsed, _ = _timed_build(
            root, cache=False, graphify=graphify
        )
        cold_times.append(elapsed)
    assert cold_evidence is not None

    with _cache_at(cache_root / source["id"]):
        _timed_build(
            root, cache=True, graphify=graphify
        )  # populate outside the timed warm sample
        warm_times = []
        warm_stats = []
        warm_match = True
        cold_blob = json.dumps(cold_evidence, sort_keys=True)
        for _ in range(runs):
            warm, elapsed, stats = _timed_build(
                root, cache=True, graphify=graphify
            )
            warm_times.append(elapsed)
            warm_stats.append(stats)
            warm_match = warm_match and json.dumps(warm, sort_keys=True) == cold_blob

    drift = build_drift(cold_evidence, source["glossary"])
    term_expect = source["expectations"]["terminology"]
    term_labels = _label_map(term_expect["correct"])
    term_recall = set(term_labels) if term_expect["recall_complete"] else set()
    terminology_score = _score(
        _terminology_keys(cold_evidence), term_labels, term_recall
    )

    drift_expect = source["expectations"]["drift"]
    drift_labels = _label_map(drift_expect["correct"])
    actual_drift = _drift_keys(drift)
    recall_kinds = set(drift_expect["recall_kinds"])
    drift_recall = {
        key for key in drift_labels
        if key.split(":", 1)[0] in recall_kinds
    }
    drift_score = _score(set(actual_drift), drift_labels, drift_recall)
    lexical_score = _lexical_score(
        cold_evidence, source["expectations"].get("lexical")
    )
    register_score = _register_score(
        cold_evidence, source["expectations"]["register"]
    )
    structural_score, validation = _structural_score(
        cold_evidence,
        source["glossary"],
        structural_expectation,
    )

    totals = cold_evidence["totals"]
    corpus_budget = cold_evidence["skipped"]["corpus_budget"]
    source_files = totals["code_files"] + totals["doc_files"]
    warm_reused = sum(item["reused"] for item in warm_stats)
    warm_processed = warm_reused + sum(item["extracted"] for item in warm_stats)
    corpus = _corpus_identity(root, cold_evidence, graphify=graphify)
    if corpus != _manifest_corpus_identity(source):
        raise EvaluationError(
            f"{source['id']}: accepted corpus digest/count does not match manifest"
        )
    return {
        "id": source["id"],
        "source": _source_metadata(source),
        "corpus": corpus,
        "files": {
            "source": source_files,
            "production_code": cold_evidence["terminology"]["scope"]["code_files"],
            "production_docs": cold_evidence["terminology"]["scope"]["doc_files"],
        },
        "bytes": {
            "code": totals["code_bytes"],
            "source_budgeted": totals.get("source_bytes"),
        },
        "corpus_budget": corpus_budget,
        "runtime_seconds": {
            "cold_samples": [round(value, 6) for value in cold_times],
            "cold_median": round(statistics.median(cold_times), 6),
            "warm_samples": [round(value, 6) for value in warm_times],
            "warm_median": round(statistics.median(warm_times), 6),
        },
        "cache": {
            "warm_output_matches_cold": warm_match,
            "reuse_rate": _ratio(warm_reused, warm_processed),
        },
        "truncations": _truncations(cold_evidence),
        "lexical": lexical_score,
        "register": register_score,
        "terminology": terminology_score,
        "drift": drift_score,
        "structural": structural_score,
        "review_items": _review_items(
            source["id"], cold_evidence, drift, validation
        ),
    }


def _aggregate(
    cases: list[dict],
    self_register: dict,
    self_nominations: dict,
) -> dict:
    def combine(surface: str, key: str) -> int:
        return sum(len(case[surface][key]) for case in cases)

    term_actual = combine("terminology", "actual")
    term_true = combine("terminology", "true_positive")
    term_false = combine("terminology", "false_positive")
    term_missed = combine("terminology", "false_negative")
    drift_actual = combine("drift", "actual")
    drift_true = combine("drift", "true_positive")
    drift_false = combine("drift", "false_positive")
    drift_missed = combine("drift", "false_negative")
    structural_actual = combine("structural", "actual")
    structural_true = combine("structural", "true_positive")
    structural_false = combine("structural", "false_positive")
    structural_missed = combine("structural", "false_negative")
    total_actual = term_actual + drift_actual + structural_actual
    total_true = term_true + drift_true + structural_true
    total_false = term_false + drift_false + structural_false
    total_useful = (
        combine("terminology", "useful")
        + combine("drift", "useful")
        + combine("structural", "useful")
    )
    lexical_checks = sum(case["lexical"]["checks"] for case in cases)
    lexical_passed = sum(case["lexical"]["passed_checks"] for case in cases)
    register_checks = (
        sum(case["register"]["checks"] for case in cases)
        + self_register["checks"]
    )
    register_passed = (
        sum(case["register"]["passed_checks"] for case in cases)
        + self_register["passed_checks"]
    )
    nomination_checks = self_nominations["checks"]
    nomination_passed = self_nominations["passed_checks"]
    structural_contract_checks = sum(
        case["structural"]["contracts"]["checks"] for case in cases
    )
    structural_contract_passed = sum(
        case["structural"]["contracts"]["passed_checks"] for case in cases
    )
    production_files = sum(case["files"]["production_code"] for case in cases)
    source_files = sum(case["files"]["source"] for case in cases)
    source_bytes = sum(case["bytes"]["source_budgeted"] for case in cases)
    walk_entries = sum(
        case["corpus_budget"]["used"]["walk_entries"] for case in cases
    )
    cold_seconds = sum(case["runtime_seconds"]["cold_median"] for case in cases)
    warm_seconds = sum(case["runtime_seconds"]["warm_median"] for case in cases)
    budget_truncations = sum(
        event["surface"] == "corpus_budget"
        for case in cases for event in case["truncations"]
    )
    known_reuse = [
        case["cache"]["reuse_rate"]
        for case in cases
        if case["cache"]["reuse_rate"] is not None
    ]
    return {
        "cases": len(cases),
        "source_files": source_files,
        "source_bytes": source_bytes,
        "walk_entries": walk_entries,
        "limits_per_repository": cases[0]["corpus_budget"]["limits"],
        "production_code_files": production_files,
        "quality": {
            "terminology_precision": _ratio(term_true, term_actual),
            "terminology_recall_where_complete": _ratio(
                term_true, term_true + term_missed
            ),
            "drift_precision": _ratio(drift_true, drift_actual),
            "drift_recall_where_complete": _ratio(
                drift_true, drift_true + drift_missed
            ),
            "structural_precision": _ratio(
                structural_true, structural_actual
            ),
            "structural_recall_where_complete": _ratio(
                structural_true, structural_true + structural_missed
            ),
            "overall_precision": _ratio(total_true, total_actual),
            "reviewer_usefulness": _ratio(total_useful, total_actual),
            "lexical_contract_rate": _ratio(lexical_passed, lexical_checks),
            "register_accuracy": _ratio(register_passed, register_checks),
            "nomination_quality": _ratio(
                nomination_passed, nomination_checks
            ),
            "structural_contract_rate": _ratio(
                structural_contract_passed, structural_contract_checks
            ),
            "false_alarms": total_false,
            "false_alarms_per_1000_production_code_files": (
                round(total_false * 1000 / production_files, 2)
                if production_files else None
            ),
        },
        "runtime": {
            "cold_median_seconds_total": round(cold_seconds, 6),
            "warm_median_seconds_total": round(warm_seconds, 6),
            "cold_seconds_per_1000_source_files": (
                round(cold_seconds * 1000 / source_files, 3)
                if source_files else None
            ),
            "warm_seconds_per_1000_source_files": (
                round(warm_seconds * 1000 / source_files, 3)
                if source_files else None
            ),
        },
        "cache": {
            "all_warm_outputs_match_cold": all(
                case["cache"]["warm_output_matches_cold"] for case in cases
            ),
            # An empty corpus has no measurable reuse rate (None); it must
            # not crash the aggregate or masquerade as a measured minimum.
            "minimum_reuse_rate": (
                min(known_reuse) if known_reuse else None
            ),
        },
        "truncation": {
            "cases_with_any_truncation": sum(bool(case["truncations"]) for case in cases),
            "corpus_budget_truncations": budget_truncations,
        },
    }


def _thresholds(aggregate: dict, thresholds: dict | None) -> dict:
    if not thresholds:
        return {"configured": False, "passed": None, "checks": []}
    metrics = {
        "terminology_precision_min": aggregate["quality"]["terminology_precision"],
        "drift_precision_min": aggregate["quality"]["drift_precision"],
        "drift_recall_min": aggregate["quality"]["drift_recall_where_complete"],
        "structural_precision_min": aggregate["quality"]["structural_precision"],
        "structural_recall_min": aggregate["quality"][
            "structural_recall_where_complete"
        ],
        "reviewer_usefulness_min": aggregate["quality"]["reviewer_usefulness"],
        "false_alarms_per_1000_max": aggregate["quality"][
            "false_alarms_per_1000_production_code_files"
        ],
        "cold_seconds_per_1000_source_files_max": aggregate["runtime"][
            "cold_seconds_per_1000_source_files"
        ],
        "corpus_budget_truncations_max": aggregate["truncation"][
            "corpus_budget_truncations"
        ],
        "minimum_cache_reuse_min": aggregate["cache"]["minimum_reuse_rate"],
        "lexical_contract_min": aggregate["quality"]["lexical_contract_rate"],
        "register_accuracy_min": aggregate["quality"]["register_accuracy"],
        "nomination_quality_min": aggregate["quality"][
            "nomination_quality"
        ],
        "structural_contract_min": aggregate["quality"][
            "structural_contract_rate"
        ],
    }
    checks = []
    for name, target in thresholds.items():
        actual = metrics.get(name)
        if actual is None:
            passed = False
        elif name.endswith("_min"):
            passed = actual >= target
        else:
            passed = actual <= target
        checks.append({
            "name": name,
            "actual": actual,
            "target": target,
            "passed": passed,
        })
    checks.append({
        "name": "warm_outputs_match_cold",
        "actual": aggregate["cache"]["all_warm_outputs_match_cold"],
        "target": True,
        "passed": aggregate["cache"]["all_warm_outputs_match_cold"],
    })
    return {
        "configured": True,
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }


_ENGINE_METADATA_KEYS = {
    "name",
    "version",
    "source_sha256",
    "evidence_schema_version",
    "drift_schema_version",
    "validation_schema_version",
    "evaluation_schema_version",
}


def _stored_threshold_targets(thresholds: object) -> dict | None:
    """Recover the threshold configuration recorded inside the results."""
    if not isinstance(thresholds, dict):
        return None
    checks = thresholds.get("checks")
    if not isinstance(checks, list) or not checks:
        return None
    targets: dict = {}
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("name"), str):
            return None
        name = check["name"]
        if name == "warm_outputs_match_cold":
            continue
        if name in targets or "target" not in check:
            return None
        targets[name] = check["target"]
    return targets


def _genuineness_errors(results: dict) -> list[str]:
    """Check the results artifact standalone: untampered, internally consistent."""
    errors: list[str] = []
    if results.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        errors.append(
            "evaluation schema does not match the current evaluator "
            f"({results.get('schema_version')!r} != {EVALUATION_SCHEMA_VERSION})"
        )
    engine = results.get("engine")
    if (
        not isinstance(engine, dict)
        or set(engine) != _ENGINE_METADATA_KEYS
        or engine.get("name") != "glossabet"
        or not isinstance(engine.get("version"), str)
        or not engine.get("version")
        or not _hex_digest(engine.get("source_sha256"))
    ):
        errors.append("engine identity metadata is malformed")
    if not _hex_digest(results.get("manifest_sha256")):
        errors.append("evaluation manifest digest is malformed")

    cases = results.get("cases")
    if not isinstance(cases, list):
        errors.append("evaluation cases are missing or malformed")
        cases = []
    ids = [case.get("id") for case in cases if isinstance(case, dict)]
    if (
        not cases
        or len(ids) != len(cases)
        or not all(isinstance(case_id, str) for case_id in ids)
        or len(set(ids)) != len(ids)
    ):
        errors.append("evaluation case ids are missing or duplicated")
    for case in cases:
        if not isinstance(case, dict):
            continue
        corpus = case.get("corpus")
        if (
            not isinstance(corpus, dict)
            or not _hex_digest(corpus.get("sha256"))
            or not isinstance(corpus.get("files_hashed"), int)
            or isinstance(corpus.get("files_hashed"), bool)
            or corpus["files_hashed"] < 0
        ):
            errors.append(
                f"{case.get('id', '<unknown>')}: corpus digest metadata is malformed"
            )

    method = results.get("method")
    method = method if isinstance(method, dict) else {}
    if method.get("runtime_runs_per_case") != RELEASE_RUNTIME_RUNS:
        errors.append(
            "evaluation results do not contain the required five-run sample"
        )
    graphify_cases = method.get("graphify_cases")
    if (
        not isinstance(graphify_cases, int)
        or isinstance(graphify_cases, bool)
        or not 0 <= graphify_cases <= len(cases)
    ):
        errors.append("evaluation Graphify case count is malformed")
    if (
        method.get("graphify") != "per-case"
        or method.get("external_source_vendored") is not False
    ):
        errors.append("evaluation source method is weakened or stale")

    self_register = results.get("self_register")
    self_nominations = results.get("self_nominations")
    aggregate = results.get("aggregate")
    expected_aggregate = None
    try:
        if cases:
            expected_aggregate = _aggregate(
                cases, self_register, self_nominations
            )
    except (KeyError, TypeError, ValueError):
        errors.append("evaluation case metrics are malformed")
    if expected_aggregate is not None and aggregate != expected_aggregate:
        errors.append("evaluation aggregate is stale or internally inconsistent")

    thresholds = results.get("release_thresholds", {})
    stored_targets = _stored_threshold_targets(thresholds)
    if stored_targets is None:
        errors.append("evaluation release metrics are malformed")
    elif set(stored_targets) != RELEASE_THRESHOLD_NAMES:
        errors.append(
            "evaluation release thresholds are missing required checks"
        )
    else:
        expected_thresholds = None
        try:
            if isinstance(aggregate, dict):
                expected_thresholds = _thresholds(aggregate, stored_targets)
        except (KeyError, TypeError, ValueError):
            errors.append("evaluation release metrics are malformed")
        if expected_thresholds is not None and thresholds != expected_thresholds:
            errors.append("evaluation release thresholds are stale")
    if (
        not isinstance(thresholds, dict)
        or thresholds.get("configured") is not True
        or thresholds.get("passed") is not True
    ):
        errors.append("evaluation release thresholds are not configured and passing")
    return errors


def _currency_errors(results: dict, manifest_path: Path) -> list[str]:
    """Check that the evidence additionally describes the current tree."""
    manifest, manifest_sha256 = _read_manifest(manifest_path)
    errors: list[str] = []
    if results.get("engine") != _engine_metadata():
        errors.append("engine version, schema, or source digest is stale")
    if results.get("manifest_sha256") != manifest_sha256:
        errors.append("evaluation manifest digest is stale")

    cases = results.get("cases")
    if not isinstance(cases, list):
        cases = []
    case_by_id = {
        case.get("id"): case
        for case in cases
        if isinstance(case, dict) and isinstance(case.get("id"), str)
    }
    result_ids = [
        case.get("id") for case in cases if isinstance(case, dict)
    ]
    expected_ids = [source["id"] for source in manifest["sources"]]
    if result_ids != expected_ids or len(case_by_id) != len(cases):
        errors.append("evaluation case ids/order do not match the manifest")

    for source in manifest["sources"]:
        case = case_by_id.get(source["id"])
        if case is None:
            continue
        if case.get("source") != _source_metadata(source):
            errors.append(f"{source['id']}: source metadata is stale")
        corpus = case.get("corpus")
        if (
            not isinstance(corpus, dict)
            or not _hex_digest(corpus.get("sha256"))
            or not isinstance(corpus.get("files_hashed"), int)
            or corpus["files_hashed"] < 0
        ):
            continue
        if corpus != _manifest_corpus_identity(source):
            errors.append(f"{source['id']}: corpus digest does not match manifest")
        if source.get("kind") == "local":
            root = _source_root(source, None, False)
            graphify = source.get("expectations", {}).get("structural") is not None
            current_evidence = build_evidence(
                root, cache=False, graphify=graphify
            )
            current = _corpus_identity(
                root,
                current_evidence,
                graphify=graphify,
            )
            if corpus != current:
                errors.append(f"{source['id']}: local corpus digest is stale")
            expected_structural, _ = _structural_score(
                current_evidence,
                source["glossary"],
                source.get("expectations", {}).get("structural"),
            )
            if case.get("structural") != expected_structural:
                errors.append(
                    f"{source['id']}: local structural evidence is stale"
                )
            expected_register = _register_score(
                current_evidence,
                source["expectations"]["register"],
            )
            if case.get("register") != expected_register:
                errors.append(
                    f"{source['id']}: local register evidence is stale"
                )

    self_evidence = build_evidence(
        PROJECT_ROOT, cache=False, graphify=False
    )
    if results.get("self_register") != _evaluate_self_register(
        manifest["self_register"], self_evidence
    ):
        errors.append("self register evidence is stale")
    if results.get("self_nominations") != _evaluate_self_nominations(
        manifest["self_nominations"], self_evidence
    ):
        errors.append("self nomination evidence is stale")

    expected_graphify_cases = sum(
        source.get("expectations", {}).get("structural") is not None
        for source in manifest["sources"]
    )
    method = results.get("method")
    method = method if isinstance(method, dict) else {}
    if method.get("graphify_cases") != expected_graphify_cases:
        errors.append("evaluation Graphify case count is stale")

    aggregate = results.get("aggregate")
    try:
        if isinstance(aggregate, dict) and results.get(
            "release_thresholds"
        ) != _thresholds(aggregate, manifest.get("release_thresholds")):
            errors.append("evaluation release thresholds are stale")
    except (KeyError, TypeError, ValueError):
        errors.append("evaluation release metrics are malformed")
    return errors


def verify_results(
    results_path: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
    *,
    current: bool = False,
) -> list[str]:
    """Check committed evaluation evidence.

    Always checks genuineness: the artifact is untampered and internally
    consistent, so it truthfully reports the run it records. With
    ``current=True`` (the release gate) it additionally checks currency:
    the evidence describes the current engine source, manifest, and local
    corpora, not an earlier state of the repository.
    """
    try:
        if results_path.stat().st_size > MAX_JSON_BYTES:
            raise EvaluationError(
                f"{results_path}: results exceed {MAX_JSON_BYTES} bytes — "
                "refusing to load"
            )
        results = json.loads(results_path.read_bytes())
    except (OSError, ValueError, RecursionError) as exc:
        raise EvaluationError(
            f"{results_path}: unreadable evaluation results ({exc})"
        ) from exc
    if not isinstance(results, dict):
        raise EvaluationError(f"{results_path}: results must be a JSON object")
    errors = _genuineness_errors(results)
    if current:
        errors.extend(_currency_errors(results, manifest_path))
    return errors


def run(manifest_path: Path, output_path: Path, repositories_root: Path | None,
        fetch: bool, runs: int, selected: set[str]) -> dict:
    manifest, manifest_sha256 = _read_manifest(manifest_path)
    sources = [
        source for source in manifest["sources"]
        if not selected or source["id"] in selected
    ]
    if selected - {source["id"] for source in sources}:
        missing = ", ".join(sorted(selected - {source["id"] for source in sources}))
        raise EvaluationError(f"unknown case(s): {missing}")
    if not sources:
        raise EvaluationError("no evaluation cases selected")

    cache_root = Path(tempfile.mkdtemp(prefix="glossabet-eval-cache-"))
    try:
        cases = [
            _evaluate_source(
                source,
                _source_root(source, repositories_root, fetch),
                runs,
                cache_root,
            )
            for source in sources
        ]
    finally:
        import shutil
        shutil.rmtree(cache_root, ignore_errors=True)

    self_evidence = build_evidence(
        PROJECT_ROOT, cache=False, graphify=False
    )
    self_register = _evaluate_self_register(
        manifest["self_register"], self_evidence
    )
    self_nominations = _evaluate_self_nominations(
        manifest["self_nominations"], self_evidence
    )
    aggregate = _aggregate(cases, self_register, self_nominations)
    thresholds = _thresholds(
        aggregate,
        manifest.get("release_thresholds") if not selected else None,
    )
    result = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "engine": _engine_metadata(),
        "manifest_sha256": manifest_sha256,
        "environment": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "method": {
            "runtime_runs_per_case": runs,
            "graphify": "per-case",
            "graphify_cases": sum(
                source.get("expectations", {}).get("structural") is not None
                for source in sources
            ),
            "external_source_vendored": False,
        },
        "cases": cases,
        "self_register": self_register,
        "self_nominations": self_nominations,
        "aggregate": aggregate,
        "release_thresholds": thresholds,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--fetch", action="store_true")
    source.add_argument("--repositories-root", type=Path)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--verify-results",
        type=Path,
        help="verify committed results are genuine and internally consistent",
    )
    parser.add_argument(
        "--current",
        action="store_true",
        help=(
            "with --verify-results, additionally require the evidence to "
            "describe the current engine source, manifest, and corpora "
            "(the release gate)"
        ),
    )
    args = parser.parse_args(argv)
    if args.current and args.verify_results is None:
        parser.error("--current requires --verify-results")
    if args.case and args.check:
        parser.error(
            "--check gates release thresholds, which a partial --case run "
            "never computes; drop --case or --check"
        )
    if args.case and args.output == DEFAULT_RESULTS:
        parser.error(
            "--case writes a partial document; pass an explicit --output "
            "so the committed release evidence is not overwritten"
        )
    if args.verify_results is not None:
        try:
            errors = verify_results(
                args.verify_results, args.manifest, current=args.current
            )
        except (EvaluationError, OSError, subprocess.TimeoutExpired) as exc:
            print(f"evaluation verification: {exc}", file=sys.stderr)
            return 1
        if errors:
            for error in errors:
                print(f"evaluation verification: {error}", file=sys.stderr)
            return 1
        if args.current:
            print("evaluation results match the current engine and corpus")
        else:
            print("evaluation results are genuine and internally consistent")
        return 0
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    try:
        if args.fetch:
            with tempfile.TemporaryDirectory(prefix="glossabet-eval-repos-") as raw:
                result = run(
                    args.manifest,
                    args.output,
                    Path(raw),
                    True,
                    args.runs,
                    set(args.case),
                )
        else:
            result = run(
                args.manifest,
                args.output,
                args.repositories_root,
                False,
                args.runs,
                set(args.case),
            )
    except (EvaluationError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"evaluation: {exc}", file=sys.stderr)
        return 1

    aggregate = result["aggregate"]
    print(
        f"evaluated {aggregate['cases']} case(s), "
        f"{aggregate['source_files']} source file(s): "
        f"precision {aggregate['quality']['overall_precision']}, "
        f"false alarms {aggregate['quality']['false_alarms']}"
    )
    thresholds = result["release_thresholds"]
    if thresholds["configured"]:
        print("release thresholds: " + ("pass" if thresholds["passed"] else "FAIL"))
    return 1 if args.check and thresholds.get("passed") is not True else 0


if __name__ == "__main__":
    raise SystemExit(main())
