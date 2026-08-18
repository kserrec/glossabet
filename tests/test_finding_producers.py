"""Producer-level tests for every drift and validation finding kind
(Phase 36.5). Each test hands a producer a small hand-built evidence dict
(or `EvidenceIndex` over one) and asserts the finding *record* — so when a
rule breaks, the failing test names the rule, not the command. The
end-to-end pipeline over a scanned corpus is proven once per command in
`test_drift.py` / `test_reconcile.py`."""

from glossabet.glossary.drift import (
    _canonical_fading,
    _canonical_overloaded,
    _index_glossary,
    _parallel_terms,
    _watched_in_use,
)
from glossabet.analysis.evidence_view import EvidenceView
from glossabet.glossary.matching import EvidenceIndex
from glossabet.glossary.reconcile import (
    _concept_findings,
    _concept_vocab,
    _resolve_bindings,
    _structure_findings,
)

# ---- a hand-built RepositoryEvidence, only the parts the producers read ----


def _table(items):
    return {"items": list(items), "truncated": None,
            "coverage": {"complete": True}}


def token(term, count, locations, *, truncated=False):
    """One entry of the ``tokens`` table; ``locations`` = {path: count}."""
    return {
        "term": term, "origin": "domain", "count": count,
        "files": len(locations),
        "modules": len({p.rsplit("/", 1)[0] if "/" in p else "." for p in locations}),
        "locations": [{"path": p, "count": c} for p, c in locations.items()],
        "locations_truncated": truncated,
    }


def identifier(name, count, locations, *, tokens=None):
    return {
        "name": name, "tokens": tokens or name.split("_"), "count": count,
        "files": len(locations),
        "locations": [{"path": p, "count": c} for p, c in locations.items()],
        "locations_truncated": False,
    }


def doc_term(term, count, locations):
    return {
        "term": term, "count": count, "files": len(locations),
        "locations": [{"path": p, "count": c} for p, c in locations.items()],
        "locations_truncated": False,
    }


def evidence(*, tokens=(), identifiers=(), doc_terms=(), files=(), modules=(),
             synonyms=(), overloads=(), complete=True):
    return {
        "vocabulary": {
            "tokens": _table(tokens),
            "identifiers": _table(identifiers),
            "doc_terms": _table(doc_terms),
        },
        "files": {"code": [{"path": p} for p in files], "docs": []},
        "modules": [{"path": m} for m in modules],
        "terminology": {
            "synonym_candidates": {"items": list(synonyms), "dropped_items": 0},
            "overload_candidates": {"items": list(overloads), "dropped_items": 0},
        },
        "skipped": {"corpus_budget": {
            "complete": complete, "production_complete": complete,
        }},
    }


def concept(id, term, status="canonical", **fields):
    return {"id": id, "term": term, "definition": "d", "status": status,
            **fields}


def glossary(*concepts):
    return {"schema_version": 1, "concepts": list(concepts)}


# ---- drift producers ------------------------------------------------------


def test_parallel_term_finding_record():
    g = glossary(concept("run", "Run"))
    canonical, _watched, known = _index_glossary(g)
    ev = evidence(
        tokens=[token("run", 4, {"runs.py": 4}),
                token("execution", 3, {"exec.py": 3})],
        synonyms=[{"a": "run", "b": "execution", "similarity": 0.72,
                   "shared_contexts": ["record", "scheduler"]}],
    )
    matcher = EvidenceIndex(ev, ["Run"])

    findings, reasons = _parallel_terms(EvidenceView(ev), canonical, known, matcher)

    assert reasons == []
    [record] = findings
    assert record["kind"] == "parallel-term"
    assert record["new_term"] == "execution"
    assert record["canonical_term"] == "Run"
    assert record["concept_id"] == "run"
    assert record["signal_strength"] == "strong"  # similarity >= 0.7
    assert record["evidence"]["shared_contexts"] == ["record", "scheduler"]
    assert record["evidence"]["new_occurrence"]["count"] == 3
    assert record["evidence"]["canonical_occurrence"]["count"] == 4
    assert record["scope"] == {"kind": "repository"}


def test_parallel_term_skips_a_term_the_glossary_already_owns():
    g = glossary(concept("run", "Run", aliases=[
        {"term": "execution", "status": "discouraged"}]))
    canonical, _watched, known = _index_glossary(g)
    ev = evidence(
        tokens=[token("run", 4, {"runs.py": 4}),
                token("execution", 3, {"exec.py": 3})],
        synonyms=[{"a": "run", "b": "execution", "similarity": 0.72,
                   "shared_contexts": ["record"]}],
    )
    findings, reasons = _parallel_terms(
        EvidenceView(ev), canonical, known, EvidenceIndex(ev, ["Run"])
    )
    assert findings == [] and reasons == []


