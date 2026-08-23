# Spec: Modularize and Type Glossabet's Evaluation Harnesses

Tracked as PLAN.md §3. One pass per session; each pass ends green.

## Purpose

Refactor Glossabet's evaluation and assurance tooling so it is substantially
easier to read, review, type-check, test, and safely modify.

Treat the current behavior as the contract. This is a structural cleanup, not
an opportunity to redesign evaluation methodology, weaken verification, change
product behavior, or regenerate recorded evidence.

The production `glossabet/` package is already proportionately engineered.
Concentrate this phase on `scripts/agent_eval.py`, `scripts/claude_eval.py`,
`evaluation/run.py`, `evaluation/review.py`, their tests, shared support code,
documentation, and packaging checks. At the start these files held roughly
7,400 lines combining host execution, plugin lifecycle, fixtures, trace
parsing, scoring, immutable history, artifact identity, result verification,
and CLI handling.

## Required outcome

1. The four existing executable paths remain valid:
   `python scripts/agent_eval.py`, `python scripts/claude_eval.py`,
   `python evaluation/run.py`, `python evaluation/review.py`.
2. Those files become thin CLI wrappers rather than implementation monoliths.
3. Evaluation logic is divided into cohesive, lane-oriented modules.
4. Live-host execution is separated from offline result verification.
5. Runtime lifecycle state is represented explicitly, never by attaching
   arbitrary attributes to exceptions.
6. Parsed documents become typed structures after validation rather than
   remaining unbounded `dict` trees throughout the system.
7. Evaluation code is included in the mypy gate.
8. Recorded evaluation JSON, attempt history, scenarios, thresholds, and
   schemas remain unchanged.
9. Default offline "genuine" verification continues to behave as recorded
   (the Claude results verifier honestly reports the retained 0/3 batch with
   exit 1; that is the contract, not a failure of the refactor).
10. No authenticated model calls, external fetches, plugin installation, or
    user-level configuration changes occur during this refactor.

## Non-goals

Do not: change production engine behavior or architecture; change evaluation
scenarios, labels, thresholds, scoring formulas, safety gates, trace limits,
or result schemas; regenerate or "freshen" committed evaluation results;
remove failed or historical evaluation attempts; run any `--run`,
`--probe-missing-cli`, reviewer-host, authenticated Codex, or authenticated
Claude operation; run the Codex plugin lifecycle smoke (it changes user-level
plugin state); make `--current` pass by weakening identity checks; add
third-party runtime dependencies; introduce a generic evaluation framework or
plugin system; create a class for every function or a module for every tiny
concept; reformat the repository (Ruff formatting is a separate later phase);
preserve private helper locations merely because tests currently import them
— move tests to the proper new owner instead of filling wrappers with
re-exports.

## Architectural direction

Lane-oriented packages beneath `evaluation/`. Exact filenames may vary when
cohesion demands it, but the responsibility boundaries are required:

```text
evaluation/
  harness/        identity.py (deterministic source/file identity)
                  io.py (bounded JSON, hashing, snapshots, atomic retention)
                  models.py (genuinely shared typed structures)
  codex/          host.py, trace.py, scenarios.py, results.py, runner.py, cli.py
  claude/         host.py, scenarios.py, results.py, runner.py, cli.py
  deterministic/  sources.py, scoring.py, results.py, runner.py, cli.py
  reviewer/       packet.py, host.py, results.py, cli.py
```

No empty ceremonial modules; a responsibility may merge with a neighbor when
it would otherwise be a trivial file. Conversely, do not retain a 1,500-line
module merely to match this sketch.

### Import direction

```text
evaluation.harness ← lane types/pure logic ← host and artifact modules
                   ← runner ← CLI wrapper
```

- `evaluation.harness` imports no evaluation lane.
- One lane does not import another, except that the reviewer lane may consume
  the deterministic lane's explicit public result-reading boundary.
- Offline `results` modules do not import live `host` modules.
- Host modules do not verify stored result history.
- CLI modules compose lane behavior but contain no scoring, fixture, history,
  or lifecycle algorithms.
- Importing an offline verifier must not inspect user configuration, search
  for executables, spawn processes, or alter filesystem state.

Add narrow dependency tests for these load-bearing rules only.

## Type strategy

Read untrusted JSON as `object`; validate and narrow once. `TypedDict` for
stable serialized shapes; frozen dataclasses for runtime state holding `Path`,
subprocess, lifecycle, or cleanup information; `Mapping[str, object]` for
intentionally version-tolerant historical data. Do not model every raw Codex
or Claude event — validate the consumed fields, keep the rest as bounded
opaque data. Failure helpers are `NoReturn`. Replace dynamically attached
exception attributes (`cleanup_verified`, `attempt_usage`, `failed_stage`,
`marketplace_added`, `plugin_added`, `cache_parent`) with explicit structures
such as:

```python
@dataclass
class PluginLifecycle:
    marketplace_added: bool = False
    plugin_added: bool = False
    cache_parent: Path | None = None
    cleanup_verified: bool = False
```

The runner keeps lifecycle state in its own scope, constructs a typed
failed-attempt record, completes cleanup, then re-raises or returns.
`BaseException` instances are never mutated.

## Evaluator-code identity (done in Pass 1)

Hashing only a thin wrapper would let imported implementation change without
changing the recorded evaluator identity. `evaluation.harness.identity`
provides one deterministic function per lane hashing: the entry wrapper,
every Python file under the lane's package, and every harness module those
files import (transitively) — each path with its bytes, sorted
repository-relative, length-prefixed. The existing serialized fields
(`evaluator_sha256`, deterministic `engine.source_sha256`) carry the
aggregate; no schema version is added for internal modularization.

