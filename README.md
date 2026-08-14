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

**Status: v0 feature-complete** — all planned phases are implemented.
`PLAN.md` is the authoritative roadmap (remaining ideas under "Later").
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
validation reports) plus an incremental cache in `<repo>/.glossarize/`.