def test_parallel_term_sampled_zero_is_suppressed_not_silent():
    g = glossary(concept("run", "Run", scope={"path_prefixes": ["svc"]}))
    canonical, _watched, known = _index_glossary(g)
    ev = evidence(
        tokens=[token("run", 9, {"svc/a.py": 9}),
                # every retained location is outside the scope and the sample
                # was clipped: zero inside the scope proves nothing.
                token("execution", 9, {"lib/x.py": 9}, truncated=True)],
        synonyms=[{"a": "run", "b": "execution", "similarity": 0.8,
                   "shared_contexts": ["record"]}],
    )
    findings, reasons = _parallel_terms(
        EvidenceView(ev), canonical, known, EvidenceIndex(ev, ["Run"])
    )
    assert findings == []
    assert reasons == [
        "1 parallel-term check(s) suppressed because scoped occurrence "
        "evidence retains only a location sample"
    ]


def test_watched_term_in_use_finding_record():
    g = glossary(concept("run", "Run", aliases=[
        {"term": "charge", "status": "discouraged"}]))
    _canonical, watched, _known = _index_glossary(g)
    ev = evidence(tokens=[token("charge", 2, {"gateway.py": 2})])

    findings, reasons = _watched_in_use(watched, EvidenceIndex(ev, ["charge"]))

    assert reasons == []
    [record] = findings
    assert record["kind"] == "watched-term-in-use"
    assert record["certainty"] == "observed"
    assert record["term"] == "charge"
    assert record["status"] == "discouraged"
    assert record["concept_id"] == "run"
    assert record["evidence"]["count"] == 2
    assert record["evidence"]["locations"] == [{"path": "gateway.py", "count": 2}]
    assert record["summary"] == (
        "discouraged term 'charge' still in use: 2 lexical occurrence(s)"
    )


def test_watched_term_absent_is_no_finding():
    g = glossary(concept("run", "Run", status="deprecated"))
    _canonical, watched, _known = _index_glossary(g)
    ev = evidence(tokens=[token("other", 1, {"a.py": 1})])
    assert _watched_in_use(watched, EvidenceIndex(ev, ["Run"])) == ([], [])


def test_canonical_fading_absent_and_fading_records():
    g = glossary(concept("workspace", "Workspace"), concept("ledger", "Ledger"),
                 concept("run", "Run"))
    ev = evidence(
        tokens=[token("ledger", 1, {"a.py": 1}),      # fading (<= 2, no docs)
                token("run", 12, {"a.py": 12})],       # healthy
        doc_terms=[],
    )
    findings = _canonical_fading(g, EvidenceIndex(ev, ["Workspace", "Ledger", "Run"]))

    assert [f["term"] for f in findings] == ["Ledger", "Workspace"]  # sorted
    ledger, workspace = findings
    assert workspace["kind"] == "canonical-fading"
    assert workspace["signal_strength"] == "strong"
    assert workspace["summary"] == "canonical 'Workspace' is absent from code"
    assert workspace["evidence"]["token_counts"] == {"workspace": 0}
    assert ledger["signal_strength"] == "moderate"
    assert ledger["summary"] == "canonical 'Ledger' is fading"
    assert ledger["evidence"]["lexical_occurrences"] == 1
    assert ledger["evidence"]["doc_mentions"] == 0


def test_canonical_fading_needs_complete_counts():
    # A truncated token table cannot prove absence: no finding, no guess.
    g = glossary(concept("workspace", "Workspace"))
    ev = evidence(tokens=[token("run", 12, {"a.py": 12})])
    ev["vocabulary"]["tokens"]["truncated"] = {"dropped_terms": 1}
    assert _canonical_fading(g, EvidenceIndex(ev, ["Workspace"])) == []


def _overload_item(term, dispersion, modules):
    return {
        "term": term, "dispersion": dispersion,
        "modules": [{"path": p, "contexts": c} for p, c in modules.items()],
    }


def test_canonical_overloaded_repository_wide_record():
    g = glossary(concept("session", "Session"))
    canonical, _w, _k = _index_glossary(g)
    ev = evidence(overloads=[_overload_item("session", 0.96, {
        "auth": ["login"], "db": ["commit"], "ml": ["model"],
    })])
    [record] = _canonical_overloaded(EvidenceView(ev), canonical)
    assert record["kind"] == "canonical-overloaded"
    assert record["signal_strength"] == "strong"  # >= 0.95
    assert record["term"] == "Session"
    assert record["evidence"]["dispersion"] == 0.96
    assert [m["path"] for m in record["evidence"]["modules"]] == ["auth", "db", "ml"]
    assert record["summary"] == (
        "canonical 'Session' used in disjoint contexts across 3 module(s)"
    )


