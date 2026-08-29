# Compatibility policy

Glossabet 0.1.0 is an unreleased source alpha. This document defines the
compatibility that the current source tree deliberately carries; it does not
turn every importable module or old JSON file into a supported public API.
Compatibility is specific to a surface: maintainer-owned state, replaceable
output, an external adapter, a Python import path, and immutable evaluation
evidence have different lifetimes.

The version constants and validators in the owning modules are executable
authority. This policy is the human-readable authority for why an older shape
is accepted or rejected and what must be true before a retained path can be
removed. Artifact ownership and cleanup are documented in
[`README.md`](README.md); module ownership is documented in
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## Product formats and accepted versions

“Current only” means that a different version is rejected, treated as stale,
or ignored and rebuilt according to the row. It does not mean that arbitrary
older fields are silently interpreted as the current shape.

| Surface | Current version | What the current product accepts |
| --- | ---: | --- |
| Repository configuration | `1` | Optional root `glossabet.json`. The loader accepts only the integer schema version 1 and rejects unknown fields or malformed input. |
| Repository evidence | `17` | `glossabet-out/evidence.json` is a replaceable output. Product commands build current evidence instead of reopening a persisted evidence file. The narrow in-memory exceptions for hand-built evidence are listed below. |
| Structured glossary | `1` | `glossabet-out/glossary.json` is durable human-governed state. The loader accepts only the integer schema version 1, validates the whole document, and normalizes scope paths in memory without discarding data. |
| Drift report | `7` | `glossabet-out/drift.json` is a replaceable current-version output, not a product input. |
| Validation report | `12` | `glossabet-out/validation.json` is a replaceable current-version output, not a product input. |
| Agent context | `6` | `inspect` emits this bounded stdout protocol; the canonical skill refuses any other context version. The CLI does not persist or reopen it. |
| Managed-context report | `1` | Drift and validation produce this nested report shape. It has no independent persisted reader. |
| Managed host block | `1` | An exact format-1 block can be current. A lower recognized integer format is stale and may be replaced only by an explicit `sync-context`; a higher format is unsupported and classified as edited rather than overwritten automatically. |
| Vocabulary brief | `1` | `brief` emits the current bounded text format. Glossabet has no parser that accepts an older brief as input. |
| Extraction cache | `5` | A cache hit requires cache version 5, the exact Glossabet generator version, repository identity, and valid entry shapes. Every mismatch is a safe cache miss and fresh extraction; the cache is disposable. |

The optional `graphify-out/graph.json` input has no Glossabet schema version:
Graphify owns it. Glossabet performs a bounded tolerant adaptation of only the
recognized fields. Missing, malformed, oversized, or unusable Graphify data
produces a warning and lexical-only analysis rather than a product-format
migration.

No earlier configuration or structured-glossary schema exists in a published
Glossabet release. If either durable format changes, the change must introduce
an explicit new schema and migration or a clear rejection path before the old
shape stops being readable. Generated reports and caches do not receive that
durable-state promise because they can be reproduced from their owners.

## Evaluation formats

Evaluation files are evidence about a particular run, not accepted product
inputs. Their current mirrors and histories must use the exact schema required
by their verifier. Default verification may accept an exact-schema result whose
recorded inputs predate the current tree; `--current` adds release-candidate
identity checks. That distinction permits honest stale evidence, not stale
result schemas.

| Surface | Current version | Acceptance |
| --- | ---: | --- |
| Deterministic manifest | `6` | Exact current maintained input. |
| Deterministic result | `8` | Exact current result schema; default verification may retain older input identity. |
| Codex scenario manifest | `1` | Exact current maintained input. |
| Codex result | `5` | Exact current result schema. |
| Codex history | `1` | Exact append-only history schema. |
| Claude scenario manifest | `1` | Exact current maintained input. |
| Claude result | `1` | Exact current result schema. |
| Claude history | `1` | Exact append-only history schema. |
| Reviewer packet | `1` | Exact packet schema; accepted digest-named packets remain immutable. |
| Reviewer result | `2` | Exact current result schema. |

