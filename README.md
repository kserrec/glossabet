# Glossabet

Glossabet helps a team choose shared names for the important parts of a
codebase and keep those names consistent as the code changes.

It has two parts:

- The `glossabet` command scans a repository and records facts about the words
  and structure already present in the code.
- The Glossabet agent skill reads those facts and relevant source files, then
  proposes names for the human to discuss and decide.

The program does not decide the vocabulary. **The human decides which names
become canonical**, meaning officially accepted for that project. The skill is
instructed to save only names the human has approved, but the
`glossabet save` command cannot verify that approval itself. Review saved
vocabulary exactly as you would review any other agent-written change.

## Current status

Glossabet 0.1.0 is an unreleased source alpha under owner testing. It is not on
PyPI or in a public plugin marketplace, outside maintainers are not being
invited yet, and it should not be described as release-ready. You can inspect
and run the source, but there is no supported public installation yet.

[`PLAN.md`](PLAN.md) records the exact remaining work.
[`EVALUATION.md`](EVALUATION.md) explains what has and has not been tested, and
[`DISTRIBUTION.md`](DISTRIBUTION.md) describes the planned package and plugin
delivery methods.

## Install from source

You need Git, Python 3.10 or newer, and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/). From a fresh
clone of this repository, run:

```bash
uv tool install . --reinstall
glossabet install
```

The first command installs the `glossabet` command in an isolated Python
environment. The second copies the matching agent skill to
`~/.agents/skills/glossabet/`, where Codex looks for personal skills. Neither
command changes a repository you want Glossabet to analyze. The installer
refuses to replace a different existing skill unless you explicitly add
`--force`.

Confirm that the command and skill use the same release:

```bash
glossabet --version
```

