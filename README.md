# Glossarize

Make a codebase's vocabulary explicit, canonical, inspectable, and
maintainable.

Glossarize helps a team establish shared names for the parts of a repository —
subsystems, entities, boundaries, protocols, surfaces — and keep that
vocabulary healthy as the code evolves. Deterministic machinery gathers
lexical and structural evidence; an agent skill (`/glossarize`) brainstorms
names grounded in that evidence; **the human decides what becomes canonical**.

Optionally, Glossarize consumes [Graphify](https://github.com/Graphify-Labs/graphify)
output as richer structural evidence and can reconcile the settled glossary
against the structural graph — surfacing unnamed architecture, orphaned
concepts, vocabulary drift, and boundary mismatches. Graphify is never
required.

The adapter supports Graphify 0.9.42's exported `links`, `source_file`,
`file_type`, `community_name`, and `built_at_commit` fields as well as the
older accepted `edges`/`source` shapes. Evidence distinguishes a graph file
being present from usable community structure being loaded. When Graphify's
commit stamp is available, Glossarize reports the structure as current, stale,
or unverified against the repository's HEAD and worktree; structural
validation is explicitly skipped when no usable groups were loaded. “Current”
means the graph's recorded commit matches a clean checkout; because the graph
file is repository-controlled input, this is a staleness signal rather than
content authentication.

## Why repository vocabulary matters

Glossarize is built on an empirically supported problem: names act as part of
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
work. It does **not** by itself prove that Glossarize saves time or produces
better naming decisions. That product claim requires direct evaluation of
Glossarize's precision, false-alarm rate, and usefulness on real repositories;
that evaluation is tracked in `PLAN.md`.

**Status: v0 engine complete through Phase 12; hardening roadmap active.**
`PLAN.md` is the authoritative roadmap for Phases 13–17.
`skill/SKILL.md` is the canonical agent skill (install it by copying to your
agent's skills directory, e.g. `~/.claude/skills/glossarize/SKILL.md`).
The CLI installs with `uv tool install .`:

```
glossarize scan <repo>       deterministic, git-stamped evidence (cached, incremental)
glossarize analyze <repo>    scan + terminology report (register, overlaps, overloads)
glossarize show <repo>       display the current glossary
glossarize drift <repo>      live vocabulary vs the canonical glossary
glossarize validate <repo>   reconcile glossary vs evidence and the Graphify graph
```

Artifacts live in `<repo>/glossarize-out/` (evidence, glossary, drift and
validation reports). The incremental extraction cache is user-owned state,
not repository input: it lives under the platform cache directory
(`$XDG_CACHE_HOME/glossarize` or `~/.cache/glossarize` on Linux,
`~/Library/Caches/glossarize` on macOS, and `%LOCALAPPDATA%\glossarize` on
Windows). `GLOSSARIZE_CACHE_DIR` can override that base; caching is disabled
if the selected directory resolves inside the scanned repository.

## Development

Prerequisites: Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/). The runtime
is standard-library only; `pytest` is the sole dev dependency.

Run the tests:

```
uv run pytest
```

Install the CLI onto your PATH and check it:

```
uv tool install . --reinstall
glossarize --version
```

- `ARCHITECTURE.md` — how the engine is built and how to work on it (start here
  to take ownership).
- `SECURITY.md` — the threat model and the enforced trust boundaries.
- `PLAN.md` — the authoritative roadmap and the binding design principles.
- `skill/SKILL.md` — the canonical `/glossarize` agent skill.
