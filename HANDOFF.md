# Session handoff — 2026-08-15

This handoff becomes stale when Kyle ends the owner self-testing pause or new
project work begins. `PLAN.md` remains the authoritative durable roadmap.

**Project:** Glossabet is a Python CLI, canonical agent skill, and local Codex
plugin prototype for making a codebase's vocabulary explicit, canonical,
inspectable, and maintainable.

**Completed this session**

- Completed Phase 22 without changing the production engine, CLI, or skill.
- Added two original Graphify fixtures covering all structural finding
  families, the seventh member beyond the display sample, exact provenance,
  and the 51st group/truncation boundary. Extended the evaluator with structural
  precision, recall, contracts, review packets, and stronger offline replay
  checks.
- Added a blinded second-reviewer lane. A separate ephemeral Codex session in
  an isolated read-only temporary directory saw only the 20-finding packet,
  response schema, and review prompt.
- Added a real installed-skill harness covering 11 plugin and standalone
  scenarios with bounded JSONL traces, independent context checks, sensitive
  canary detection, write snapshots, and exact plugin cleanup.
- Added offline agent/reviewer verifiers to the reusable quality and release
  workflows, source-distribution contents, and regression suite.
- With Kyle's explicit authorization, renamed the public GitHub repository to
  `kserrec/glossabet`, changed `origin` to
  `git@github.com:kserrec/glossabet.git`, moved the local checkout to
  `/home/serrecchia/Projects/glossabet`, and verified the old GitHub path's
  redirect. No commit was pushed as part of the rename.
- Refreshed the ignored repository-local `.venv` from `uv.lock` because its
  generated launchers contained the old absolute checkout path. The stale
  editable `glossarize` installation was removed, `glossabet` 0.1.0 was
  installed, and `.venv/bin/pytest` now points to the renamed checkout.
- Audited the ownership documentation against the implementation and current
  official Codex skill/plugin documentation. Updated `README.md`,
  `ARCHITECTURE.md`, and `CLAUDE.md` with the Glossabet-versus-glossary
  distinction, fresh-clone setup, and active owner self-testing pause.
- Switched all package project URLs and the distribution assertion to
  `kserrec/glossabet`, rebuilt the embedded wheel, and regenerated the
  installed-agent evidence against the exact new plugin hash. Only wheel
  `METADATA` and `RECORD` changed; executable entries remained byte-identical.
  A final README status sync changed metadata only, so the wheel and evidence
  were rebuilt once more against the final source state.

**Verified state**

- `uv run pytest -q`: 303 passed.
- Deterministic evaluation: 7 cases, 99 source files, 52 production-code files,
  overall/structural precision 1.0, recall 1.0 where complete, 15/15 lexical
  contracts, 26/26 structural contracts, zero false alarms, and all release
  thresholds passing.
- Second reviewer: 20/20 findings reviewed, 17 useful (0.85), 17 agreements
  (0.85), and three preserved disagreements: p-limit `Pause Queue` fading,
  the authentication/authorization Identity Boundary, and tenant fragmentation.
  This reviewer was Codex, not an outside maintainer.
- Installed-agent evaluation: 11/11 scenarios passed on Codex CLI 0.147.0,
  CPython 3.12.3, and Linux. Codex read the exact temporary plugin skill,
  version-checked its bundled 0.1.0 engine, never exposed the sensitive canary,
  made no unexpected repository write, and stopped before `inspect` when the
  standalone CLI was missing. The documented `inspect` evidence refresh was
  explicitly permitted.
- Agent preflight reliability is not established: six of seven observed full
  plugin batches ran the required single version check. The original Phase 22
  work accounted for four of five; both post-Phase 22 metadata-only refreshes
  passed, including the current final wheel's first full batch. Every failed or
  successful attempt completed its exact plugin cleanup.
- `uv run python evaluation/run.py --verify-results evaluation/results.json`,
  `uv run python scripts/agent_eval.py --verify-results
  evaluation/agent-results.json`, and `uv run python evaluation/review.py
  --verify-results evaluation/reviewer-results.json` all pass.
- No temporary Glossabet plugin or marketplace remains installed. The only
  configured marketplace is the pre-existing `openai-curated` entry.

**External and local identity state**

- GitHub now hosts the still-public repository at
  `https://github.com/kserrec/glossabet`; the old GitHub path was verified to
  resolve to it. The configured Git remote is
  `git@github.com:kserrec/glossabet.git`.
- The checkout now lives at `/home/serrecchia/Projects/glossabet`; the old
  `/home/serrecchia/Projects/glossarize` directory no longer exists.
- Package project URLs, the embedded plugin wheel, and installed-agent evidence
  now use and bind to `kserrec/glossabet`. The refreshed evidence records plugin
  tree SHA-256
  `a2bc528e23478e4fa708a40dbfe97f081f482901323d60c45351a06966df5cc5`.
- No package or plugin was published; no Codex plugin, tag, release, domain,
  security setting, visibility setting, invitation, or outreach was created or
  changed. Kyle's separate legacy `~/.local/bin/glossarize` 0.0.1 installation
  remains untouched.

**Current stopping point**

- The owner self-testing pause is active. Kyle will run the current build and
  perform additional checks himself. Do not invite anyone, collect outside
  alpha evidence, begin Phase 23, or perform publication setup until Kyle
  explicitly ends this pause.
- After that explicit instruction, the trusted-alpha gate requires at least two
  consenting maintainers to try the exact installed build on enough additional
  varied repositories to bring the measured total to at least five. Record
  opt-in scope, repository traits, failures, false alarms, usefulness, and
  exact build identity without copying private repository content here.
