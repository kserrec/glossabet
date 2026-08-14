---
name: glossarize
description: >-
  Build a shared naming vocabulary for a codebase. Use when the user wants to
  name or rename the parts of a repo, establish a glossary, coin house terms,
  or brainstorm names for components, subsystems, surfaces, data structures, or
  domain concepts. Scans the repo from its root, identifies the parts that
  warrant a name, and proposes three ranked names for each — one recommended
  pick plus two alternates — as the OPENING PASS of a brainstorm with the user,
  never as a final answer. Works for any repo, visual or purely backend.
---

# glossarize

Give the parts of a codebase good, shared names so people can talk about it
precisely. This skill does the first pass: it scans, decides what deserves a
name, and proposes candidates. Naming is then finished with the user, term by
term — the skill only gets the brainstorm going.

## Audience — write for regulars

Everything this skill produces is for people who **already work in the project
regularly**. Assume they know the domain and the codebase. Do not add newcomer
onboarding, "what this repo is" primers, or explanations of basics. Be precise
and dense. The value is in sharp names and the reasoning behind them, not in
accessibility to outsiders.

## Stance (read this first)

- *The first pass is a brainstorm opener, not a verdict.* Present proposals as
  "here's where I'd start," then react to the user's picks, rejections, and
  half-likes. Expect to iterate for many turns, propose fresh alternates on
  demand, and change course. The user decides; you generate and reason.
- *Never finalize unilaterally.* Do not write a canonical glossary file until
  the user has actually settled the terms. "Locked" means they said so.
- *One thing, one name.* The goal is that everyone uses the same word for the
  same thing. Distinctness matters more than cleverness.

## Step 0 — Ground in engine evidence (when available)

The glossarize engine (`glossarize` CLI) can pre-compute deterministic
evidence for this skill. Before Step 1, check whether
`glossarize-out/evidence.json` exists at the repo root.

**Freshness check (never skip):** compare the file's `repository.git.head`
and `repository.git.dirty` against the live repo (`git rev-parse HEAD`,
`git status --porcelain`). Fresh means: heads match AND neither the stamp nor
the live tree is dirty. Anything else — mismatch, dirty, missing stamp — is
stale or uncertain.

- **Fresh** → ground yourself in it and tell the user you're using engine
  evidence.
- **Stale or absent, CLI installed** → say so and refresh it yourself
  (`glossarize scan .` — cheap and deterministic), then proceed on the new
  evidence.
- **Stale or absent, no CLI** → say evidence is unavailable and fall back to
  direct repository reading. Every later step works unchanged without
  evidence.

**Never silently ground yourself on stale evidence.** Always state which mode
you are in: fresh evidence, refreshed, or direct reading.

**How the evidence feeds the later steps:** `totals`, `languages`, `modules`,
and `files` seed Step 1's map of the repo; `vocabulary.identifiers` (real
identifier spellings with counts) is raw material for Step 2's house-register
inference; `vocabulary.tokens` (normalized, with counts and representative
locations) plus `modules` ranks material for Step 3's nominations;
`vocabulary.doc_terms` shows what the documentation talks about. Evidence
*guides* — it never replaces judgment. Still read the key files before
proposing: never nominate a part from counts alone (real parts only), and
treat any list carrying a truncation marker as partial, not complete.

### Monorepo alert

If the evidence says `monorepo.detected: true`, **stop before nominating**.
Tell the user what was detected (the `reasons` and `sub_roots`) and ask
plainly: proceed whole-repo, or run glossarize per sub-project? Vocabulary is
usually healthier per sub-project. Never proceed silently on a flagged
monorepo.

### Existing glossary — resume, don't restart

Also check for `glossarize-out/glossary.json`. If it exists, this repo's
vocabulary is already partly settled, and you are resuming a maintained
glossary, not opening a fresh brainstorm:

- **`canonical` concepts are decided.** Do not re-nominate or re-propose
  them; list them briefly as "already canonical, keeping" and only revisit
  one if the user asks or if you find a genuine conflict worth surfacing.
- **`proposed` concepts are the open items.** Pick the brainstorm up there.
- **`deprecated`/`discouraged`/`alias` entries are constraints** on new
  proposals: never propose a term the glossary already discourages, and note
  when a candidate collides with an existing alias.
- Nominate **new** candidates only for parts no existing concept covers.
- If the file fails to load, say so and treat the glossary as absent —
  never guess at half-read vocabulary. (`glossarize show` displays it.)

## Step 1 — Scan the repo from its root

Build a mental map of what this codebase is and what its parts are:

- Read README, CLAUDE.md/AGENTS.md, ARCHITECTURE, docs/, and any
  design notes. These name the problem domain and the intended structure.
- Map the directory tree and the module boundaries. Note the entry points, the
  services/daemons, the shared contracts, the data layer, the public surfaces.
- Skim the principal types/interfaces, the protocol/message/event shapes, the
  core domain entities, and the boundaries between trust or ownership zones.
- Adapt to the repo's nature. A visual app has surfaces, panes, and components
  to name; a pure-backend service has subsystems, pipelines, entities, jobs,
  events, and boundaries instead. Name what this repo actually has.

Ground everything in real code — cite path or path:line. Never invent a part
that isn't there, and never rename something without having looked at it.

## Step 2 — Infer the house register

Before proposing anything, learn how this project already names things. Look
at existing good names and match their style:

- word count (one-word? two-word compounds?), tone (plain vs. playful),
  lineage (terminal/unix, nautical, domain jargon, product-y), casing.
- If a `CLAUDE.md`/README states a voice or naming rule, honor it exactly.

