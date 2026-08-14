"""Exact lexical-unit matching for glossary terms against code evidence.

A one-token term uses the token index. A compound term is observed only when
its ordered tokens occur contiguously inside one identifier spelling, such as
``PaymentRequest`` or ``create_payment_request``. Independent token hits in a
file, module, or repository never establish a compound occurrence.
"""

from __future__ import annotations

from collections import Counter

from glossarize.glossary import path_in_scope, scope_evidence
from glossarize.imports import module_of
from glossarize.tokenize import tokenize_identifier, tokenize_term

LOCATION_SAMPLE = 5


def _contains_sequence(unit: list[str], wanted: list[str]) -> bool:
    width = len(wanted)
    return any(unit[index:index + width] == wanted
               for index in range(len(unit) - width + 1))


def _matching_locations(entry: dict, scope: tuple[str, ...]) -> list[dict]:
    return [
        location for location in entry.get("locations", [])
        if path_in_scope(location["path"], scope)
    ]


def _scoped_entry_occurrence(entry: dict, scope: tuple[str, ...]) -> dict:
    locations = _matching_locations(entry, scope)
    modules = {module_of(location["path"]) for location in locations}
    return {
        "count": sum(location["count"] for location in locations),
        "count_complete": not entry.get("locations_truncated", False),
        "files": len(locations),
        "files_complete": not entry.get("locations_truncated", False),
        "modules": len(modules),
        "locations": locations[:LOCATION_SAMPLE],
        "locations_truncated": bool(entry.get("locations_truncated", False)),
    }


def code_term_occurrence(
    evidence: dict, term: str, scope: tuple[str, ...] | None = None
) -> dict:
    """Return rule-proven lexical occurrences and completeness metadata."""
    wanted = tokenize_term(term)
    empty = {
        "term_tokens": wanted,
        "match_kind": "token" if len(wanted) <= 1 else "lexical-unit",
        "count": 0,
        "count_complete": True,
        "files": 0,
        "files_complete": True,
        "modules": 0,
        "locations": [],
        "locations_truncated": False,
        "scope": scope_evidence(scope),
    }
    if not wanted:
        return empty

    vocabulary = evidence["vocabulary"]
    if len(wanted) == 1:
        section = vocabulary["tokens"]
        entry = next(
            (item for item in section["items"] if item["term"] == wanted[0]),
            None,
        )
        if entry is None:
            return {
                **empty,
                "count_complete": section.get("truncated") is None,
                "files_complete": section.get("truncated") is None,
            }
        if scope is not None:
            return {
                "term_tokens": wanted,
                "match_kind": "token",
                **_scoped_entry_occurrence(entry, scope),
                "scope": scope_evidence(scope),
            }
        return {
            "term_tokens": wanted,
            "match_kind": "token",
            "count": entry["count"],
            "count_complete": True,
            "files": entry["files"],
            "files_complete": True,
            "modules": entry["modules"],
            "locations": list(entry["locations"]),
            "locations_truncated": entry["locations_truncated"],
            "scope": scope_evidence(scope),
        }

    section = vocabulary["identifiers"]
    count = 0
    locations: Counter = Counter()
    locations_truncated = False
    scoped_count_complete = True
    files_complete = section.get("truncated") is None
    for entry in section["items"]:
        unit = entry.get("tokens")
        if not isinstance(unit, list):
            unit = tokenize_identifier(entry["name"])
        if not _contains_sequence(unit, wanted):
            continue
        entry_locations = entry.get("locations", [])
        if scope is None:
            count += entry["count"]
        else:
            entry_locations = _matching_locations(entry, scope)
            count += sum(location["count"] for location in entry_locations)
        for location in entry_locations:
            locations[location["path"]] += location["count"]
        if entry.get("locations_truncated"):
            locations_truncated = True
            files_complete = False
            if scope is not None:
                scoped_count_complete = False

    ranked_locations = sorted(
        locations.items(), key=lambda item: (-item[1], item[0])
    )
    kept = ranked_locations[:LOCATION_SAMPLE]
    if len(ranked_locations) > len(kept):
        locations_truncated = True
        files_complete = False
    modules = {module_of(path) for path in locations}
    return {
        "term_tokens": wanted,
        "match_kind": "lexical-unit",
        "count": count,
        "count_complete": (
            section.get("truncated") is None and scoped_count_complete
        ),
        "files": len(locations),
        "files_complete": files_complete,
        "modules": len(modules),
        "locations": [
            {"path": path, "count": uses} for path, uses in kept
        ],
        "locations_truncated": locations_truncated,
        "scope": scope_evidence(scope),
    }


def code_identifier_occurrence(
    evidence: dict, name: str, scope: tuple[str, ...] | None = None
) -> dict:
    """Exact identifier occurrence used to resolve stable symbol bindings."""
    section = evidence["vocabulary"]["identifiers"]
    entry = next((item for item in section["items"] if item["name"] == name), None)
    if entry is None:
        complete = section.get("truncated") is None
        return {
            "count": 0,
            "count_complete": complete,
            "files": 0,
            "files_complete": complete,
            "modules": 0,
            "locations": [],
            "locations_truncated": False,
            "scope": scope_evidence(scope),
        }
    if scope is not None:
        return {**_scoped_entry_occurrence(entry, scope), "scope": scope_evidence(scope)}
    return {
        "count": entry["count"],
        "count_complete": True,
        "files": entry["files"],
        "files_complete": True,
        "modules": len({
            module_of(location["path"]) for location in entry.get("locations", [])
        }),
        "locations": list(entry.get("locations", [])),
        "locations_truncated": entry.get("locations_truncated", False),
        "scope": scope_evidence(scope),
    }


def doc_term_occurrence(
    evidence: dict, term: str, scope: tuple[str, ...] | None = None
) -> dict:
    """Exact one-token documentation occurrence with the same scope contract."""
    wanted = tokenize_term(term)
    section = evidence["vocabulary"]["doc_terms"]
    if len(wanted) != 1:
        return {
            "count": 0,
            "count_complete": False,
            "scope": scope_evidence(scope),
        }
    entry = next(
        (item for item in section["items"] if item["term"] == wanted[0]), None
    )
    if entry is None:
        return {
            "count": 0,
            "count_complete": section.get("truncated") is None,
            "scope": scope_evidence(scope),
        }
    if scope is None:
        return {
            "count": entry["count"],
            "count_complete": True,
            "scope": scope_evidence(scope),
        }
    scoped = _scoped_entry_occurrence(entry, scope)
    return {
        "count": scoped["count"],
        "count_complete": scoped["count_complete"],
        "scope": scope_evidence(scope),
    }
