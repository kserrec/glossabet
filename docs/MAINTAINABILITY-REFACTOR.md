# Glossabet Maintainability Refactor Specification

## Status

Implementation plan for the Glossabet codebase examined at commit
`0ff856593bc7e44b8cf57040306cfd17cded8682` (`main`, version `0.1.0`). If the
working branch has advanced, first reconcile this plan with the current tree;
preserve the intent and invariants rather than blindly applying stale paths.

This is a behavior-preserving refactor. It addresses the codebase's most
material readability and maintainability weaknesses without redesigning the
product, changing its heuristics, weakening its safety model, or adding runtime
dependencies.

Each numbered pass below is intentionally sized for one focused agent pass.
Complete exactly one pass, run its required gates, report the result, and stop.
Do not begin the next pass automatically.

## 1. Problem statement

Glossabet is coherent and unusually defensive, but several internal design
choices make it harder to understand and modify safely than it needs to be:

1. Persisted documents and internal domain records are mostly nested,
   string-keyed dictionaries. Many cross-module functions expose only `dict`
   rather than an explicit contract.
2. `EvidenceView` wraps some dictionary lookups but still returns raw
   dictionaries, so it adds ceremony without completing the type-safety job.
3. Important invalid states are rejected procedurally at runtime. For example,
   a finding must carry exactly one of `certainty` and `signal_strength`.
4. Coverage and omission accounting is valuable but represented through
   subtle dictionary conventions that are easy to misuse.
5. The project has extensive annotations but no enforced static type checker
   or linter.
6. Four modules carry too many responsibilities: `corpus/scanner.py`,
   `analysis/graphify.py`, `glossary/store.py`, and
   `glossary/reconcile.py`.
7. Heuristic policy is embedded as scattered constants and arithmetic,
   obscuring which choices are product policy rather than structural truth.
8. Some production comments preserve development-phase history or repeatedly
   argue for invariants already expressed elsewhere.
9. The filesystem code makes strong hostile-repository claims that should be
   checked against its exact concurrency threat model.
10. No current evidence establishes a material runtime bottleneck. Performance
    work therefore needs measurement before optimization.

## 2. Desired outcome

At completion:

- Every persisted JSON document has a named, statically checked schema type.
- Cross-module production APIs no longer return or accept unexplained bare
  `dict` values.
- Important domain distinctions are visible in types, especially observed
  versus heuristic findings and exact versus partial coverage.
- `EvidenceView` is a genuinely typed read boundary rather than a thin wrapper
  over unknown dictionaries.
- Ruff and mypy are required local and CI gates.
- The four largest modules are decomposed along existing responsibilities,
  without introducing a fragmented collection of tiny files.
- Heuristic weights and thresholds are explicit policy with pure, directly
  tested scoring functions.
- Production comments describe lasting reasons, invariants, algorithms, and
  platform hazards rather than development history.
- Security documentation claims exactly what the filesystem implementation
  enforces.
- Performance has a reproducible baseline; production optimization occurs only
  when profiling identifies a real hotspot.

## 3. Binding invariants

These constraints apply to every pass.

### 3.1 Public behavior must remain unchanged

Unless a later, separately approved feature specification says otherwise, do
not change:

- CLI commands, arguments, help text, stdout/stderr text, or exit statuses.
- JSON filenames, field names, nesting, ordering, serialization, or schema
  versions.
- Glossary validation acceptance/rejection behavior.
- Scan roles, exclusions, budgets, limits, or symlink rules.
- Heuristic formulas, weights, thresholds, rankings, caps, or findings.
- Coverage, completeness, omission, and epistemic-status semantics.
- Cache identity or cold/warm byte identity.
- AgentContext lean/full projections or byte ceilings.
- `skill/SKILL.md`, the engine/skill protocol, or human-approval boundary.
- Plugin, installer, hook, package, or release behavior.
- Supported Python versions or operating systems.

Schema-version bumps are forbidden because this work changes internal
representation, not the serialized contracts.

### 3.2 Preserve the architectural direction

- Runtime primitives remain below corpus analysis.
- Corpus collection remains below evidence aggregation.
- Analysis remains below glossary reconciliation.
- Agent and installation surfaces consume lower layers; lower layers must not
  import command or host-integration modules.
- Put each type in the lowest layer that owns its meaning. Do not create one
  central `models.py` that imports the entire application.
