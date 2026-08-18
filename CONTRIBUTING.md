# Contributing to Glossabet

Glossabet is currently under an **owner self-testing pause** (see the top of
`PLAN.md`): outside contributions and maintainer invitations are not being
accepted until Kyle explicitly ends it. This document records the terms that
will apply when they are, so nobody is surprised later.

## License of contributions

Glossabet is licensed under the Apache License 2.0 (`LICENSE`). By
submitting a contribution you agree that it is licensed under Apache-2.0
(Apache License §5) and that you have the right to submit it under those
terms.

## Developer Certificate of Origin (DCO)

Every commit must carry a sign-off line certifying the
[Developer Certificate of Origin 1.1](https://developercertificate.org/) —
an 11-line statement that you wrote the change, or otherwise have the right
to submit it under the project's license. There is no document to sign and
no account to create; the sign-off is one trailer in the commit message:

```
Signed-off-by: Your Name <you@example.com>
```

Git adds it for you:

```
git commit -s
```

Use a real name and an email address you control. Sign-offs from AI coding
assistants do not count; the human who reviewed and submitted the change
signs. Existing history predates this requirement and is not rewritten.

There is no automated check today; a maintainer will ask you to add the
trailer before merging if it is missing.

## What contributions must respect

- `PLAN.md` is the authoritative roadmap and lists the binding principles
  (human authority over vocabulary, lexical-first scanner, no contamination,
  no secrets ingested, determinism, bounded work with logged truncation).
- `skill/SKILL.md` is the behavioral spec; its philosophy is preserved
  verbatim, never diluted by machinery.
- Dependencies must earn their place: a real use site and a one-line
  cost/reason, stdlib-first.
- Tests protect concrete threats, not coverage numbers.

Development setup, the test suite, and the release gate are described in
`README.md` ("Development and release verification") and `RELEASING.md`.
