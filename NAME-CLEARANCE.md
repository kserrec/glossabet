# Glossabet name decision and point-in-time checks

Checked on 2026-08-15 at 04:09 PDT. This record supports a product decision;
it does not reserve a name, create trademark rights, or replace a lawyer's
clearance opinion.

## Decision

Kyle selected **Glossabet**, pronounced “GLOSS-uh-bet,” as the replacement
for the repository's pre-rename working title. The coinage joins `glossa`
(Greek: language or tongue) with `bet` (Amharic ቤት: house, home) — a
"glossary home."

**Correction, 2026-08-17.** Until this date the paragraph above read that the
coinage joined `glossa` "with the ending of `alphabet`." That was Claude's
inference when writing this record on 2026-08-15, made without asking Kyle
how he had arrived at the name, and it was wrong. Kyle's actual derivation,
in his words: he was working from the idea of a *home* for a project's
terms — earlier candidates were *termstead* (from homestead) and *nomenbase*
(base, as in home base), then *glossacasa* (Spanish *casa*, house), and then,
via a close Ethiopian friend's language, Amharic *bet* for house — which
produced *Glossabet*. The resemblance to the ending of *alphabet* was
something Kyle had not noticed; Claude pointed it out afterward, and Kyle
regarded it as a pleasant coincidence. Git history preserves the earlier,
incorrect wording; this paragraph exists so the two versions are not read as
contradictory records of the same fact.

**Note on "Alphabet."** The coined word is phonetically close to *Alphabet*,
the name of Google's parent company. That proximity is coincidental (above)
and, in Kyle's and Claude's non-lawyer reading, not confusingly similar in
this goods/services context: a local command-line vocabulary tool for
codebases is not the class of goods or services for which that mark is known,
the leading element `glossa-` is distinctive, and there is no use in commerce
that could suggest affiliation. It is recorded here because a clearance
opinion would at least consider it, and because a reader who notices the
echo should find it already acknowledged rather than overlooked.

The Phase 21 exit is **rename**: the source distribution, Python package and
import, command, agent skill, Codex plugin, configuration file, output
directory, cache namespace, and documentation now use `glossabet`. Old
`glossarize-out/` and `.glossarize/` directories remain ignored inputs so
pre-rename local artifacts cannot contaminate a new scan; they are not read,
migrated, or deleted.

At the Phase 21 checkpoint, this source repository's configured Git remote was
still `git@github.com:kserrec/glossarize.git`, and Kyle's separate user
installation at `~/.local/bin/glossarize` still reported version 0.0.1. Both
were deliberately left unchanged during that phase. Later on 2026-08-15, with
Kyle's explicit authorization, the public GitHub repository was renamed to
`kserrec/glossabet`, the configured remote was updated to
`git@github.com:kserrec/glossabet.git`, and the local checkout directory was
renamed to `glossabet`. The separate legacy installation remains untouched;
no package or plugin was published.

## Exact-name results

| Surface | Probe | Observed result |
| --- | --- | --- |
| Local command | `command -v glossabet` | No command on the normal shell `PATH` before the source build. |
| Configured Codex plugins | `codex plugin list --available --json`, filtered to the exact name | No installed or available plugin named `glossabet`; only the `openai-curated` marketplace was configured. |
| GitHub repositories | GitHub Search API, `glossabet in:name` | 0 repositories. |
| GitHub accounts | GitHub Search API, `glossabet in:login` | 0 accounts. |
| PyPI | `https://pypi.org/pypi/glossabet/json` | HTTP 404. |
| npm | `https://registry.npmjs.org/glossabet` | HTTP 404. |
| RubyGems | `https://rubygems.org/api/v1/gems/glossabet.json` | HTTP 404. |
| crates.io | `https://crates.io/api/v1/crates/glossabet` | HTTP 404. |
| NuGet | `https://api.nuget.org/v3-flatcontainer/glossabet/index.json` | HTTP 404. |
| Domains | RDAP for `glossabet.com`, `.net`, `.org`, `.dev`, `.io`, and `.ai` | Final HTTP 404 for all six names. |
| Historical domain use | Internet Archive CDX query for `glossabet.com` | No capture was returned in the 2026-08-14 preliminary check. |
| General indexed use | Exact web searches for `"Glossabet"` and product/company/app variants | No exact current use was returned in the 2026-08-14 preliminary check. |

An HTTP 404 or zero search count only records what that endpoint returned at
that moment. It is not a reservation, ownership proof, availability promise,
or exhaustive search of unindexed/private uses.

## U.S. federal trademark search

The official USPTO Trademark Search interface was probed directly in a
headless browser on 2026-08-15:

- `CM:GLOSSABET` returned “Result 1 of 0” and “No results found.”
- `CM:/.*glo+s+a[ -]?be+t+.*/ AND LD:true` returned the same zero-result
  state for a live-record spelling-neighborhood query.

Those queries cover the exact coined term and one deliberately broad spelling
pattern. They do not exhaust sound-alikes, translations, design marks, state
registrations, common-law use, company-name databases, or confusingly similar
marks evaluated in their actual goods/services context. The USPTO itself
describes a federal database search as one part of a broader
[clearance search](https://www.uspto.gov/trademarks/search/comprehensive-clearance-search-similar-trademarks).

## Public-state boundary

No package name, domain, hosted repository name, trademark, Git tag, GitHub
Release, or plugin-directory entry was created or reserved by these checks.
The later hosted-repository rename was separately authorized and was not part
of these clearance checks. Before publication, rerun the exact package,
plugin-directory, domain, and trademark probes from the release candidate and
obtain any legal review appropriate to the risk Kyle chooses to take.