- Update `tests/test_module_dependencies.py` whenever a module moves or is
  extracted. New cycles and upward imports are prohibited.

### 3.3 Preserve the dependency policy

- Add no runtime dependency.
- Ruff and mypy are development-only dependencies and must be locked.
- Prefer `TypedDict`, `Literal`, `TypeAlias`, protocols, dataclasses, and
  standard-library generics.
- Do not add Pydantic, attrs, a JSON-schema runtime, a CLI framework, or a
  serialization framework as part of this refactor.

### 3.4 Separate persisted representation from internal representation

- Persisted JSON remains ordinary dictionaries, lists, and JSON primitives.
- Use `TypedDict` for persisted document shapes because it adds no runtime
  object or serialization cost.
- Use frozen/slotted dataclasses only when an internal value owns behavior or
  must make an invalid state unrepresentable.
- Conversion to a persisted dictionary must happen at a deliberate document
  boundary, not repeatedly throughout the call graph.
- Never use `Any` merely to silence the checker. Parse untrusted JSON as
  `object`, validate it, and narrow it into the appropriate contract.

## 4. Per-pass execution contract

For every pass:

1. Read the current implementations and focused tests before editing.
2. State the exact invariant being preserved and the responsibility being
   changed.
3. Keep the patch limited to that pass. Do not opportunistically rename,
   reformat, optimize, or rewrite neighboring code.
4. Add or update focused tests for the new internal contract.
5. Run focused tests first, then the required global gates.
6. If a public artifact, report, ranking, message, or exit status changes,
   treat that as a regression and fix it. Do not bless the new output.
7. Do not regenerate committed evaluation results to hide a difference.
8. When production package bytes change, rebuild the checked-in plugin only
   through `scripts/build_plugin.py`; never hand-edit its wheel, skill mirror,
   manifest, or digest.
9. If the scoped work cannot be completed with all required gates green in one
   coherent patch, stop before leaving a partial migration. Report the blocking
   seam and propose an A/B split; do not leave two competing APIs unless this
   specification explicitly defines a temporary compatibility boundary.
10. End with a concise report: files changed, invariant preserved, tests run,
   and any unresolved issue. Then stop.

## 5. Standard verification gates

Use the repository's locked environment. Commands may be adapted to the local
runner, but their substance must not be weakened.

### Gate A: every pass

```bash
uv sync --locked
uv run --locked ruff check .
uv run --locked mypy glossabet
uv run --locked pytest -q
uv run --locked python scripts/run_walkthrough.py
uv run --locked python scripts/check_workflows.py
```

Ruff and mypy become available in Pass 1. Before that pass is merged, run the
existing gates that are available.

### Gate B: passes touching analysis, glossary, agent contracts, or heuristics

```bash
uv run --locked python evaluation/run.py --verify-results evaluation/results.json
uv run --locked python scripts/agent_eval.py --verify-results evaluation/agent-results.json
uv run --locked python evaluation/review.py --verify-results evaluation/reviewer-results.json
```

These commands verify stored evidence; they do not authorize rewriting it.

### Gate C: passes touching production package code, packaging, installation,
plugins, skills, or workflows

```bash
uv build --no-sources --clear
uv run --locked python scripts/build_plugin.py dist
uv run --locked python scripts/check_distribution.py dist
uv run --locked python scripts/wheel_smoke.py dist
```

Commit the plugin rebuild produced by the canonical script when required.

## 6. Ordered implementation passes

## Pass 1 — Add enforceable static-quality gates

### Objective

Introduce reproducible linting and type checking without pretending the
existing raw-dictionary model is already strict.

### Work

- Add pinned, development-only Ruff and mypy dependencies in `pyproject.toml`
  and refresh `uv.lock`.
- Configure Ruff for Python 3.10 and enable objective correctness/import rules:
  `E4`, `E7`, `E9`, `F`, `I`, and `B`. Do not enable line-length enforcement or
  run a repository-wide formatter in this pass.
- Configure mypy over `glossabet/` with:
  - Python 3.10 semantics.
  - `check_untyped_defs = true`.
  - `no_implicit_optional = true`.
  - warnings for unused ignores, redundant casts, unused config, and return
    values that unexpectedly become `Any`.
  - temporary allowance for unparameterized dictionaries and incompletely
    typed definitions; later passes remove this allowance.
- Do not add global `ignore_errors`, broad module exclusions, or blanket
  `# type: ignore` comments.