def test_canonical_overloaded_scoped_recomputes_dispersion_inside_scope():
    g = glossary(concept("session", "Session",
                         scope={"path_prefixes": ["svc"]}))
    canonical, _w, _k = _index_glossary(g)
    ev = evidence(overloads=[_overload_item("session", 0.9, {
        "svc/a": ["login"], "svc/b": ["commit"], "svc/c": ["model"],
        "lib/x": ["login"],  # outside the scope: ignored
    })])
    [record] = _canonical_overloaded(EvidenceView(ev), canonical)
    assert record["scope"] == {"kind": "path-prefixes", "path_prefixes": ["svc"]}
    assert record["evidence"]["dispersion"] == 1.0  # fully disjoint in scope
    assert [m["path"] for m in record["evidence"]["modules"]] == [
        "svc/a", "svc/b", "svc/c"
    ]


def test_canonical_overloaded_ignores_non_canonical_and_thin_scoped_evidence():
    g = glossary(concept("session", "Session", scope={"path_prefixes": ["svc"]}),
                 concept("draft", "Draft", status="proposed"))
    canonical, _w, _k = _index_glossary(g)
    ev = evidence(overloads=[
        _overload_item("draft", 0.99, {"a": ["x"], "b": ["y"], "c": ["z"]}),
        _overload_item("session", 0.99, {"svc/a": ["x"], "svc/b": ["y"],
                                          "lib/c": ["z"]}),  # 2 in scope < 3
    ])
    assert _canonical_overloaded(EvidenceView(ev), canonical) == []


# ---- validation producers ---------------------------------------------------


def test_resolve_bindings_every_status():
    ev = evidence(
        identifiers=[identifier("payment_service", 1, {"pay/svc.py": 1})],
        files=["pay/svc.py"], modules=["pay"],
    )
    matcher = EvidenceIndex(ev)
    scoped = concept("payment", "Payment", scope={"path_prefixes": ["billing"]},
                     bindings=[{"ref": "symbol:payment_service"},
                               {"ref": "file:pay/svc.py"},
                               {"ref": "module:pay"}])
    assert [b["status"] for b in _resolve_bindings(scoped, matcher)] == [
        "out-of-scope", "out-of-scope", "out-of-scope"
    ]
    plain = concept("payment", "Payment", bindings=[
        {"ref": "symbol:payment_service"}, {"ref": "symbol:GhostService"},
        {"ref": "file:pay/svc.py"}, {"ref": "file:gone.py"},
        {"ref": "module:pay"}, {"ref": "module:gone"},
    ])
    assert [b["status"] for b in _resolve_bindings(plain, matcher)] == [
        "resolved", "unresolved", "resolved", "unresolved",
        "resolved", "unresolved",
    ]
    # An incomplete inventory cannot prove a file/module binding is gone.
    partial = EvidenceIndex(evidence(files=[], modules=[], complete=False))
    assert [b["status"] for b in _resolve_bindings(plain, partial)] == [
        "uncertain", "uncertain", "uncertain", "uncertain",
        "uncertain", "uncertain",
    ]


def test_concept_findings_orphan_binding_and_fragmentation_records():
    canonical = [
        concept("workspace", "Workspace"),                       # orphaned
        concept("payment", "Payment", bindings=[                 # unresolved
            {"ref": "symbol:payment_service"}, {"ref": "symbol:GhostService"}]),
        concept("tenant", "Tenant"),                             # fragmented
    ]
    vocab = {c["id"]: _concept_vocab(c) for c in canonical}
    ev = evidence(
        tokens=[token("payment", 2, {"pay/svc.py": 2}),
                token("tenant", 5, {f"{m}/code.py": 1 for m in "abcde"})],
        identifiers=[identifier("payment_service", 1, {"pay/svc.py": 1})],
    )
    matcher = EvidenceIndex(ev, ["Workspace", "Payment", "Tenant"])

    orphaned, unresolved, fragmented, reasons, binding_reasons = _concept_findings(
        canonical, vocab, matcher
    )
    assert binding_reasons == []

    assert reasons == []
    [orphan] = orphaned
    assert orphan["kind"] == "orphaned-concept"
    assert orphan["concept_id"] == "workspace"
    assert orphan["signal_strength"] == "strong"
    assert orphan["evidence"]["token_counts"] == {"workspace": 0}
    assert orphan["evidence"]["bindings_total"] == 0
    [ghost] = unresolved
    assert ghost["kind"] == "binding-unresolved"
    assert ghost["certainty"] == "observed"
    assert ghost["ref"] == "symbol:GhostService"
    assert ghost["binding_status"] == "unresolved"
    assert ghost["concept_id"] == "payment"
    [spread] = fragmented
    assert spread["kind"] == "fragmentation"
    assert spread["signal_strength"] == "weak"
    assert spread["concept_id"] == "tenant"
    assert spread["evidence"]["module_spread"] == 5


