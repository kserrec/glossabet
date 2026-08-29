# Evaluation directory authority

This directory contains maintained evaluation inputs, evaluator implementation,
and retained evidence. For the public methodology, measurements, claims, and
limitations, read [`../EVALUATION.md`](../EVALUATION.md). This file answers a
different question: which repository file owns each evaluation concern, and
which files are generated rather than edited.

## Authority rules

- Scenario manifests, labels, prompts, response schemas, and fixtures are
  maintained inputs. Change them only with the tests and evaluation identity
  updates that define the same contract.
- Result files are evidence produced by their lane. Never edit a score,
  identity, status, or failure by hand to make a verifier pass.
- A retained result may be genuine without being current or successful.
  Default verification checks the historical claim; `--current` is the
  stricter release-candidate comparison.
- Codex and Claude raw runs are write-once. Their history indexes are
  append-only. A miss, abort, or stale run remains evidence and is not deleted
  when a later run succeeds.
- Reviewer packets accepted by a result are retained by content digest. The
  top-level working packet may be regenerated; the digest-named packet it
  references is immutable.
- Authenticated host execution, account use, and paid model calls require
  fresh owner authorization. Offline verification does not.

## Lane map

| Lane | Maintained inputs | Implementation authority | Generated or retained evidence | Read-only verification |
| --- | --- | --- | --- | --- |
| Deterministic corpus | [`corpus.json`](corpus.json) and [`fixtures/`](fixtures/) | [`deterministic/`](deterministic/) with thin entry point [`run.py`](run.py) | [`results.json`](results.json) | `uv run python evaluation/run.py --verify-results evaluation/results.json` |
| Installed Codex boundary | [`agent-scenarios.json`](agent-scenarios.json), [`agent-prompt.md`](agent-prompt.md), and [`agent-response-schema.json`](agent-response-schema.json) | [`codex/`](codex/) with thin entry point [`../scripts/agent_eval.py`](../scripts/agent_eval.py) | [`agent-results.json`](agent-results.json), [`agent-history.json`](agent-history.json), and Codex records in [`agent-runs/`](agent-runs/) | `uv run python scripts/agent_eval.py --verify-results evaluation/agent-results.json` |
| Claude Code boundary | [`claude-scenarios.json`](claude-scenarios.json) and [`claude-response-schema.json`](claude-response-schema.json) | [`claude/`](claude/) with thin entry point [`../scripts/claude_eval.py`](../scripts/claude_eval.py) | [`claude-results.json`](claude-results.json), [`claude-history.json`](claude-history.json), and Claude records in [`agent-runs/`](agent-runs/) | `uv run python scripts/claude_eval.py --verify-history` |
| Blinded reviewer | [`reviewer-prompt.md`](reviewer-prompt.md) and [`reviewer-response-schema.json`](reviewer-response-schema.json) | [`reviewer/`](reviewer/) with thin entry point [`review.py`](review.py) | [`reviewer-packet.json`](reviewer-packet.json), [`reviewer-results.json`](reviewer-results.json), and [`reviewer-reviewed-packets/`](reviewer-reviewed-packets/) | `uv run python evaluation/review.py --verify-results evaluation/reviewer-results.json` |
| Shared harness | No scenario input | [`harness/`](harness/) owns bounded JSON I/O, framed hashing, atomic replacement, and evaluator-source identity | No independent result | Exercised through every lane verifier |

The deterministic lane uses no model provider. Its source adapter may perform
a confined public Git fetch when `--fetch` is explicit. Codex live process and
temporary-plugin behavior belongs in `codex/host.py`; Claude live process,
profile sanitization, and scratch ownership belongs in `claude/host.py`.
Their `results.py` modules are the offline authorities and do not import the
live host. The reviewer follows the same boundary: `reviewer/host.py` owns the
authenticated Codex invocation, `reviewer/results.py` owns comparison and
offline verification, and `reviewer/cli.py` imports the host only for
`--run-reviewer`. `reviewer/packet.py` is the lane's sole dependency on
another evaluator package, through the deterministic lane's public result
reader and verifier.

## Scenarios, fixtures, and schemas

The three scenario sources serve different purposes:

- `corpus.json` names pinned repositories, controlled fixtures, labels,
  expected findings, and release thresholds. Source IDs are unique safe path
  components because they also name evaluator cache or checkout state.
  `fixtures/` contains only the repository content and Graphify inputs for its
  local cases.