Raw runs, history entries, and digest-named reviewer packets keep the fields
their original engine emitted, including product fields since retired. They
are immutable testimony and are not examples of what the current product
reader accepts. [`evaluation/README.md`](evaluation/README.md) owns their file
lifecycle and mutation rules.

## Python import paths

The supported application interface is the `glossabet` command (including
`python -m glossabet`), its documented files, and its versioned protocols.
Glossabet 0.1.0 does not declare a general-purpose Python library API. An
importable module is therefore not automatically a stable third-party import
path.

Two exact historical surfaces are nevertheless retained deliberately:

- The `glossabet.glossary.store` module's `__all__` contains its five
  persistence-owned names
  (`GLOSSARY_FILE`, `GlossaryError`, `glossary_sha256`, `load_glossary`, and
  `save_glossary`) plus the ten pre-split aliases `BINDING_KINDS`,
  `GLOSSARY_SCHEMA_VERSION`, `SCOPE_PATHS_KEY`, `STATUSES`,
  `checked_glossary`, `concept_scope`, `path_in_scope`, `scope_evidence`,
  `scopes_overlap`, and `validate_glossary`. The aliases resolve to the object
  in `glossary.model`, `glossary.schema`, or `glossary.scope` that now owns the
  concept.
- `glossabet.agent.agent_context` continues to expose
  `AGENT_CONTEXT_SCHEMA_VERSION`, `AgentContextCoverage`,
  `AgentContextDocument`, `ContextCoverage`, `ContextCoverageRecord`,
  `ContextFreshness`, `ContextGlossarySection`, `ContextLimits`,
  `ContextNamingCandidates`, `ContextRegisterSection`, `ContextTermCandidate`,
  `ContextTerminology`, `LeanVocabularySection`, `ModuleRollupEntry`,
  `ModuleRollupTable`, `Projection`, `RegisterExemplar`, and
  `RegisterExemplars`, although their owner is now
  `glossabet.agent.agent_context_protocol`.

These re-exports are compatibility paths, not alternate owners. New product
code imports the owning module, and no new alias is added merely because code
moves. `glossabet.corpus.scanner` and `glossabet.analysis.graphify` are
intentional internal composition facades; their `__all__` declarations keep
the repository architecture coherent but do not create a supported external
library API. Other module and function locations are internal during the
source alpha unless this document names them.

Neither retained re-export surface is currently deprecated or scheduled for
removal. Its removal must satisfy both the release horizon below and the
specific criteria under “Python re-exports.”

## Field deprecation horizons

No current product field is in a deprecation window. The glossary value
`status: "deprecated"` describes a vocabulary term; it is not a deprecated
JSON field.

After Glossabet's first public release, a durable input field or protected
Python import path must be announced as deprecated in one feature release,
remain accepted throughout the next feature release, and may be removed no
earlier than the following feature release. A patch release never starts,
shortens, or ends that window. Before 1.0, “feature release” means a `0.x`
minor release; after 1.0, removal must also wait for the major version required
by Semantic Versioning. For example, something first deprecated in 0.2.0 stays
available through every 0.3.x release and can be removed no earlier than
0.4.0. The current unreleased 0.1.0 starts no deprecation clock.

This minimum horizon applies to maintainer-authored configuration and glossary
fields because silently losing either can violate user trust. Removal also
requires a schema bump, a tested migration that preserves meaning or a clear
rejection diagnostic, and release notes naming the replacement.

Replaceable evidence, drift, validation, agent-context, brief, and cache fields
do not carry parallel aliases through that horizon. An incompatible change
bumps every affected version, updates all consumers in the same change, and
requires regeneration. Thus retired evidence fields such as `count_complete`,
`files_complete`, and graph `available`, and retired validation fields such as
`graph_available` and `total_findings_complete`, are not accepted aliases in
current documents. Drift's current `total_findings_complete` is a separate
field with its own still-current meaning. Historical evaluation bytes remain
untouched.

## Narrow compatibility exceptions

The exceptions below are the retained legacy or hand-built paths governed by
this policy. Each exists for a named producer or caller and has an
evidence-based removal criterion; age by itself is never sufficient. Ordinary
tolerant parsing of other externally owned Graphify fields is adapter behavior,
not a promise to accept every shape ever observed.

