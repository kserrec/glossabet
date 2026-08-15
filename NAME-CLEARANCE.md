# Glossabet name decision and point-in-time checks

Checked on 2026-08-15 at 04:09 PDT. This record supports a product decision;
it does not reserve a name, create trademark rights, or replace a lawyer's
clearance opinion.

## Decision

Kyle selected **Glossabet**, pronounced “GLOSS-uh-bet,” as the replacement
for the repository's pre-rename working title. The coinage joins `glossa`
(language or tongue) with the ending of `alphabet`.

The Phase 21 exit is **rename**: the source distribution, Python package and
import, command, agent skill, Codex plugin, configuration file, output
directory, cache namespace, and documentation now use `glossabet`. Old
`glossarize-out/` and `.glossarize/` directories remain ignored inputs so
pre-rename local artifacts cannot contaminate a new scan; they are not read,
migrated, or deleted.

This source repository's configured Git remote is still
`git@github.com:kserrec/glossarize.git`, and Kyle's separate user installation
at `~/.local/bin/glossarize` still reports version 0.0.1. Both are external,
user-owned state and were deliberately left unchanged. Renaming the hosted
GitHub repository and publishing any package or plugin remain separate,
explicitly authorized actions.

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
Before publication, rerun the exact package, repository, plugin-directory,
domain, and trademark probes from the release candidate and obtain any legal
review appropriate to the risk Kyle chooses to take.