Proposals that clash with the house register are wrong even if they're clever.

## Step 3 — Decide what warrants a name

Nominate the parts that people actually need to talk about. Good candidates:

- *Surfaces / screens / views* a user switches between (visual repos).
- *Subsystems / services / modules* with a clear job.
- *Key data structures / entities* — the core nouns of the domain.
- *Protocols / contracts / message or event shapes.*
- *Boundaries / seams* — trust, ownership, tenancy, or security lines. These
  are the highest-value names: a name that encodes a boundary teaches the rule
  every time it's spoken.
- *Long-lived processes / daemons / workers / jobs.*
- *Pipelines / flows / lifecycles.*
- *Roles / actors.*

Prioritize: things referred to by a vague phrase ("the thing that does X"),
things named only by file path, things with awkward or overloaded names, and
things that come up constantly in conversation. Skip trivial internals nobody
discusses — don't name every function. Also flag things that are already
well-named and should simply be kept (canonical, leave alone).

Watch for *meaningful distinctions that deserve to be split into two names* —
where one word is currently doing two jobs, or two related things share a name
and blur an important line. Surfacing those is often the most valuable output.

## Step 4 — Propose three ranked names per thing

For each nominated part, give a one-line "what it is" (grounded in code) and
three candidates, ranked, with the pick standing out and the alternates to the
side. Use this layout:

**<thing>** — <one-line what it is> (`path`)
  → **`pick-name`** — one clause on why it's the recommendation
     alternates: `alt-one` · `alt-two`

Rules for the candidates:

- The *pick* leads and carries a short reason. The two *alternates* sit
  beside it with a quick tradeoff each (why it's a real option, why it ranked
  lower). No long essays per name.
- *Primary decisions get a real explanation.* For the load-bearing terms —
  the boundary-encoders, the split-a-word-in-two pairs, anything central to how
  the project is discussed — write a short paragraph on why this name and
  what line it draws, not just a clause. Minor terms can stay one-liners.
- All three must fit the house register from Step 2.
- Prefer names that are distinct from each other and from existing terms, and —
  where relevant — that quietly encode what the thing is or which side of a
  boundary it's on.
- For a distinction worth splitting, propose the pair together and say what
  line the two names draw.

Group the output by category (surfaces, subsystems, entities, boundaries, …) so
the user can move through it in chunks.

## Step 5 — Brainstorm to a decision, with the user

After the first pass, work term by term:

- Take the user's locks, rejections, and "I like the one-word one but…" notes.
- On request, generate fresh alternates from a different thread (another
  lineage, a tighter compound, a bolder metaphor) rather than defending the
  first set.
- When the user coins their own word, adopt it and check it against the register
  and against collisions with existing terms; note any clash honestly.
- Keep track of what's *locked* vs. *still open*.

## Step 6 — Finalize (only when asked)

When the user says the vocabulary is settled, offer to write a standalone
GLOSSARY.md at the repo root. It is written for regulars (see Audience) and
carries both the terms AND the reasoning. Structure:

- *A house-register line* — the naming style the project holds itself to.
- *The headline distinction(s) first* — any boundary-encoding pair, as prose:
  the two names, what each is, and the line between them stated as a rule people
  can repeat. This is the part that must explain itself, not just define.
- *Detail tables, grouped by category* (surfaces, subsystems, entities,
  boundaries, sessions, …). Columns: *Term · What it is · Notes*, plus a
  *(was)* column wherever a term is a rename, so regulars can map old to new.
  The "Notes" column carries the useful specifics — collisions to avoid, why a
  precise term was kept, where it lives in code.
- *A short "primary decisions" section* — a few sentences each on the calls
  that shaped the vocabulary (the coined words, the splits, the renames that
  might surprise someone), so the reasoning survives past the conversation.
- *The one load-bearing rule* at the end, if there is one.

Alongside GLOSSARY.md, write the machine-readable
`glossarize-out/glossary.json`:

```json
{
  "schema_version": 1,
  "concepts": [
    {
      "id": "payment",
      "term": "Payment",
      "definition": "An attempt to collect money for an order.",
      "status": "canonical",
      "aliases": [
        {"term": "charge", "status": "discouraged",
         "note": "the gateway operation only"}
      ],
      "bindings": [
        {"ref": "symbol:PaymentService"},
        {"ref": "module:src/billing"}
      ],
      "notes": "optional freeform"
    }
  ]
}
```

`bindings` are optional and connect a concept to its implementation for
`glossarize validate`. Write them only when the user confirms the mapping,
and only against stable identities — `symbol:`, `file:`, `module:` — never
graph community or node ids, which change across rebuilds. A binding that
later stops resolving is reported as drift, not an error.

Statuses: `canonical` (human-settled — **only** terms the user explicitly
locked), `proposed` (still open at session end), `alias`, `discouraged`,
`deprecated`, `unknown`. Both files together are the glossary: GLOSSARY.md
carries the reasoning for people, glossary.json carries the state for
machines (resumption, `glossarize show`, and future drift detection).

Optionally offer to rename code comments/identifiers and update docs to match —
but only the ones the user approves, and as its own reviewable change.

## Principles

- *Write for regulars.* Assume domain fluency; skip the onboarding.
- *Carry the reasoning.* The primary decisions must explain themselves; a
  glossary of bare names loses the why the moment the conversation ends.
- *Real parts only.* Every named thing must exist in the code you read.
- *Match the register.* The project's own voice wins over your taste.
- *Names that mark boundaries are worth the most.* Spend effort there.
- *Don't overwhelm.* Name what gets talked about; skip the rest.
- *The user names the world; you get it started.*
