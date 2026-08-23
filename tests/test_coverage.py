"""The coverage primitives serialize to exactly the persisted shapes."""

import json

from glossabet.runtime.coverage import (
    capped_collection,
    coverage_ledger,
    location_sample,
)


def test_ledger_keys_and_values_are_the_persisted_contract():
    ledger = coverage_ledger(5, 3, total_items_exact=False, reasons=["b", "", "b", "a"])
    assert list(ledger) == [
        "total_items", "included_items", "dropped_items",
        "total_items_exact", "complete", "reasons",
    ]
    assert ledger == {
        "total_items": 5, "included_items": 3, "dropped_items": 2,
        "total_items_exact": False, "complete": False, "reasons": ["b", "a"],
    }
    assert json.loads(json.dumps(ledger)) == ledger


def test_capped_collection_keeps_items_without_copying_them():
    item = {"name": "x"}
    kept, ledger = capped_collection([item, {"name": "y"}], 1, cap_reason="cap 1")
    assert kept[0] is item
    assert ledger["dropped_items"] == 1
    assert ledger["reasons"] == ["cap 1"] and ledger["complete"] is False


def test_location_sample_records_and_truncation_flag():
    records, truncated = location_sample({"b": 2, "a": 2, "c": 1}, 2)
    assert records == [{"path": "a", "count": 2}, {"path": "b", "count": 2}]
    assert truncated is True
    assert location_sample({}, 3) == ([], False)