- Add one Linux/Python-3.10 `static` job to
  `.github/workflows/quality.yml`. It must perform a locked sync, Ruff, and
  mypy exactly once rather than repeating them across all 15 test-matrix
  cells.
- Make the package job depend on both the complete OS/Python test matrix and
  the static job.
- Update `scripts/check_workflows.py` and its tests so the static gate and
  dependency chain cannot silently be removed, skipped, softened, or reordered.
- Fix only the lint/type defects needed for this initial honest baseline.

### Acceptance

- Ruff and mypy pass locally and in the reusable quality workflow.
- The workflow checker rejects removal or weakening of either static command.
- `uv sync --locked` succeeds on Python 3.10.
- No runtime dependency or production behavior changes.
- Gates A and C pass.

## Pass 2 — Type the JSON and coverage foundations

### Objective

Give the lowest-level document primitives explicit names before higher-level
schemas depend on them.

### Work

- Add a low-level JSON type module under `glossabet/runtime/` containing
  aliases for JSON scalars, arrays, objects, and values that work on Python
  3.10.
- In `runtime/coverage.py`, define explicit persisted shapes for:
  - `CoverageLedger`.
  - A capped collection/section.
  - Location/count samples where appropriate.
- Annotate `coverage_ledger`, `capped_collection`, `capped_section`,
  `coverage_reasons`, and their callers at the runtime/corpus boundary.
- Give bounded-read status values precise literal types while preserving the
  existing `BoundedRead` dataclass and serialized behavior.
- Parameterize collections in runtime and corpus public signatures. Local
  temporary dictionaries may remain local when their complete shape does not
  cross a module boundary.
- Add focused contract tests where they add value; retain all runtime
  validation tests.
- Tighten mypy for `glossabet.runtime.*` and the touched corpus modules. Do not
  tighten untouched higher layers yet.

### Acceptance

- Coverage objects serialize to the exact previous dictionaries.
- All exactness, completeness, dropped-count, and reason tests remain green.
- No schema constants or artifact bytes change.
- Gates A and C pass.

## Pass 3 — Define RepositoryEvidence and complete EvidenceView

### Objective

Turn RepositoryEvidence into an explicit cross-module contract and make
`EvidenceView` genuinely type-safe.

### Work

- Create `glossabet/analysis/evidence_types.py` or an equivalently scoped
  module owned by the analysis layer.
- Define `TypedDict` contracts for the top-level `EvidenceDocument` and its
  meaningful subdocuments: identity/provenance, totals, files, modules,
  imports, vocabulary tables, terminology, naming candidates, structural
  groups, configuration, monorepo state, skipped/corpus budgets, and coverage.
- Reuse the runtime coverage types rather than redeclaring their keys.
- Annotate `build_evidence`, `persist_evidence`, and the helper folds/builders
  that construct these sections.
- Change `EvidenceView.__init__` to accept the typed evidence contract.
- Give every `EvidenceView` method a precise return type. No method may return
  an unexplained bare `dict` or `list[dict]`.
- Retain the view as the named read boundary; do not make consumers resume
  scattered raw top-level key access.
- Correct its misleading documentation: the view centralizes key spellings and
  improves static checking, but it does not make arbitrary consumer mistakes
  fail at import time.
- Update immediate consumers and document-key tests. Do not change any key or
  returned object identity/copying behavior.
- Tighten mypy for the analysis evidence producer and view.

### Acceptance

- Existing evidence, warm/cold identity, document-key, scan, and inspect tests
  pass unchanged.
- The example walkthrough emits identical artifacts and terminal output.
- `EvidenceView` has no bare-container return annotations.
- Gates A, B, and C pass.

## Pass 4 — Type the structured glossary and its store boundary

### Objective

Make `glossary.json` an explicit schema without changing what schema version 1
accepts.

### Work

- Add glossary-owned schema types for:
  - `GlossaryDocument`.
  - `ConceptRecord`.
  - `AliasRecord`.
  - `BindingRecord`.
  - Repository-wide and path-prefix scope records.
  - Vocabulary status and binding-kind literals.
- Preserve the current accepted status set exactly. Do not narrow concept or
  alias statuses as part of a type refactor.
- Treat input loaded from JSON/stdin as `object`; only return a typed glossary
  after complete validation.
- Annotate glossary hashing, loading, saving, scope lookup, ownership checks,
  and command boundaries.
