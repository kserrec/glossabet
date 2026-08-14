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

**Status: pre-implementation.** `PLAN.md` is the authoritative roadmap;
`skill/` will carry the agent skill. Nothing is installable yet.
