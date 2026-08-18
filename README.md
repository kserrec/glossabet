# Glossabet

Make a codebase's vocabulary explicit, canonical, inspectable, and
maintainable.

Glossabet helps a team establish shared names for the parts of a repository —
subsystems, entities, boundaries, protocols, surfaces — and keep that
vocabulary healthy as the code evolves. Deterministic machinery gathers
lexical and structural evidence; an agent skill (`/glossabet`) brainstorms
names grounded in that evidence; **the human decides what becomes canonical**.
Stated honestly, that last rule is an instruction to the agent, not a
mechanical guarantee: the `/glossabet` skill is written to persist only terms
the human has confirmed, and to write a project's `AGENTS.md`/`CLAUDE.md`
block (`sync-context`) only on explicit request, but the `glossabet save`
command validates structure and trusts its caller — it cannot tell whether
the agent piping to it really obtained your approval. Review what lands in
`glossabet-out/glossary.json` the way you would review any agent-written
change.

**Glossabet is the project and product name.** It keeps three different
things separate:

- `GLOSSARY.md` — the vocabulary humans have agreed to use.
- `GLOSSABET.md` — Glossabet's human-readable analysis of the health and
  alignment of that vocabulary: gaps, overloads, suspected synonyms, drift,
  glossary/code disagreement, proposals, open questions, coverage limits.
- `glossabet-out/glossary.json` — structured vocabulary state used for
  resumption, drift detection, validation, scopes, aliases, and bindings.

The glossary tells the team what the words mean; the Glossabet report tells
the team whether those words still match the codebase. `GLOSSABET.md` is not
a better glossary and never replaces `GLOSSARY.md` — its value is precisely
that it lets `GLOSSARY.md` remain a glossary. The `/glossabet` skill writes
the report at the scan root when it finalizes, or on request when a session
ends with open findings; it clearly marks proposed and unresolved items as
non-canonical, is refreshed as one report rather than appended to, and is
derived output — safe to regenerate, excluded from lexical evidence so it can
never become evidence for its own next run, and excluded from the freshness
stamp so regenerating it never makes evidence look stale.