- Keep persisted JSON as dictionaries and preserve deterministic serialization.
- If an internal scope value benefits from a frozen dataclass or tuple, convert
  only at the validated boundary and preserve the current external shape.
- Tighten mypy for `glossary/store.py`, `glossary/glossary_commands.py`, and
  directly owned schema helpers.

### Acceptance

- Every existing valid and hostile glossary fixture receives the same result
  and diagnostics in the same order.
- Hashes and saved bytes remain identical.
- No glossary schema version change.
- Gates A, B, and C pass.

## Pass 5 — Make findings and report sections structurally explicit

### Objective

Represent observed facts and heuristic signals as different types and remove
the runtime API that permits both/neither epistemic fields.

### Work

- Define typed persisted records for:
  - The common finding fields.
  - `ObservedFinding`, requiring `certainty`.
  - `HeuristicFinding`, requiring `signal_strength`.
  - The union `FindingRecord`.
  - Typed finding sections and findings documents.
- Replace the single XOR-style `finding(...)` constructor with two explicit
  factories, such as `observed_finding(...)` and
  `heuristic_finding(...)`.
- Migrate every producer in drift and reconciliation. Once all call sites are
  migrated, remove the ambiguous internal constructor rather than leaving two
  APIs indefinitely.
- Keep the persisted flat dictionary shape exactly the same, including
  producer-specific fields such as `concept_id`, `ref`, `group`, and
  `concepts`.
- Type `FindingsDocumentView`, `DriftView`, `ValidationView`, and section
  rendering against the union.
- Preserve coverage and suppression behavior exactly.
- Add tests proving that producer APIs cannot construct both or neither status,
  while retaining the runtime validation/renderer tests.
- Tighten mypy for `glossary/findings.py`, `drift.py`, `matching.py`, and
  `reconcile.py` at their public boundaries.

### Acceptance

- Drift and validation JSON and terminal reports are byte-for-byte compatible.
- Every finding still has exactly one epistemic field.
- Existing finding-producer, document-key, drift, and reconcile tests pass.
- Gates A, B, and C pass.

## Pass 6 — Type AgentContext and remaining production boundaries

### Objective

Finish named contracts above the evidence/glossary layers and prepare the whole
package for strict checking.

### Work

- Define agent-owned types for AgentContext v3, projection omissions, lean/full
  coverage, register exemplars, managed-context inspection, and brief data.
- Annotate `agent_context.py`, `brief.py`, `managed_context.py`,
  `context_sync.py`, and their command entry points.
- Type installer and Claude-plugin result records where they cross module
  boundaries.
- Type CLI dispatch without introducing a framework or changing lazy imports.
  A small typed namespace/protocol per command is acceptable; a large generic
  command abstraction is not.
- Replace remaining exported `-> dict`, `dict` parameters, and `list[dict]`
  annotations with owned types or parameterized mappings.
- Use `Mapping` for read-only inputs and concrete `dict` only when mutation or
  the persisted representation requires it.
- Tighten mypy for agent, install, and CLI modules.

### Acceptance

- Lean and full AgentContext JSON remain byte-identical for fixed inputs.
- Brief and managed-block behavior remains identical.
- Install/plugin tests remain green on all supported platforms.
- Gates A, B, and C pass.

## Pass 7 — Close the strict static-type gate

### Objective

Remove the temporary migration allowances and make the entire production
package continuously type-checked.

### Work

- Enable package-wide:
  - `disallow_untyped_defs`.
  - `disallow_incomplete_defs`.
  - `disallow_any_generics`.
  - `warn_return_any`.
  - strict equality checks where compatible with the validated JSON model.
- Remove staged per-module relaxations.
- Eliminate accidental `Any` propagation at cross-module and persisted-document
  boundaries.
- Permit narrowly scoped `Any` or `# type: ignore[code]` only when a stdlib API
  genuinely forces it; every exception needs a nearby reason and the exact
  mypy error code.
- Add a test or lightweight source check preventing new bare container
  annotations in exported production functions.
- Do not chase maximal theoretical strictness inside harmless local temporary
  structures if doing so worsens the code. The binding requirement is strict
  cross-module and document-boundary typing.

### Acceptance

- One non-excluded `mypy glossabet` invocation enforces the final policy.
- No `ignore_errors`, blanket excludes, unqualified ignores, or fake protocol
  casts are present.
- Ruff and mypy are mandatory in CI.
- Gates A, B, and C pass.

## Pass 8 — Isolate heuristic policy without changing it