### Graphify `edges`

The Graphify adapter chooses the first non-empty list from top-level `links`
and legacy `edges`. Therefore a missing or empty `links` list falls through to
a non-empty `edges` list; when both are non-empty, `links` wins. Both lists
still count toward the pre-normalization work budget.

Purpose: accept Graphify artifacts from producers that use either top-level
edge spelling without weakening the bounded hostile-input boundary.

**Removal criterion:** remove `edges` only after Glossabet declares and tests a
minimum supported Graphify producer range, authoritative producer contracts for
that whole range use `links`, and maintained fixtures contain no supported
`edges` artifact. There is no scheduled release for removal today.

### Tolerant evidence facts

`glossabet.analysis.evidence_facts` is not a general old-schema loader. It
supports only these conservative reads for direct pure-builder callers and
tests that assemble an `EvidenceDocument` in memory:

- a missing or malformed named `skipped` ledger reads as an empty list; current
  string path entries and legacy mapping entries are passed through for the
  consuming owner to narrow;
- missing corpus-budget information means incomplete, never complete;
- when `production_complete` is absent, a legacy `complete: true` repository
  budget also proves its production subset complete; an explicit
  `production_complete` value takes precedence; and
- a missing `oversized_identifiers` counter means that supported minimal
  in-memory evidence recorded no identifier-tail omission; current schema-17
  evidence always supplies the counter; and
- the optional vocabulary `truncated` marker may be absent.

The CLI does not use these rules to open an arbitrary old
`glossabet-out/evidence.json`. Current commands build schema-17 evidence, and
all ordinary statically known fields are read directly.

**Removal criterion:** narrow or remove a fallback only after every maintained
direct builder caller crosses a validator that guarantees the current evidence
shape, all supported hand-built fixtures have migrated, and a focused test
proves missing completeness data can no longer be mistaken for complete data.
There is no time-based expiry.

### Python re-exports

The two exact re-export sets under “Python import paths” let source-alpha
callers survive the glossary-owner decomposition and agent-context protocol
split. Identity tests prove that every alias resolves to its one current owner,
while dependency tests prevent package internals from treating an alias as
ownership.

**Removal criterion:** a re-export may be removed only after the replacement
owner path is documented, the release horizon has elapsed, repository and
packaged-skill consumers no longer import it, the compatibility test is changed
as an explicit breaking-contract decision, and the changelog names the
removal. There is no scheduled removal today.

### Pre-rename output names

The lexical scanner excludes `glossarize-out/` and `.glossarize/` at every
depth, alongside the current `glossabet-out/` and `.glossabet/` names. This
prevents an old local run from feeding generated vocabulary back into a newer
scan. Graphify provenance separately discounts nodes sourced from
`glossarize-out/` as glossary output; the former `.glossarize/` cache is not a
glossary-provenance source.

Purpose: preserve the no-self-contamination promise for repositories that may
retain pre-rename generated state indefinitely.

**Removal criterion:** these names have no scheduled expiry. Removal requires
an explicit decision to reclaim a name as ordinary repository content plus a
tested migration or identity rule that distinguishes old generated artifacts
without reading them into evidence. Merely observing that the rename is old,
or that a fresh repository does not contain the names, is insufficient.

## Changing or removing compatibility

Every compatibility change is one explicit migration:

1. Identify the exact existing reader, alias, fixture, or exclusion and prove
   its current behavior.
2. Classify the affected state as durable human state, replaceable generated
   output, external input, Python import, or immutable evidence.
3. Add the migration, rejection, or fallback test before changing behavior.
4. Update the owner, all affected versions and consumers, this policy, the
   changelog, evaluation identity, and packaged copies together.
5. For removal, record which criterion above became true; absence from the
   current repository alone is not proof that an external compatibility path
   has no caller.

The ordinary completion gates are the focused compatibility tests, full test
suite, Ruff, mypy, workflow policy, distribution parity, and wheel/plugin smoke
whenever packaged behavior or documentation changes.