For this source alpha, the expected output is `glossabet 0.1.0`. Codex normally
detects an installed skill automatically; if it does not appear, restart
Codex. These Codex loading and invocation instructions follow the
[official OpenAI skill documentation](https://learn.chatgpt.com/docs/build-skills#how-chatgpt-and-codex-use-skills).

### Claude Code installation

Claude Code users install the skill with:

```bash
glossabet install --agent claude
```

That command writes only `~/.claude/skills/glossabet/`. It also installs a
session-start hook—an automatic command that loads an existing glossary when
a Claude Code session starts, resumes, clears, or compacts. Use `--skill-only`
to install the skill without that automatic command. The folder has passed
offline validation, and Kyle used it successfully in one ordinary Claude Code
session. The repeatable three-scenario Claude Code test is incomplete, so that
single session is not release evidence.

## Use Glossabet on a repository

Start a new Codex session from the root directory of the repository whose
vocabulary you want to work on. In your Codex prompt, mention the installed
skill with `$glossabet` and describe what you want named. For example:

> `$glossabet` Help me establish shared names for the important parts of this
> repository.

Codex can also select the skill automatically when your request clearly asks
for repository naming or vocabulary work.

On its first pass, the skill:

1. checks that the installed command is the matching version;
2. scans the repository without reading known secret files, generated output,
   or vendored dependencies;
3. tells you if any scan limits prevented complete coverage;
4. reads the important production files selected by the scan;
5. proposes three ranked names for each part worth discussing; and
6. waits for you to accept, reject, or reshape those proposals.

Nothing becomes canonical merely because the skill proposed it. The skill does
not write a settled glossary until you explicitly approve the vocabulary and
ask it to finalize.

To try the complete workflow on the included sample instead of one of your own
repositories, run:

```bash
uv run python scripts/run_walkthrough.py
```

[`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md) explains the sample output and then
shows the same process on a real repository.

## Files Glossabet creates

Glossabet keeps three files with different jobs:

- `GLOSSARY.md` is the human-readable vocabulary the team has agreed to use.
- `glossabet-out/glossary.json` is the same workflow's structured state for
  software: accepted and proposed terms, aliases, code locations, and path
  limits.
- `GLOSSABET.md` is a report about the vocabulary's current health. It records
  possible gaps, conflicting uses, changes in the code, open proposals, and
  incomplete analysis. It is not the glossary and never replaces it.

The skill writes `GLOSSARY.md` and the structured state only after the human
settles the vocabulary. It can regenerate `GLOSSABET.md`; that report is kept
out of future scans so it cannot become evidence for itself.

## Core Glossabet terms

The following project-specific terms are canonical within Glossabet's own
documentation. Other project-specific shorthand must be defined before use or
replaced with ordinary language.

| Term | Meaning |
| --- | --- |
| **canonical term** | A project name that a human has explicitly approved as the name the team should use. |
| **engine** | The deterministic Python command-line program. The same repository state produces the same analysis. |
| **agent skill** | The installed instructions that tell Codex or Claude Code how to use the engine and conduct the naming discussion. |
| **evidence** | Facts the engine records from the repository, such as identifiers, documentation words, modules, imports, and excluded files. Evidence informs a proposal; it is not a naming decision. |
| **house register** | The naming style already established by a project's good existing names: word length, casing, tone, and source of metaphors or domain language. |
| **drift** | A difference between the accepted vocabulary and the words or code locations now present in the repository. |
| **scope** | The part of a repository in which a term has a particular meaning. A term without an explicit scope applies to the whole repository. |
| **binding** | A saved connection between a glossary concept and a stable file, module, or code symbol. |
| **coverage record** | The counts and reasons that state how much work was included or omitted. It prevents a partial scan or shortened report from looking complete. |

## Optional Graphify input

Glossabet can also read structural groups exported by
[Graphify](https://github.com/Graphify-Labs/graphify). Graphify is optional.
Without it, Glossabet still analyzes identifiers, documentation, modules, and
simple import relationships.

The adapter accepts Graphify 0.9.42's `links`, `source_file`, `file_type`,
`community_name`, and `built_at_commit` fields, plus the older
`edges`/`source` shapes. Glossabet reports separately whether a graph file
exists and whether it contains usable groups. When Graphify records a commit,
Glossabet compares it with the repository's current commit and uncommitted
changes. A match with no uncommitted changes means the graph is current; a
difference means it is stale; missing proof means its age is unverified. This
detects old graph data but does not prove that the graph's content is genuine.

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

## What evaluation has shown

Glossabet's repeatable evaluation uses three fixed versions of permissively
licensed public repositories—
[Requests](https://github.com/psf/requests/tree/8068356288978c4f54661ae6f95afe0e0831885e),
[hey](https://github.com/rakyll/hey/tree/5626f79b8698df6daf9b25799c9805c6acc96740),
and [p-limit](https://github.com/sindresorhus/p-limit/tree/df476048d023ff868cd45b35ee47f5fb0ca2b25a)—plus
four purpose-built test repositories. Together they contain 99 included source
files and 52 production code files.

On the labelled cases, Glossabet reported all 20 findings that the expected
results listed and reported no extras. All 15 word-analysis checks and all 26
code-structure checks passed. The naming-style evaluation passed all 16 cases.
A separate check required four real repository concepts to be suggested,
required six generic words not to be suggested, and required every suggestion
to identify why it was selected; all 11 expectations passed. The primary
reviewer marked all 20 findings useful. A separate Codex session that could not
see those labels marked 17 useful and disagreed on three.

These are regression-test results, **not evidence that Glossabet works broadly
for real teams**. The dataset and number of findings are small. The evaluation
glossaries were written for this project rather than approved by the public
repositories' maintainers. The expected results are not exhaustive for the
real repositories, and the second reviewer was another Codex session rather
than an outside maintainer. Code-structure completeness is measured only in
the controlled Graphify test repositories. Before calibration, the engine
reported 53 false positives among 64 findings; those results were used to make
the rules for separating files, recognizing identifier patterns, and proposing
possible synonyms more conservative.

The complete methodology, licenses, baseline, thresholds, limitations, and
reproduction command are in [`EVALUATION.md`](EVALUATION.md); raw results are
in [`evaluation/results.json`](evaluation/results.json).

## Command reference

The command-line interface provides:

```
glossabet install                 install the matching agent skill for Codex
glossabet install --agent claude  install the skill and optional startup command for Claude Code
glossabet scan <repo>             scan a repository and save the evidence
glossabet analyze <repo>          scan and report possible vocabulary problems
glossabet inspect <repo>          create current, size-limited JSON for the agent skill
glossabet inspect <repo> --full   include additional diagnostic details
glossabet brief <repo>            print accepted vocabulary without scanning or writing
glossabet sync-context <repo>     copy accepted vocabulary into a marked AGENTS.md section
glossabet sync-context <repo> --agent claude  write the marked section to CLAUDE.md instead
glossabet save <repo>             validate and save glossary JSON received on standard input
glossabet show <repo>             display the current structured glossary
glossabet drift <repo>            compare current repository words with accepted vocabulary
glossabet validate <repo>         compare the glossary with repository and Graphify evidence
glossabet cache-clear             remove Glossabet's user cache, never repository files
```

### What `inspect` gives the agent skill

The installed skill must run `glossabet inspect .` from the exact repository
or subproject root. The command validates project-controlled JSON, scans the
current files, refreshes `glossabet-out/evidence.json`, and prints a versioned,
size-limited JSON document for the skill. Its normal output is checked against
a 100 KB target on this repository and may never exceed 1 MB. The optional
`--full` form includes additional diagnostic detail. Both forms report omitted
repository input under `coverage.corpus` and details removed from the JSON
output under `coverage.context`.

The JSON keeps two sources of glossary information separate:

- `glossary` contains the validated structured state from
  `glossabet-out/glossary.json`.
- `repository_glossary` describes a hand-written root `GLOSSARY.md` without
  copying its contents. It reports whether the file exists, whether it could
  be read safely, whether it is a symbolic link, its size and SHA-256 digest,
  and any nested `GLOSSARY.md` files that the scan ignored. If the file cannot
  be read safely, it is reported as present but unreadable rather than absent.

The skill uses four canonical names for the possible starting states:

- **no glossary** — neither file exists;
- **adoption** — only the hand-written `GLOSSARY.md` exists;
- **resume** — only Glossabet's structured state exists; and
- **managed** — both files exist.

In adoption and managed sessions, the skill analyzes the code before reading
the hand-written glossary. It then compares that independent analysis with the
team's document and reports where a term is supported, weakly represented,
changed, overloaded, missing, mismatched with an alias, or still unresolved.
It asks before treating an already documented term as canonical and edits an
existing `GLOSSARY.md` instead of replacing the whole file.

When both glossary files exist and the Markdown file was read completely,
`repository_glossary.divergence` reports accepted terms missing from the
Markdown and old aliases that remain while their replacement does not appear.
This check examines at most 500 terms and 4 million normalized characters and
reports when either limit applies. It is absent, not empty, when the check
could not run.

The skill never opens Glossabet's JSON files directly and never responds to an
`inspect` failure by reading the repository without limits. Once the human
settles the vocabulary, the skill sends the complete structured glossary to
`glossabet save .`. That command validates the data and writes
`glossary.json` atomically, so a failed write cannot leave a partial file.

`glossabet brief <repo>` is the read-only ambient vocabulary boundary. It
loads only the confined, strictly validated glossary and the hardened live Git
stamp; it does not scan source files, refresh evidence, or write any repository
file. With no glossary it emits nothing. Otherwise it emits at most 4,096 UTF-8
bytes of deterministic plain text: canonical terms with one-line definitions,
scopes, alias statuses, a semantic glossary SHA-256, `{head, dirty}` Git state
plus `glossary.json`'s own state (`committed`/`modified`/`untracked` — `dirty`
deliberately excludes `glossabet-out/`, so it must never be read as "the
glossary is committed"),
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
- One canonical term or alias identity may belong to only one concept in
  overlapping scopes, where identity is the term's normalized word sequence
  (`Alpha Beta`, `AlphaBeta`, and `alpha_beta` are one identity, because
  drift, validation, and matching compare vocabulary by words; `Limit` and
  `Limit Function` stay distinct — the identity is taken before the lexical
  keyword filter); a term with no words is keyed by its NFKC-casefolded
  spelling. Invisible
  formatting characters (zero-width space, word joiner, soft hyphen, BOM)
  are refused in every glossary string. Ambiguous aliases are rejected before the glossary
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