### Objective

Make experimental judgment calls readable and testable while preserving every
current score, threshold, ranking, and finding.

### Work

- Group terminology and importance weights/caps into immutable policy objects
  owned by the analysis layer. Keep reconciliation-only thresholds in the
  glossary layer to preserve dependency direction.
- Extract pure functions for module scores, term scores, synonym gates,
  overload dispersion decisions, and structural match strength where this
  reduces mixed calculation/report-building code.
- Give each field a semantic name. Avoid anonymous tuple positions or generic
  `weights` dictionaries.
- Keep the current defaults numerically identical.
- Allow tests to inject a policy directly; do not expose a new CLI/config-file
  feature in this refactor.
- Add tests for:
  - Exact compatibility of current default outputs.
  - Deterministic tie-breaking.
  - Important monotonic relationships where they are genuinely intended.
  - Boundary behavior immediately below/at/above each threshold.
- Update comments to call these values calibrated nomination policy, not
  measured probability or truth.

### Acceptance

- Stored evaluation verification and every expected ranking remain unchanged.
- No default output bytes or schema versions change.
- The formulas can be located and tested without reading report-assembly code.
- Gates A, B, and C pass.

## Pass 9 — Decompose the repository scanner

### Objective

Separate path trust policy and budget accounting from traversal orchestration.

### Target structure

Use names consistent with the repository, but aim for responsibilities like:

- `corpus/path_policy.py`: sensitive names, self-output exclusions, exact-name
  rules, and symlink target classification.
- `corpus/walk_budget.py`: `CorpusBudget`, inclusion/reclassification, samples,
  and coverage serialization.
- `corpus/scanner.py`: deterministic traversal, file/directory classification,
  monorepo detection, and the existing public facade.

### Work

- Move code; do not redesign policies or alter constants.
- Preserve existing public imports through `scanner.py` where other modules or
  documented tests rely on them.
- Keep path-policy helpers below traversal; they must not import evidence or
  repository-glossary discovery.
- Update dependency-ratchet tests to cover the extracted modules and prevent
  cycles/upward imports.
- Keep platform-specific and hostile-path tests with the module that owns the
  behavior.
- Avoid tiny one-function modules; combine code by responsibility.

### Acceptance

- Scanner inventories, skip reasons, samples, role decisions, and corpus
  ledgers are identical.
- Cold/warm evidence remains byte-identical.
- `scanner.py` is an orchestration/facade module rather than the owner of every
  policy and data structure.
- Gates A, B, and C pass.

## Pass 10 — Decompose glossary storage and validation

### Objective

Separate schema validation and path-scope ownership from persistence.

### Target structure

- `glossary/model.py`: persisted schema types and status/binding literals
  introduced in Pass 4.
- `glossary/scope.py`: scope normalization, path membership, overlap, and the
  ownership index.
- `glossary/schema.py`: bounded validation and diagnostic accumulation.
- `glossary/store.py`: digest, confined load/save, and stable public facade.

### Work

- Extract existing behavior without replacing the validator or narrowing the
  schema.
- Preserve public imports through `store.py` where needed.
- Ensure schema validation depends on model/scope primitives, while neither
  model nor scope imports persistence or commands.
- Keep diagnostic ordering and bounded error collection unchanged.
- Update dependency and schema tests.

### Acceptance

- Valid, invalid, oversized, Unicode, scoped-ownership, and hostile glossary
  tests are unchanged in outcome and text.
- Saved bytes and semantic hashes are identical.
- Each resulting module has one clear reason to change.
- Gates A, B, and C pass.

## Pass 11 — Decompose the Graphify adapter

### Objective

Separate untrusted input adaptation/provenance from normalized group analysis.

### Target structure

- `analysis/graphify_input.py`: bounded file reading, tolerant field extraction,
  schema-shape handling, glossary/self-output provenance filtering, Git
  freshness, and warnings.
- `analysis/graphify_groups.py`: normalized groups, member tokens, cohesion/god
  node calculations, caps, coverage, and structure nominations.
- `analysis/graphify.py`: stable facade exposing the existing public builder,
  disabled state, and candidate entry points.

### Work

- Preserve tolerant degradation: malformed or unsupported graph shapes remain
  warnings/lexical-only behavior, not new hard failures.
- Preserve every input-work and output cap.
- Do not change freshness semantics or attempt to authenticate Graphify data.
- Update dependency tests so neither extracted module imports commands,
  glossary state, or agent code.

