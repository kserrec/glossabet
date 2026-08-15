# Glossabet

Make a codebase's vocabulary explicit, canonical, inspectable, and
maintainable.

Glossabet helps a team establish shared names for the parts of a repository —
subsystems, entities, boundaries, protocols, surfaces — and keep that
vocabulary healthy as the code evolves. Deterministic machinery gathers
lexical and structural evidence; an agent skill (`/glossabet`) brainstorms
names grounded in that evidence; **the human decides what becomes canonical**.

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
all 26 structural contracts passed. The primary reviewer marked 20/20 findings
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

**Status: 0.1.0 source alpha under post-audit hardening; not yet published to
PyPI or a plugin directory and not yet a trusted-alpha release.** The
Glossabet name decision and local Codex plugin lifecycle are recorded and
tested. Phase 22 also passes 11/11 installed-skill scenarios on Codex CLI
0.147.0/Linux. Outside maintainer alpha evidence is the next gate; do not
describe the current stopping point as release-ready. See
[`NAME-CLEARANCE.md`](NAME-CLEARANCE.md) for the
point-in-time name checks, [`DISTRIBUTION.md`](DISTRIBUTION.md) for exact
installation ownership, [`PLAN.md`](PLAN.md) for the closure sequence, and
[`RELEASING.md`](RELEASING.md) for external actions.

The preferred future Codex artifact is the version-coupled plugin prototype at
`plugins/glossabet/`. It carries the canonical skill and a matching wheel that
runs from the plugin cache without adding a command to `PATH`. No public
marketplace entry exists yet. For local use from a source checkout, the
standalone fallback installs the CLI and then makes a separate skill copy:

```bash
uv tool install . --reinstall
glossabet install
```

Codex currently loads personal skills from `~/.agents/skills`; Claude Code
users can instead run `glossabet install --agent claude`, which targets
`~/.claude/skills`. That Claude route is experimental until an installed
Claude Code session is directly tested. The wheel carries the exact canonical
[`skill/SKILL.md`](skill/SKILL.md), and installation refuses to overwrite a
different skill unless `--force` is explicit. The locations follow the
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
glossabet scan <repo>       deterministic, git-stamped evidence (cached, incremental)
glossabet analyze <repo>    scan + terminology report (register, overlaps, overloads)
glossabet inspect <repo>    fresh, bounded JSON context for the agent skill
glossabet save <repo>       validate/save glossary JSON from standard input
glossabet show <repo>       display the current glossary
glossabet drift <repo>      live vocabulary vs the canonical glossary
glossabet validate <repo>   reconcile glossary vs evidence and the Graphify graph
```

The installed skill requires `glossabet inspect .` from the exact repository
or subproject root. That command safely validates repository-controlled JSON,
builds current evidence, refreshes `evidence.json`, and emits a separate
versioned context capped at 1 MB. The context reports scanner omissions under
`coverage.corpus` and agent-projection omissions under `coverage.context`.
The skill never opens Glossabet JSON artifacts itself and does not fall back
to unrestricted recursive reading when the CLI boundary fails. When the human
settles terms, the skill sends the complete JSON document to `glossabet save
.` on standard input; that command bounds, strictly validates, confines, and
atomically persists `glossary.json` instead of letting the agent write it.

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

The evidence freshness stamp records the commit and worktree state
with live Git state while excluding only that top-level `glossabet-out/`
directory. This makes a clean repository immediately fresh after its first
scan, whether generated output is tracked or untracked. Changes elsewhere
inside the scanned root — including `GLOSSARY.md` and `graphify-out/` — remain
visible. Pre-rename `.glossarize/` and `glossarize-out/` paths stay excluded so
old tool artifacts cannot contaminate a new scan. A subproject scan uses that
subproject, not an enclosing Git worktree, as its scope. The freshness check
still treats cache and pre-rename paths like ordinary Git state unless Git
ignores them; only the top-level current `glossabet-out/` is filtered from Git
status. Git-ignored files follow Git's normal
semantics and therefore cannot make the stamp dirty; a repository without a
readable `HEAD` is reported as unverified. The skill does not reimplement this
check: `inspect` builds its bounded context from live inputs in that same CLI
invocation. This is not an atomic filesystem snapshot; do not scan while an
untrusted process is mutating the checkout.

Glossabet never creates or edits the target repository's `.gitignore`.
Repository owners decide which artifacts to track. Removing the derived
reports is sufficient cleanup when the glossary should be retained; the
user-cache directory can be removed independently because it is only a
performance optimization.

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

An optional `glossabet.json` at the scanned root can add ignored paths,
classify project-specific layouts, or mark a conventionally non-production
path as production:

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

Prerequisites: Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/). The runtime
is standard-library only; `pytest` is the sole development dependency, and
Hatchling is isolated to builds. One reusable quality workflow tests CPython
3.10–3.14 on Linux, macOS, and Windows before packaging; both ordinary CI and
the manual publication workflow must pass it.

Run the tests:

```
uv run pytest
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
git diff --exit-code -- plugins/glossabet
uv run python scripts/check_distribution.py dist --tag v0.1.0
uv run python scripts/wheel_smoke.py dist
uv run python scripts/plugin_smoke.py dist
```

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
