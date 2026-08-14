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

**Status: early phases.** `PLAN.md` is the authoritative roadmap.
`skill/SKILL.md` is the canonical agent skill (install it by copying to your
agent's skills directory, e.g. `~/.claude/skills/glossarize/SKILL.md`); the
CLI installs with `uv tool install .` and currently provides
`glossarize scan <repo>`, which writes deterministic, git-stamped repository
evidence to `<repo>/glossarize-out/evidence.json`.