### Acceptance

- Complete, truncated, malformed, unavailable, stale, and unverified Graphify
  fixtures produce identical normalized documents and warnings.
- Structural evaluation labels remain unchanged.
- Gates A, B, and C pass.

## Pass 12 — Decompose reconciliation

### Objective

Leave `reconcile.py` responsible for composing a validation document, not every
binding and structural algorithm it invokes.

### Target structure

- `glossary/binding_validation.py`: stable binding parsing/resolution and
  orphan/unresolved/fragmentation evidence.
- `glossary/structural_validation.py`: graph usability, structural concept
  matching, match-work coverage, and structural findings.
- `glossary/reconcile.py`: build orchestration, reuse of drift, final coverage
  assembly, `ValidationView`, rendering, and command handler.

### Work

- Extract along these existing seams without changing algorithms.
- Pass typed inputs/results rather than reaching into shared mutable documents.
- Keep finding sorting, caps, suppression rules, and total-completeness logic in
  their current owning algorithms.
- Preserve the existing `build_validation` and command-facing API through the
  facade.
- Add dependency tests preventing extracted producers from importing command
  or rendering code.

### Acceptance

- Every validation fixture and producer test remains identical.
- `reconcile.py` reads as a top-level validation pipeline.
- No new circular imports or duplicated coverage logic.
- Gates A, B, and C pass.

## Pass 13 — Clean comments and synchronize architecture documentation

### Objective

Make the source read like a durable codebase rather than an implementation
transcript, without deleting essential rationale.

### Work

- Remove production-code references to numbered implementation phases and
  replace each with the lasting reason or invariant it was meant to explain.
- Remove comments that merely translate the next line into prose or repeat the
  same invariant already stated in the module docstring.
- Retain comments explaining:
  - Threat boundaries and why ordinary-looking filesystem operations are not
    used.
  - Non-obvious Unicode/platform behavior.
  - Mathematical formulas and algorithmic bounds.
  - Why partial evidence suppresses or downgrades a conclusion.
  - Compatibility constraints that tests alone do not make evident.
- Prefer neutral explanations over argumentative phrases such as “the one
  way” or “never smuggled,” unless uniqueness is itself an enforced invariant.
- Update `ARCHITECTURE.md` to show the new module layout and typed document
  boundaries.
- Correct stale paths and the EvidenceView import-time-error claim wherever it
  appears.
- Do not rewrite user-facing product prose or `skill/SKILL.md` in this pass.

### Acceptance

- `rg` finds no unexplained `Phase N`/`Phase N.M` references in production
  Python.
- Comments still document all material trust, partiality, and compatibility
  decisions.
- No executable behavior changes.
- Gates A, B, and C pass.

## Pass 14 — Resolve the filesystem race/threat-model question

### Objective

Ensure hostile-repository claims match the guarantees actually provided by the
filesystem primitives.

### Work

- State explicitly whether the supported threat model includes:
  1. A repository that is hostile but not concurrently mutated during a
     command.
  2. Ordinary concurrent edits.
  3. An adversarial process racing path components between checks and use.
- Inventory check/use sequences in artifacts, glossary loading/saving,
  managed-context writes, cache operations, scanner reads, and installation.
- Add deterministic tests for every practical symlink-swap or target-replace
  race the implementation claims to resist. Keep POSIX-only tests properly
  skipped on Windows; test Windows behavior separately rather than assuming
  POSIX descriptors.
- Resolve each discovered mismatch in one of two honest ways:
  - If active adversarial races are in scope, use descriptor-relative/no-follow
    primitives or an equivalent fail-closed design where the platform supports
    them, and define the safe behavior on unsupported platforms.
  - If they are out of scope, narrow comments and `SECURITY.md` so they claim
    protection against hostile initial paths and detected ordinary changes,
    not immunity to an actively racing local process.
- Do not perform a broad filesystem rewrite without a failing test or a
  documented guarantee it is needed to enforce.

### Acceptance

- Every security claim names the concurrency assumption under which it holds.
- Tests demonstrate the guarantees the project continues to claim.
- Linux, macOS, and Windows behavior remains intentional and documented.
- Gates A, B, and C pass.

## Pass 15 — Establish a performance baseline and optimize only proven hotspots

### Objective

Replace performance speculation with reproducible evidence.

### Work