Optionally, Glossabet consumes [Graphify](https://github.com/Graphify-Labs/graphify)
output as richer structural evidence and can reconcile the settled glossary
against the structural graph — surfacing unnamed architecture, orphaned
concepts, vocabulary drift, and boundary mismatches. Graphify is never
required.

The adapter supports Graphify 0.9.42's exported `links`, `source_file`,
`file_type`, `community_name`, and `built_at_commit` fields as well as the
older accepted `edges`/`source` shapes. Evidence distinguishes a graph file
being present from usable community structure being loaded. When Graphify's
commit stamp is available, Glossabet reports the structure as current, stale,
or unverified against the repository's HEAD and worktree; structural
validation is explicitly skipped when no usable groups were loaded. “Current”
means the graph's recorded commit matches a clean checkout; because the graph
file is repository-controlled input, this is a staleness signal rather than
content authentication.

## Why repository vocabulary matters

Glossabet is built on an empirically supported problem: names act as part of
a program's documentation, developers do not naturally converge on the same
names, and inconsistencies between names and meaning make code harder to
understand. Relevant studies include:

- Schankin et al., [*Descriptive Compound Identifier Names Improve Source Code
  Comprehension*](https://doi.org/10.1145/3196321.3196332) ([open-access
  paper](https://brains-on-code.github.io/descriptive-compound-identifier-names.pdf)),
  studied 88 Java developers. With descriptive compound identifiers,
  participants found semantic defects about 14% faster than with shorter,
  less descriptive names; the effect did not appear for syntax errors that did
  not require deeper comprehension.
- Fakhoury et al., [*Measuring the Impact of Lexical and Structural
  Inconsistencies on Developers' Cognitive Load During Bug
  Localization*](https://doi.org/10.1007/s10664-019-09751-4)
  ([institutional record](https://rex.libraries.wsu.edu/esploro/outputs/journalArticle/Measuring-the-impact-of-lexical-and/99900601056501842)),
  found that lexical inconsistencies significantly increased participants'
  cognitive load throughout a code snippet; lexical and structural
  inconsistencies were also associated with worse bug-localization time and
  success rate.
- Arnaoudova, Di Penta, and Antoniol, [*Linguistic Antipatterns: What They Are
  and How Developers Perceive
  Them*](https://doi.org/10.1007/s10664-014-9350-8) ([author
  manuscript](https://www.veneraarnaoudova.ca/wp-content/uploads/2014/10/2014-EMSE-Arnaodova-et-al-Perception-LAs.pdf)),
  catalogued 17 recurring inconsistencies among naming, documentation, and
  implementation. In two empirical studies, a majority of both external and
  project developers regarded the studied antipatterns as poor practice.
- Kim and Kim, [*Automatic Identifier Inconsistency Detection Using Code
  Dictionary*](https://doi.org/10.1007/s10664-015-9369-5)
  ([institutional record and author
  preprint](https://orbilu.uni.lu/handle/10993/20131)), showed why a project's
  own domain vocabulary matters to automated analysis: accepting domain words
  and programming idioms reduced false alarms. Their seven-project evaluation
  reported 85.4% precision and 83.59% recall.
- Feitelson et al., [*How Developers Choose
  Names*](https://doi.org/10.1109/TSE.2020.2976920) ([open-access
  preprint](https://arxiv.org/abs/2103.07487)), asked 334 participants to name
  program elements. Across the study's scenarios, the median probability that
  two developers independently chose the same name was only 6.9%; names
  produced with an explicit naming model were judged better than unaided names
  by a two-to-one ratio.

This research supports the need for deliberate, repository-specific vocabulary
work. It does **not** by itself prove that Glossabet saves time or produces
better naming decisions. Glossabet's own small controlled evaluation is
reported separately below and does not turn those studies into a
product-efficacy claim.

## Evaluation status

Phase 15 pins three permissively licensed public repositories—
[Requests](https://github.com/psf/requests/tree/8068356288978c4f54661ae6f95afe0e0831885e),
[hey](https://github.com/rakyll/hey/tree/5626f79b8698df6daf9b25799c9805c6acc96740),
and [p-limit](https://github.com/sindresorhus/p-limit/tree/df476048d023ff868cd45b35ee47f5fb0ca2b25a)—plus
four original fixtures for terminology, multilingual scoped vocabulary, and
Graphify structure/truncation. The five-run corpus now contains 99 included
source files and 52 production code files. It emitted 20 labelled terminology,
drift, and structural findings with 100% precision, 100% recall where the
expected set was complete, and zero false alarms. All 15 lexical contracts and
all 26 structural contracts passed. Phase 25 also adds 16/16 passing register
labels across the seven cases and this repository, covering dominant style and
whether structurally styled names are predominantly multi-word. Phase 26 adds
an 11/11 passing self-nomination gate: four repository concepts must surface
with their expected nomination kinds, six recorded generic tokens must not,
and every retained term must be typed. The primary
reviewer marked 20/20 findings
useful; a separate Codex session, blinded to those labels and isolated from the
repository, marked 17/20 useful and recorded three disagreements.

Those percentages are a regression-gate result, **not evidence of broad
efficacy**: the corpus and positive-finding count are small, the evaluation
glossaries are curator-authored rather than endorsed by upstream maintainers,
real-repository heuristic recall is not exhaustive, and the second reviewer is
a Codex session rather than an outside maintainer study. Structural recall is
labelled only in controlled Graphify fixtures. The pre-calibration engine
produced 53 false alarms among 64 findings on the earlier labels; the corpus
drove narrower file-separation, identifier-pattern, and similarity gates for
synonym nominations.

The complete methodology, licenses, baseline, thresholds, limitations, and
reproduction command are in [`EVALUATION.md`](EVALUATION.md); raw results are
in [`evaluation/results.json`](evaluation/results.json).

**Status: 0.1.0 source alpha under an owner self-testing pause; not yet
published to PyPI or a plugin directory and not yet a trusted-alpha release.**
Phases 0–22, 24–32, and 34–36 are implemented (36.8 and the Claude Code
live-hook evidence of 33.2 remain); `PLAN.md` records their exact
acceptance and commit state. The installed-agent harness
separately probes fresh-session hook delivery, the installed skill, and the
non-login, profile-disabled missing-CLI boundary. Its offline gate checks the
current plugin artifact and all recorded safety outcomes deterministically,
while its append-only attempt history reports procedural agent misses instead of
selecting a green retry. See [`EVALUATION.md`](EVALUATION.md) for every observed
attempt and its provenance limits. Owner-run testing and the trusted-alpha
evidence gate stay before any outside maintainer invitation.
Package metadata and the embedded plugin wheel are bound to the renamed GitHub
repository; the checked-in wheel and plugin were rebuilt from the current
source and canonical skill on 2026-08-18, and the installed-agent evidence
recorded that day (Codex CLI 0.147.0 on Linux, 14/14 scenarios) passes the
currency check against them.
The trusted-alpha evidence gate and Phase 23 remain later work; do not describe
the current stopping point as release-ready. See
[`NAME-CLEARANCE.md`](NAME-CLEARANCE.md) for the
point-in-time name checks, [`DISTRIBUTION.md`](DISTRIBUTION.md) for exact
installation ownership, [`PLAN.md`](PLAN.md) for the closure sequence, and
[`RELEASING.md`](RELEASING.md) for external actions.

The preferred future Codex artifact is the version-coupled plugin prototype at
`plugins/glossabet/`. It carries the canonical skill and a matching wheel that
runs from the plugin cache without adding a command to `PATH`. Its declared
Codex `SessionStart` hook runs the bundled `brief .` boundary at startup,
resume, clear, and compaction. Once the user trusts that installed hook, its
bounded stdout becomes developer context for the session; an absent glossary
contributes nothing. No public marketplace entry exists yet. For local use
from a source checkout, the standalone fallback installs the CLI and then
makes a separate skill copy:

```bash
uv tool install . --reinstall
glossabet install
```

Codex currently loads personal skills from `~/.agents/skills`; Claude Code
users run `glossabet install --agent claude` instead, which targets
`~/.claude/skills/glossabet/`. For Claude Code that one command also makes the
skill folder a
[skills-directory plugin](https://code.claude.com/docs/en/plugins-reference#skills-directory-plugins):
beside `SKILL.md` it writes `.claude-plugin/plugin.json` and a
`hooks/hooks.json` whose `SessionStart` hook runs `glossabet brief .` at
startup, resume, clear, and compaction — the same ambient vocabulary
delivery the Codex plugin provides. Claude Code loads the folder as
`glossabet@skills-dir` from the next session; with no glossary the hook adds
nothing. Nothing outside that folder is written (`~/.claude/settings.json` is
never touched); `--skill-only` installs the skill without the hook, and
deleting the folder (or `claude plugin disable glossabet@skills-dir`) removes
it. The hook names the exact `glossabet` executable that ran `install`, so a
moved or removed CLI produces a visible per-session notice rather than
silence — rerun `glossabet install --agent claude` after reinstalling. The
folder is validated offline against `claude plugin validate`; a live
installed Claude Code session has not yet been probed the way the Codex
plugin has (PLAN Phase 33.2), so that route is still labelled unverified.
The wheel carries the exact canonical [`skill/SKILL.md`](skill/SKILL.md), and
installation refuses to overwrite a different skill, manifest, or hook unless
`--force` is explicit. The locations follow the
[official OpenAI Codex documentation](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)
and [official Claude Code documentation](https://code.claude.com/docs/en/skills#where-skills-live).

Run the isolated end-to-end sample:

```bash
uv run python scripts/run_walkthrough.py
```

The full explanation and expected result are in
[`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md). The CLI surface is:

```
glossabet install           install the canonical agent skill (Codex default)
glossabet install --agent claude  skill + session-start hook as a Claude Code plugin
glossabet scan <repo>       deterministic, git-stamped evidence (cached, incremental)
glossabet analyze <repo>    scan + terminology report (register, overlaps, overloads)
glossabet inspect <repo>    fresh, lean JSON context for the agent skill
glossabet inspect <repo> --full  detailed diagnostic projection
glossabet brief <repo>      bounded read-only canonical vocabulary digest
glossabet sync-context <repo>  explicitly sync a managed block into AGENTS.md
glossabet sync-context <repo> --agent claude  target CLAUDE.md instead
glossabet save <repo>       validate/save glossary JSON from standard input
glossabet show <repo>       display the current glossary
glossabet drift <repo>      live vocabulary vs the canonical glossary
glossabet validate <repo>   reconcile glossary vs evidence and the Graphify graph
glossabet cache-clear       remove Glossabet's user cache directory (never the repo)
```

The installed skill requires `glossabet inspect .` from the exact repository
or subproject root. That command safely validates repository-controlled JSON,
builds current evidence, refreshes `evidence.json`, and emits a separate
versioned, compact context. The routine schema-v3 projection uses per-module
vocabulary rollups and retains file locations only for naming candidates and
register exemplars; on Glossabet itself its checked soft target is 80 KB. The
1 MB ceiling remains a hard failure backstop for unusual repositories, not a
routine budget. `inspect --full` emits the former detailed collection shape
for diagnostics. Both modes report scanner omissions under `coverage.corpus`
and every agent-projection omission under `coverage.context`. The context
carries two distinct glossary channels that are never merged: `glossary` is
Glossabet's own structured state (`glossabet-out/glossary.json`), and
`repository_glossary` describes the repository's hand-maintained root
`GLOSSARY.md` — presence, safe-read status (`readable` with a named
`reason` when a symlink escapes the root or points at an in-repo sensitive
file, the entry is not a regular file, the file exceeds the 2 MB bound, or
something is there but its exact name could not be confirmed),
whether the entry is a symlink (readable through, never written through), size, and the SHA-256 of the exact
bytes, plus any nested `GLOSSARY.md` files the walk excluded
(`nested_ignored`). Metadata only, never content: `GLOSSARY.md` stays out of
lexical evidence at every depth so it can never become evidence for itself,
and the skill forms its own naming model before it reads the maintainers'
document. An unreadable glossary is reported as present-but-unreadable,
never as absent. From those two channels the skill is in exactly one of four
states — no glossary, adoption (Markdown only), resume (structured only), or
managed (both) — and in the adoption and managed states it forms its own
naming model from the glossary-blind context first, only then reads the
maintainers' document, reconciles the two (supported, weakly represented,
drifted, overloaded, missing, alias mismatch, blurred distinction,
unresolved), offers settled-and-supported terms as "documented already —
keep?", promotes nothing to `canonical` without the human, and edits a
pre-existing `GLOSSARY.md` surgically rather than regenerating it. When both
files exist and the Markdown was read completely, the context and
`glossabet validate` also carry one deterministic signal,
`repository_glossary.divergence`: canonical terms whose folded spelling occurs
nowhere in the document, and superseded alias terms that still appear while
their canonical term does not — lexical presence only, capped at 500 terms
and at 4 M normalized characters with the cap reported, absent (never
empty) when the check could not run. The skill never
opens Glossabet JSON artifacts itself and does not fall back to unrestricted
recursive reading when the CLI boundary fails. When the human settles terms,
the skill sends the complete JSON document to `glossabet save .` on standard
input; that command bounds, strictly validates, confines, and atomically
persists `glossary.json` instead of letting the agent write it.

`glossabet brief <repo>` is the read-only ambient vocabulary boundary. It
loads only the confined, strictly validated glossary and the hardened live Git
stamp; it does not scan source files, refresh evidence, or write any repository
file. With no glossary it emits nothing. Otherwise it emits at most 4,096 UTF-8
bytes of deterministic plain text: canonical terms with one-line definitions,
scopes, alias statuses, a semantic glossary SHA-256, `{head, dirty}` Git state,
and explicit coverage when entries or details do not fit. Its first line
names its origin — that it was emitted by `glossabet brief .` and that an
installed Glossabet `SessionStart` hook injects it into agent context
automatically — so months after installing a plugin, anyone reading a
transcript can tell where the text came from. The text can be
piped or pasted into an ordinary agent context, and the Codex plugin supplies
it automatically through its trusted `SessionStart` hook. It is context for
using settled words, never permission to nominate, coin, finalize, save, edit,
or rename vocabulary; those changes still require a human `/glossabet` naming
session.

Hosts without a trusted session-start hook can persist the same canonical
vocabulary with an explicit `glossabet sync-context <repo>` invocation. The
default Codex target is the repository-root `AGENTS.md`; `--agent claude`
selects only root `CLAUDE.md`. The command is never called by `install`,
`scan`, `inspect`, `brief`, `drift`, `validate`, or the agent skill's normal
finalization flow. It creates or updates one marked block only after the human
invokes it. The stable block repeats the semantic glossary SHA-256 rather than
a live Git stamp: a persistent file cannot truthfully preserve live dirtiness,
because writing that file changes the worktree itself.

Hand-written bytes outside the two exact markers are preserved. One intact
older glossary block is updated atomically; a current block is a no-write
operation. A stamped body that was edited is preserved unless `--force` is
explicit, while malformed, duplicated, unmatched, or changed markers/metadata
are always refused because the replacement boundary is ambiguous. Targets
must be regular UTF-8 files no larger than 2 MB; symlinks are never followed.
`drift` and `validate` inspect both supported root files read-only and report a
stale, edited, or uninspectable block in their terminal output and JSON report.
The scanner removes one exactly bounded managed block before lexical analysis,
so canonical vocabulary cannot echo through `AGENTS.md`/`CLAUDE.md` and hide
drift; surrounding human instructions remain ordinary documentation evidence.

Artifacts live in `<repo>/glossabet-out/` (evidence, glossary, drift and
validation reports). The incremental extraction cache is user-owned state,
not repository input: it lives under the platform cache directory
(`$XDG_CACHE_HOME/glossabet` or `~/.cache/glossabet` on Linux,
`~/Library/Caches/glossabet` on macOS, and `%LOCALAPPDATA%\glossabet` on
Windows). `GLOSSABET_CACHE_DIR` can override that base; caching is disabled
if the selected directory resolves inside the scanned repository.

### Artifact ownership, freshness, and cleanup

The top-level `<repo>/glossabet-out/` directory is reserved for
Glossabet-owned files. Do not put unrelated project files there. Its contents
have two different lifecycles:

- `evidence.json`, `drift.json`, and `validation.json` are derived reports.
  They can be removed and rebuilt with `scan`, `drift`, and `validate`
  respectively (the latter two require an existing glossary).
- `glossary.json` is the machine-readable record of human-governed vocabulary,
  including settled and still-proposed terms. It is owned and written by the
  Glossabet workflow, but it is not disposable: preserve it unless that state
  is intentionally being discarded or is recoverable from version control.
  For a shared team glossary, commit both `GLOSSARY.md` and
  `glossabet-out/glossary.json`.
- Root `GLOSSABET.md`, the vocabulary-health report the skill writes next to
  `GLOSSARY.md`, is a derived Glossabet artifact outside that directory: not
  the authoritative machine state (`glossary.json` is) and not the
  authoritative human vocabulary (`GLOSSARY.md` is). It is safe to delete
  and regenerate — deleting it changes no canonical state — and teams may
  commit it so findings are visible in review; its role stays derived.
  A nested `GLOSSABET.md` belongs to the subproject scan that wrote it.

The evidence freshness stamp records the commit and worktree state
with live Git state while excluding only that top-level `glossabet-out/`
directory and the scan root's own `GLOSSABET.md` — both are Glossabet-owned
output, so regenerating them does not make the inputs they were built from
look stale. This makes a clean repository immediately fresh after its first
scan, whether generated output is tracked or untracked. Changes elsewhere
inside the scanned root — including `GLOSSARY.md` (human-governed vocabulary,
deliberately *not* treated as output despite the similar name), a nested
subproject's `GLOSSABET.md`, and `graphify-out/` — remain
visible. Pre-rename `.glossarize/` and `glossarize-out/` paths stay excluded so
old tool artifacts cannot contaminate a new scan. A subproject scan uses that
subproject, not an enclosing Git worktree, as its scope. The freshness check
still treats cache and pre-rename paths like ordinary Git state unless Git
ignores them; only the top-level current `glossabet-out/` and root
`GLOSSABET.md` are filtered from Git status. Git-ignored files follow Git's normal
semantics and therefore cannot make the stamp dirty; a repository without a
readable `HEAD` is reported as unverified. The skill does not reimplement this
check: `inspect` builds its bounded context from live inputs in that same CLI
invocation. This is not an atomic filesystem snapshot; do not scan while an
untrusted process is mutating the checkout.

Glossabet never creates or edits the target repository's `.gitignore`.
Repository owners decide which artifacts to track. Removing the derived
reports is sufficient cleanup when the glossary should be retained; the
user-cache directory is only a performance optimization and can be removed
independently with `glossabet cache-clear`, which deletes only Glossabet's
own cache layout under the platform cache directory (or `GLOSSABET_CACHE_DIR`),
never touches any repository, and reports anything unrecognized that it left
in place.

A synchronized block lives in a project-owned `AGENTS.md` or `CLAUDE.md`, not
under `glossabet-out/`. It is therefore normal repository state: review and
commit it if the team wants the context shared. Package or plugin removal does
not delete or edit it. To stop using this fallback, remove only the text from
the exact Glossabet start marker through the exact end marker, leaving the
surrounding host instructions intact.

The installed agent skill is separate user-owned state. Uninstalling the
Python package removes the CLI but deliberately does not delete that copied
`SKILL.md`; if the skill is no longer wanted, inspect and remove only the
reported `glossabet` skill directory for the selected agent.

### Repository analysis scope

Glossabet analyzes production vocabulary by default. Test and fixture files
remain visible in the file and module inventory, with an explicit `role`, but
their lexical content does not drive vocabulary, naming, synonym, overload,
drift, or lexical reconciliation signals. Generated and vendored paths are not
read lexically and are reported under `skipped`. Graphify remains a separate
structural input with its own provenance and freshness limits.

Retained code tokens are tagged `origin: domain` or `origin: language` from the
current conservative Python builtin table; unlisted languages and tokens
default to domain. Language tokens stay in the full evidence record, but only
domain tokens can consume terminology's top-150 analysis budget or the
term-nomination pool. Every such exclusion is counted in the affected coverage
ledger. If a spelling has any domain occurrence, domain wins, so one language's
builtin cannot hide a same-spelled project concept in another language.
Ambiguous words including `open`, `type`, `run`, and `match` deliberately remain
domain evidence.

Term nominations rank repository breadth, documentation, source-unit naming,
and count-normalized compound productivity from existing identifier patterns.
A token used in many distinct compounds therefore outranks an equally frequent
standalone token without letting raw repetition dominate. Wide terms reuse
terminology's bounded context-dispersion measurement and carry
`nomination_kind: "deserves a canonical name"` or `"deserves disambiguation"`;
each numeric input and every omission remain visible. These are evidence for
the skill's naming review, never canonical decisions.

An optional `glossabet.json` at the scanned root can add ignored paths,
classify project-specific layouts, or mark a conventionally non-production
path as production. You meet it where the classification is on screen: `scan`
and `analyze` end their summary with one line saying whether roles came from
built-in defaults or from `glossabet.json` and that the file adjusts them,
`--help` for `scan`/`analyze`/`inspect` names it, and every evidence and
`inspect` context carries its shape under `configuration.shape` (keys, the
five roles, the literal-prefix rules, one example) so the `/glossabet` skill
can offer to write one when the roles look wrong — only on the user's yes:

```json
{
  "schema_version": 1,
  "ignore_paths": ["scratch", "docs/archive"],
  "path_roles": {
    "production": ["tests/product_contracts"],
    "test": ["qa"],
    "fixture": ["sample_data"],
    "generated": ["src/api/generated"],
    "vendored": ["third_party"]
  }
}
```

Every entry is a literal, `/`-separated path prefix relative to the scanned
root; globs, absolute paths, and `..` are rejected. Ignore rules win, and the
most-specific configured role wins over a broader configured or default role.
Unknown fields and malformed configurations are user errors rather than
silently ignored typos.

Conservative defaults classify `test`/`tests`/`spec`/`specs` directories and
common test filenames as `test`, and fixture/test-data directories as
`fixture`. Common build/generated directories are `generated`; dependency and
vendor directories are `vendored`. Everything else is `production`. The
artifact records the loaded configuration, per-role file totals, every
included file's role, and configured/generated/vendored exclusions, so the
analysis scope is inspectable rather than implicit.

Each scan is also bounded to 10,000 included source files, 32 MB of included
source bytes, 100,000 walked entries, and 10,000 entries in one directory.
`skipped.corpus_budget` records limits, usage, exact source-file/byte skips,
bounded samples, and any inexact unvisited walk remainder. If `complete` is
false, the CLI says the evidence is partial; no exhaustive conclusion should
be drawn from it.

### Precision contracts

- A glossary concept may optionally declare literal repository-relative
  `scope.path_prefixes`. Omission means repository-wide. Drift, lexical
  validation, stable bindings, and fragmentation are restricted to those
  paths; findings carry the applied scope. Aliases inherit their concept's
  scope. A normalized term or alias may have multiple owners only in disjoint
  scopes. Because normalized Graphify groups do not carry repository paths,
  structural validation explicitly reports partial/skipped scope coverage
  instead of guessing.
- Identifier extraction is Unicode-aware and NFKC-casefolded. Camel, Pascal,
  snake, and Clojure kebab forms normalize consistently; acronym runs remain
  intact; digit runs attach to the preceding word (`HTTP2Server` becomes
  `http2`, `server`), while standalone numeric hunks are discarded. Source
  sigils and predicate/bang suffixes are lexical boundaries. This remains a
  lexical approximation and reads comments/string contents like other source
  text; it is not a parser.
- Every retained code token carries a language/domain origin. Curated language
  builtins are tagged rather than deleted, domain use wins for mixed-origin
  spellings, and language-token exclusions from terminology/naming budgets are
  explicit in coverage rather than silently shrinking the input.
- House-register headline style and length percentages use only multi-token
  snake/camel/Pascal spellings whose structure is direct code evidence. Flat
  spellings and one-token case variants must be domain-origin and must appear
  at least as often among identifier-shaped code-file matches as in docs before
  they are admitted. The report accounts for every used and excluded spelling
  by reason and states that the headline denominator is the structurally styled
  subset.
- A compound glossary term occurs in code only when its normalized words are
  contiguous inside one identifier, such as `PaymentRequest` or
  `create_payment_request`. Independent word hits elsewhere do not establish
  the compound. Drift and validation build one requested-term trie and scan
  the bounded identifier index once; an explicit work ledger records any
  identifier positions or overlong compound terms omitted by its budgets. A
  Graphify structural group is the separate, explicitly defined local context
  used for structural matching.
- One NFKC-casefolded canonical term or alias may belong to only one concept
  in overlapping scopes. Ambiguous aliases are rejected before the glossary
  is saved or consumed. Every glossary object rejects unknown fields, and
  concept/alias/binding/scope/string counts have documented semantic ceilings.
  Ownership validation uses an indexed path-prefix lookup rather than comparing
  every same-word concept pair.
- Heuristic thresholds are labelled `signal_strength` (`strong`, `moderate`,
  or `weak`), not “confidence.” Directly proven lexical or binding facts use
  `certainty: observed`. Probabilistic confidence labels remain reserved for
  future measured calibration.
- Every bounded vocabulary, candidate, terminology, structure, drift, and
  validation collection carries the same `coverage` ledger:
  `total_items`, `included_items`, `dropped_items`, `total_items_exact`,
  `complete`, and `reasons`. `total_items` is the known evaluated count;
  `total_items_exact: false` marks it as a lower bound when upstream work was
  omitted. `total_findings` includes known findings omitted from displayed
  `items`; `total_findings_complete` says whether that total is exhaustive.
  Reports then say “evaluated findings” and identify the partial coverage
  instead of presenting a lower bound as exhaustive.
- Graphify groups keep a six-label `members_sample` only for display, while
  reconciliation matches against the complete normalized `member_tokens` set
  from every accepted non-glossary member. Structural concept lookup uses an
  inverted token index; boundary-pair totals are counted arithmetically while
  only the bounded detail prefix is generated.
- Repository-controlled text is terminal data, never terminal instructions.
  The CLI renders control and bidirectional-format characters as visible
  escape spellings; glossary identity fields reject them outright.

## Development and release verification

Prerequisites: Git, Python ≥ 3.10, and [uv](https://docs.astral.sh/uv/). The
runtime is standard-library only; `pytest` is the sole development dependency,
and Hatchling is isolated to builds. One reusable quality workflow tests
CPython 3.10–3.14 on Linux, macOS, and Windows before packaging; both ordinary
CI and the manual publication workflow must pass it.

From a fresh clone, create the locked development environment and run the
tests:

```bash
git clone https://github.com/kserrec/glossabet.git
cd glossabet
uv sync --locked
uv run pytest -q
```

Install the CLI onto your PATH and check it:

```
uv tool install . --reinstall
glossabet --version
```

Build and verify the distributions without publishing them:

```bash
uv run python scripts/check_workflows.py
uv run python evaluation/run.py --verify-results evaluation/results.json
uv run python scripts/agent_eval.py --verify-results evaluation/agent-results.json
uv run python evaluation/review.py --verify-results evaluation/reviewer-results.json
uv build --no-sources
uv run python scripts/build_plugin.py dist
uv run python scripts/check_distribution.py dist --tag v0.1.0
uv run python scripts/wheel_smoke.py dist
uv run python scripts/plugin_smoke.py dist
```

The three `--verify-results` gates check that the committed evaluation
evidence is genuine — untampered and internally consistent. Between releases
the evidence may honestly lag the source tree; the release gate reruns each
verifier with `--current` to additionally require that the evidence describes
the exact code being shipped (see `RELEASING.md`).

- `CONTRIBUTING.md` — how contributions are accepted (Apache-2.0 inbound,
  Developer Certificate of Origin sign-off).
- `ARCHITECTURE.md` — how the engine is built and how to work on it (start here
  to take ownership).
- `SECURITY.md` — the threat model and the enforced trust boundaries.
- `PRIVACY.md` — local versus agent-mediated data flow and network behavior.
- `EVALUATION.md` — corpus, labels, measurements, thresholds, and limitations.
- `docs/WALKTHROUGH.md` — reproducible first-use path and real-repository flow.
- `RELEASING.md` — local gate plus all still-manual public account actions.
- `DISTRIBUTION.md` — plugin versus wheel ownership, upgrades, and removal.
- `NAME-CLEARANCE.md` — the chosen identity, exact checks, and their limits.
- `CHANGELOG.md` — release-facing change history.
- `PLAN.md` — the authoritative roadmap and the binding design principles.
- `skill/SKILL.md` — the canonical `/glossabet` agent skill.

## Provenance and affiliation

Glossabet is an independent open-source project by Kyle Serrecchia, released
under the Apache License 2.0 (`LICENSE`). It is not affiliated with, endorsed
by, or sponsored by OpenAI, Anthropic, GitHub, or Graphify Labs; "Codex",
"Claude Code", and "Graphify" are named only to identify the third-party
hosts and tools it integrates with, and each remains its owner's mark.

Glossabet is developed with AI coding assistants working under human
direction and review — Claude (via Claude Code) writes much of the code and
documentation, and ChatGPT contributed to the initial 2026-08-14 plan; commit
history records that co-authorship. Contributions are accepted under the
terms in `CONTRIBUTING.md`.