- `agent-scenarios.json` declares the installed-Codex cases. `codex/fixtures.py`
  creates their temporary repositories; `codex/scenarios.py` validates the
  manifest and judges the bounded traces.
- `claude-scenarios.json` declares the three Claude SessionStart/skill cases.
  `claude/fixtures.py` creates their temporary repositories and
  `claude/scenarios.py` judges the response and event evidence.

Codex and Claude fixture snapshots compare ordinary file contents plus
directory and non-regular entry metadata. They never open special entries.
Dotenv entry names are matched case-insensitively and contribute only their
path key and bounded `lstat` metadata (type, mode, size, modification time,
device, and inode). They are never opened or descended, so mutation detection
does not weaken the evaluator's secret-file boundary.

Tree identities are a different contract: case-insensitive dotenv and
bytecode-cache names are excluded without a read, and real directories
contribute no host-specific metadata. Every included symlink or non-regular
entry is rejected before a content read; only included regular-file paths and
bytes enter those digests.

Files ending in `-response-schema.json` constrain a model host's structured
response. They are not schemas for the retained result files. Persisted result,
history, and packet schema versions are owned by the corresponding lane's
`contract.py`/`results.py` code. A persisted-schema change updates its
producer, verifier, tests, recorded identity, and compatibility policy
together; it is never performed by editing one retained JSON document.
Reviewer packet/result versions live in `reviewer/contract.py`, with packet
validation in `reviewer/packet.py` and result validation in
`reviewer/results.py`.

## Retained baselines and archives

“Retained” identifies the selected repository evidence, not a blanket release
approval:

| Selected file | Current meaning |
| --- | --- |
| `results.json` | Accepted by the default genuineness verifier. It honestly retains a failing release threshold, so it is not a passing release baseline. |
| `agent-results.json` | Accepted historical installed-Codex evidence. Its default verifier passes; release currency is a separate `--current` question. |
| `claude-results.json` | The honest 0/3 controlled batch. It is deliberately retained but is not accepted as a successful Claude result; `claude-history.json` is the passing integrity record for that attempt. |
| `reviewer-results.json` | Accepted historical blinded-reviewer evidence. Default verification passes; current packet/input identity remains a release-only question. |

The archive surfaces preserve the evidence behind those summaries:

- `agent-runs/*.json` contains immutable raw Codex and Claude results. A live
  runner creates a unique filename and refuses to overwrite it.
- `agent-history.json` and `claude-history.json` bind attempt metadata to raw
  result paths and digests. Their producers append attempts; maintainers do
  not rewrite or prune misses.
- `reviewer-reviewed-packets/<sha256>.json` preserves the exact blinded input
  read by an accepted reviewer result. Content-addressed names permit safe
  judgment reuse only when the question and blinded findings are identical.
- `reviewer-packet.json` is the generated working packet. Rebuild it with
  `--build-packet`; do not substitute it for the digest-named archive.

The selected result files, histories, raw runs, working reviewer packet, and
digest-named reviewer packets are all producer-owned files: do not edit them
manually. When evidence is stale, fix the maintained source if necessary and
run the appropriate producer under its authorization boundary. Retain the old
raw/history evidence.

## Mutation and packaging boundaries

The four commands in the “Read-only verification” column are ordinary offline
checks. Adding `--current` still verifies rather than generating evidence, but
it is intended for an exact release candidate and may honestly report stale
inputs or failed thresholds.

Generation is separate:

- `evaluation/run.py` writes deterministic `results.json`; `--fetch` also
  retrieves the three pinned public repositories into temporary space.
- `scripts/agent_eval.py --run` invokes authenticated Codex, temporarily
  changes evaluator-owned local plugin state, writes a unique raw result,
  appends history, and promotes the completed result mirror.
- `scripts/claude_eval.py --run` invokes the already authenticated Claude Code
  profile, writes a unique raw result, appends history, and promotes the
  completed result mirror.
- `evaluation/review.py --build-packet` writes the working packet without a
  model call. `--run-reviewer` invokes authenticated Codex and writes reviewer
  evidence plus its digest-named packet.

The source distribution includes active evaluator code, maintained inputs,
fixtures, and retained evidence needed to reproduce and verify the published
claims. These archives are evidentiary inputs, not irrelevant construction
history. The application wheel contains none of `evaluation/`. Repository-only
construction transcripts under `docs/history/` are preserved in Git but
excluded from source distributions.