- Add a standard-library-only profiling/benchmark script under `scripts/`.
- Measure at least:
  - Cold and warm evidence construction on the payment-service example.
  - A representative multi-language fixture.
  - Compound matching over a bounded glossary.
  - Terminology pair analysis.
  - Complete and truncated Graphify fixtures.
  - Lean and full AgentContext projection/serialization.
- Report median wall time, peak Python memory (`tracemalloc`), output bytes, and
  relevant work/coverage ledger counts. Do not create brittle absolute CI
  timing failures across heterogeneous runners.
- Record how to reproduce the measurements in `docs/PERFORMANCE.md`, including
  interpreter, platform, fixture identity, repetitions, and warm-up policy.
- Profile before editing production code.
- Make a production optimization in this pass only if one hotspot clearly
  dominates and a simple change provides a repeatable material improvement
  without changing output or increasing architectural complexity.
- Otherwise commit the benchmark and the finding that no justified optimization
  was identified. Do not manufacture a performance patch.
- If several independent hotspots are proven, create one subsequent pass per
  hotspot. Each must include a before/after benchmark and all compatibility
  gates.

### Acceptance

- Another developer can reproduce the measurements with one documented
  command.
- Benchmark inputs are fixed and do not require network access.
- Any optimization shows a repeatable improvement on the same machine and
  produces identical artifacts/findings.
- Gates A, B, and C pass.

## 7. Final definition of done

The refactor is complete only when all of the following are true:

- The full test suite passes on Python 3.10–3.14 across Linux, macOS, and
  Windows CI.
- Ruff and one package-wide mypy invocation are required and green.
- There are no broad checker suppressions or unexplained `Any` values at
  persisted-document/cross-module boundaries.
- RepositoryEvidence, glossary, findings, validation, drift, AgentContext,
  coverage, and managed-context records have named types.
- Observed and heuristic findings cannot be confused by the construction API.
- `EvidenceView` returns precise types and remains the deliberate read boundary.
- The four large modules have been decomposed along the specified seams without
  cycles or gratuitous micro-modules.
- Default heuristic results are unchanged and the policy is independently
  testable.
- No public JSON schema version, field, ordering, command output, or exit status
  changed.
- The canonical skill remains byte-identical.
- Stored deterministic, agent, and reviewer evidence still verifies as genuine
  and internally consistent.
- The wheel, source distribution, plugin wheel, digest, hooks, and smoke tests
  pass through the canonical build chain.
- Security documentation makes no stronger filesystem-race claim than tests
  and implementation support.
- Performance has a reproducible baseline, and any optimization is backed by a
  measured result rather than intuition.

## 8. Explicit non-goals

Do not use this effort to:

- Change Glossabet's product scope or user workflow.
- Add a daemon, database, network access, parser framework, or model call.
- Replace lexical analysis with language-specific AST parsers.
- Change the glossary ontology or introduce a migration system.
- Tune heuristics or relabel evaluation expectations.
- Remove coverage or omission accounting.
- Change Graphify's trust level or make it required.
- Rewrite the skill or automate human approval.
- Reformat the entire repository.
- Pursue an arbitrary line-count or test-count target.
- Publish a package or marketplace plugin.

## 9. Agent completion format for each pass

End every pass with exactly these categories:

1. **Completed:** the scoped structural change.
2. **Compatibility:** what was proven unchanged.
3. **Verification:** exact commands and outcomes.
4. **Files:** concise list of important files added/moved/changed.
5. **Open issues:** only blockers or evidence relevant to the next pass.
6. **Stop:** explicitly state that the next pass has not begun.

## 10. Reusable one-pass agent prompt

Attach or provide this specification, then use the following prompt with the
desired pass number substituted:

```text
Work in the Glossabet repository and execute only Pass <N> from the attached
Glossabet Maintainability Refactor Specification.

Before editing, inspect the current tree and the tests named by that pass. If
the repository has advanced beyond the specification's anchor commit, adapt
paths and mechanics while preserving the pass's intent and all binding
invariants. Make the implementation changes; do not merely propose them.

Keep the patch strictly within Pass <N>. Preserve public behavior and serialized
artifacts. Run focused tests followed by every verification gate required by
the pass. Do not rewrite expected outputs to conceal a compatibility change.
If the work cannot be completed as one coherent green patch, stop before a
partial migration and propose the smallest A/B split.

Finish using the six-category completion format in Section 9, then stop. Do not
start Pass <N+1>.
```
