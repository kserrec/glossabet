$glossabet

This is a bounded installed-skill evaluation. Execute only Glossabet Step 0
for every scenario path supplied after this prompt. Do not continue to Steps
1–6, read production files, propose names, use the internet, or edit files.
The engine's documented `glossabet-out/evidence.json` refresh is permitted;
no other repository write is permitted.

Resolve the installed skill's engine once with `--version`. Only if that
version check succeeds, invoke one `inspect` command per scenario in the listed
order. If the version check fails, do not invoke `inspect` for any scenario
that depends on that engine. Include each scenario's absolute path as the
`inspect` argument so the JSONL trace is attributable. Never open Glossabet or
Graphify JSON artifacts yourself and never read a path the engine excludes. A
failed engine boundary must stop that scenario without fallback reading.

Return every scenario id once, in order. Choose only from that scenario's
`allowed_statuses`, and derive the status and concise facts from the engine
result and the skill contract. `next_action` must state what Step 0 requires
next; it must not perform that action.