Tests: a lane file change changes only that lane; a harness change changes
every lane importing it; unrelated production or other-lane code does not;
default genuine verification never consults current evaluator bytes;
`--current` does; no committed result is rewritten because its identity is
now stale.

## Compatibility contracts

Preserve CLI arguments, validation rules, exit statuses, and ordinary
stdout/stderr wording; default genuine-versus-current semantics; immutable
attempt history; trace byte/event/command/preview bounds; sensitive canary
detection; unexpected-write detection; plugin cleanup guarantees; scenario
ordering and required generations; reviewer blinding and comparison
arithmetic; deterministic formulas and thresholds; the exact distinction
between a genuine historical result and one current for release; existing
JSON serialization ordering for newly written documents. Private Python
function locations are not compatibility contracts.

## Passes

Each pass finishes with a green repository and stops.

1. **Characterize and establish shared identity** — packages, CLI
   characterization tests, aggregate identity and mutation tests, move only
   clearly duplicated identity/bounded-JSON/hashing primitives. *(done)*
2. **Codex offline results and history** → `evaluation.codex.results`:
   shape, artifact identity, safety/coherence, history validation, record
   construction, immutable retention, genuine-versus-current. Typed shapes
   for stable documents. Verifier imports no host code; a test fails if it
   spawns a subprocess or reads user Codex configuration.
3. **Codex traces and scenarios** — bounded JSONL/event parsing, command
   extraction, trace summaries/redaction, fixture creation, context
   validation, expected-error classification, per-scenario and session-hook
   evaluation, missing-CLI judgment. Pure where possible; fixtures separate
   from judgments; no scenario module installs or removes a plugin.
4. **Codex host lifecycle and thin wrapper** — version probe, command
   execution, temporary marketplace, plugin install/identity/cleanup,
   standalone-skill shadowing, live-run orchestration; explicit lifecycle
   dataclasses; cleanup tests before marketplace creation, after it, after
   plugin install, and during interrupt; wrapper ≤ ~100–150 lines.
5. **Claude offline results and history** — shapes, retention,
   genuine/current, scenario-result consistency, stored event/usage checks,
   input identity. Reuse shared primitives only where semantics match.
   `--verify-history` passes; 0/3 evidence stays honest; no login-state read.
6. **Claude host, scenarios, runner** — environment sanitization, installed
   plugin inspection, version/auth preflight, fixtures, response/event
   parsing, per-scenario evaluation, scratch ownership and cleanup, live-run
   composition; explicit cleanup structures; thin wrapper; cleanup proven
   under success, failure, interruption.
7. **Deterministic sources and scoring** — manifest/path/license validation,
   confined Git fetch config, source/corpus identity, cache and timed builds;
   lexical, register, nomination, drift, structural scoring kept by family;
   production `EvidenceDocument`/`DriftDocument`/`ValidationDocument` types
   used where those exact structures arrive.
8. **Deterministic aggregation, verification, CLI** — per-source assembly,
   aggregate, thresholds, genuineness, currency, result writing, run
   orchestration, parsing; thin wrapper; the 14-of-15 result stays honest;
   `--current` stays strict.
9. **Reviewer lane** — packet construction, host invocation and trace
   parsing, normalization and comparison, offline verification, CLI; thin
   wrapper; offline verification cannot import the live reviewer host.
10. **Gates, packaging, documentation** — mypy covers `evaluation/` and the
    wrappers without `Any` substitutes; dependency tests; every module an
    entry wrapper needs is in the sdist and none in the wheel; update
    `ARCHITECTURE.md`, `docs/CODE-WALKTHROUGH.md`, `EVALUATION.md`, command
    docs; add a concise walkthrough (lane structure, live host vs offline
    verifier, genuine vs current, evaluator identity, immutable history,
    where to add a scenario/score/rule); remove the duplicated "Persisted
    documents are…" line from `ARCHITECTURE.md`. No construction history in
    active architecture docs.

## Final quality requirements

Thin wrappers; no extracted module over ~700 lines without a documented
cohesive reason; no function over ~120 lines unless splitting would obscure
one ordered validation algorithm; mypy-clean evaluation code; no dynamic
exception attributes; no shared `utils.py`; offline verifiers free of live
host modules; identities covering all governing source; no import cycles; no
committed evaluation JSON changed solely by the refactor; no production or
runtime-dependency change.

## Final verification

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked mypy
uv run --locked python scripts/check_workflows.py
uv run --locked python evaluation/run.py --verify-results evaluation/results.json
uv run --locked python scripts/agent_eval.py --verify-results evaluation/agent-results.json
uv run --locked python scripts/claude_eval.py --verify-results evaluation/claude-results.json   # exit 1: recorded 0/3
uv run --locked python scripts/claude_eval.py --verify-history
uv run --locked python evaluation/review.py --verify-results evaluation/reviewer-results.json
uv build --no-sources --out-dir <temporary-dist>
python scripts/check_distribution.py <temporary-dist> --current
python scripts/wheel_smoke.py <temporary-dist>
git diff -- evaluation/*.json evaluation/agent-runs   # must be empty
```

Never run: any evaluator `--run`, `--probe-missing-cli`, `--fetch`,
`--run-reviewer`, the plugin lifecycle smoke, or a `--current` live-evidence
gate that needs newly authorized evidence.
