# Glossabet — Current Roadmap

Last updated: 2026-08-22.

Glossabet 0.1.0 is an unreleased source alpha. The implementation and local
release machinery exist, but Kyle is still testing the product as its owner.
Outside testing, contribution intake, release-candidate work, and publication
remain paused until he explicitly advances those gates.

This file contains only current and future work. The complete construction
record is preserved under [`docs/history/`](docs/history/README.md).

## Product boundary

Glossabet gathers deterministic repository evidence, an agent proposes names,
and a human decides what becomes canonical. The skill is instructed not to
save canonical terms without explicit human approval; the `save` command can
validate the document but cannot prove that approval occurred.

Every future change must preserve these constraints:

- Repository content is hostile static data: never import or execute it.
- Production operation is local and makes no network requests.
- Reads and writes stay bounded, path-confined, symlink-aware, and explicit.
- Every cap or omission remains visible; incomplete evidence never reads as
  complete.
- Generated Glossabet context does not feed back into lexical evidence.
- Persisted schemas, deterministic ordering, and compatibility behavior change
  only through an explicit migration.
- Runtime dependencies remain zero unless a concrete correctness or security
  need justifies a reviewed exception.
- External account use, paid/live evaluation, publication, tags, releases, and
  repository-setting changes require separate explicit authorization.

## 1. Complete the owner walkthrough

**Outcome:** Kyle has exercised the public workflow as a first-time user and
has judged its explanations, proposals, persisted state, drift reporting,
resumption behavior, and cleanup instructions from observed output.

**Prerequisite:** none. This is the next product task. During the walkthrough,
present exactly one action at a time and diagnose any failure before changing
code.

**Current status:** not complete. The owner self-testing pause remains active.
The walkthrough covers the README, the reproducible payment-service example,
a real no-glossary naming session with rejection and revision, artifact review,
maintained-glossary commands, a fresh-session reuse check, and disposable tests
of Claude installation, `sync-context`, cache cleanup, and uninstall guidance.
It does not authorize live evaluator batches, outside testing, or publication.

## 2. Finish the two optional live-host evidence lanes

These lanes improve host-specific evidence but do not broaden the product's
local security claims.

### Claude Code session-start evidence

**Outcome:** the existing evaluator records three controlled normal-profile
scenarios: canonical vocabulary present, vocabulary absent, and root-skill
invocation with model tools disabled.

**Prerequisite:** fresh explicit authorization to use Kyle's existing Claude
Max subscription for exactly three Claude Code calls with no retry, at no more
than 200,000 input and 6,000 output tokens total and a command-line cap of
$0.25 per call, plus creation and deletion of the evaluator's one named
temporary directory. Normal authentication is reused; no login state is read,
copied, or changed.

**Current status:** pending authorization. The offline evaluator and corrected
Draft 7-compatible response schema pass their tests. The retained first batch
stopped before SessionStart or model use because its earlier schema declared a
newer JSON Schema draft; that 0/3 miss remains in the evidence ledger. A manual
owner smoke test is useful partial evidence but does not satisfy the controlled
acceptance.

### Post-approval skill behavior

**Outcome:** recorded live scenarios show that report refresh writes only the
derived root `GLOSSABET.md` without promoting proposed terms, and that a
maintainer-owned `GLOSSARY.md` is read only after the skill first states its
independent naming baseline.

**Prerequisite:** the evaluator changes must be implemented and tested offline;
then Kyle must explicitly authorize the stated number of authenticated Codex
turns and their token/cost ceiling.

**Current status:** not started. Existing installed-agent evidence covers the
Step 0 boundary, not these post-approval behaviors.

## 3. Trusted alpha

**Outcome:** at least two consenting maintainers have used the exact installed
build, and the measured set totals at least five varied repositories. The
record includes opt-in scope, repository traits, failures, false alarms,
usefulness feedback, and exact build identity without copying private
repository content here.

**Prerequisite:** Kyle explicitly ends the owner self-testing pause and the
owner walkthrough is complete.

**Current status:** blocked by the intentional owner pause; no invitations are
to be sent yet.

## 4. Exact-artifact release candidate

**Outcome:** one immutable source state and its wheel, source distribution, and
plugin are tied to the same hashes and pass deterministic evaluation, current
installed-agent and reviewer gates, the full supported-platform CI matrix,
distribution checks, and clean install/update/remove smoke tests. The report
separates proven behavior, measured alpha evidence, and remaining limitations.

**Prerequisite:** trusted-alpha evidence is complete.

**Current status:** not started. Ordinary development verifies recorded
evidence for integrity; the `--current` evidence gates and plugin rebuild are
release-candidate work.

## 5. External publication

**Outcome:** only after a successful release candidate, separately authorized
actions may enable GitHub private vulnerability reporting or dependency
security updates, register/upload the package, create a Git tag or GitHub
Release, or submit a public plugin listing.

**Prerequisite:** the exact-artifact release candidate passes and Kyle
explicitly authorizes each account or public-state change.

**Current status:** not authorized and not started. Local verification never
publishes merely because it passes.