def test_concept_findings_out_of_scope_binding_and_resolved_binding_is_no_orphan():
    canonical = [concept(
        "payment", "Payment", scope={"path_prefixes": ["billing"]},
        bindings=[{"ref": "symbol:payment_service"}],
    )]
    vocab = {c["id"]: _concept_vocab(c) for c in canonical}
    ev = evidence(
        tokens=[token("payment", 3, {"pay/svc.py": 3})],
        identifiers=[identifier("payment_service", 1, {"pay/svc.py": 1})],
    )
    orphaned, unresolved, _f, _r, _b = _concept_findings(
        canonical, vocab, EvidenceIndex(ev, ["Payment"])
    )
    [record] = unresolved
    assert record["kind"] == "binding-out-of-scope"
    assert record["binding_status"] == "out-of-scope"
    assert record["scope"] == {"kind": "path-prefixes", "path_prefixes": ["billing"]}
    # Zero in-scope occurrences and no resolved binding → orphaned inside scope.
    assert [o["concept_id"] for o in orphaned] == ["payment"]


def _group(gid, label, members, member_tokens=None):
    return {
        "id": gid, "label": label, "size": len(members),
        "members_sample": members,
        "member_tokens": member_tokens if member_tokens is not None else [
            t for m in members for t in m.lower().split()
        ],
    }


def test_structure_findings_all_three_records():
    canonical = [concept("authentication", "Authentication"),
                 concept("authorization", "Authorization"),
                 concept("payment", "Payment"), concept("tenant", "Tenant"),
                 concept("run", "Run")]
    vocab = {c["id"]: _concept_vocab(c) for c in canonical}
    structural = {"groups": [
        _group("g0", "community 0", ["AuthenticationFlow", "AuthorizationPolicy"],
               ["authentication", "flow", "authorization", "policy"]),
        _group("g1", "community 1", ["LeaseManager", "SlotClaim", "ReaperWorker",
                                     "AllocationTable", "LeaseTimer"],
               ["lease", "manager", "slot", "claim", "reaper", "worker",
                "allocation", "table", "timer"]),
        _group("g2", "community 2", ["PaymentFlow", "TenantMap", "RunLoop"],
               ["payment", "flow", "tenant", "map", "run", "loop"]),
    ]}

    unnamed, boundary, overloaded, work = _structure_findings(
        structural, canonical, vocab, []
    )

    [lease] = unnamed["items"]
    assert lease["kind"] == "unnamed-structure"
    assert lease["group"] == "community 1"
    assert lease["signal_strength"] == "strong"  # 5 nodes
    assert lease["evidence"]["size"] == 5
    pairs = {tuple(f["concepts"]) for f in boundary["items"]}
    assert ("authentication", "authorization") in pairs
    assert all(f["kind"] == "boundary-mismatch" for f in boundary["items"])
    [region] = overloaded["items"]
    assert region["kind"] == "overloaded-structural-region"
    assert region["group"] == "community 2"
    assert region["concepts"] == ["payment", "run", "tenant"]
    for section in (unnamed, boundary, overloaded):
        assert section["coverage"]["total_items_exact"] is True
    assert work["complete"] is True


def test_structure_findings_confess_missing_member_tokens():
    canonical = [concept("payment", "Payment")]
    vocab = {c["id"]: _concept_vocab(c) for c in canonical}
    structural = {"groups": [{
        "id": "g", "label": "community 0", "size": 2,
        "members_sample": ["PaymentFlow", "Ledger"],  # no member_tokens
    }]}
    unnamed, boundary, overloaded, _work = _structure_findings(
        structural, canonical, vocab, []
    )
    assert unnamed["items"] == []  # the sample still reached "payment"
    for section in (unnamed, boundary, overloaded):
        assert section["coverage"]["total_items_exact"] is False
        assert (
            "1 structural group(s) lack complete member_tokens and fell back "
            "to the display sample"
        ) in section["coverage"]["reasons"]
