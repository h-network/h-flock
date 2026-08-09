# Review 03 — hardcoded values

> Find values baked into code that should come from the environment, the roster
> or `.env` — and leave alone the ones that are correctly fixed.
>
> **Pull `main` first.** Fix your own files; report anything else.

## 1. The distinction that makes this useful

Not every constant is a defect. Two kinds, and confusing them makes things worse:

| | example | verdict |
|---|---|---|
| **A fact about the image or the design** | `/home/ubuntu` — the container runs as `ubuntu` and the CLIs expect that home | **leave it.** Deriving it implies a choice that does not exist |
| | `redis://127.0.0.1:6379/0` — a fact inside a tenant, `LLD-container` §1 | **leave it** |
| **Per-office configuration** | pod, tenant, container name, session name, agent names | **must be derived** |

⚠ **Adding configuration nobody wants is a defect too.** If a value can only
ever be one thing, a knob for it is a new way to get it wrong. The test is:
*could two working offices legitimately differ here?*

## 2. Three real ones, already found

Not hypotheticals — these were in `main` this morning:

1. **`seed-home.sh` and `plumbing-check.sh`** hardcoded `h-flock-hq-tenant-1` and
   `pod:acme:tenant:hq`, so they worked against exactly one office. Fixed — both
   now read `container/.env`.
2. **`/restdoc` still advertises `bob`.** `src/flock/api/app.py` carries `curl`
   examples against `/agents/bob/…` and a session payload naming `alice`. The
   rename covered `docs/` and missed `src/`, so **the API page the tenant serves
   about itself names agents that exist in no default office.**
3. **The agent guide** in `src/flock/tmux/ops.py` says *"a message arrives as
   `[message from alice]`"* — the one document every agent reads.

⚠ **2 and 3 are user-facing output, not comments.** They are the examples people
copy.

## 3. What to scan

Your own module, for values that should vary per office:

- pod, tenant, container name, tmux session name
- agent names — in code, in served documentation, in generated text
- paths that embed an agent name or a tenant
- ports, when not read from the environment with a documented default
- key prefixes assembled by hand rather than through `prefix()`
- timeouts and intervals that a real deployment might need to differ on — report
  these, do not add knobs for them

⚠ **Look at strings you *emit*, not only ones you branch on.** All three found so
far were in output — a served doc page, a guide, a script's default. Code that
merely reads a constant is easy to spot; text that ships it is not.

## 4. What not to do

⚠ **Do not add environment variables speculatively.** Report a value you think
should be configurable and say why; do not make it so.

⚠ **`VERIFIED-*`, `BUILD-*`, `AUDIT-*`, `REVIEW-*` are records.** A hardcoded
name in one of them is correct.

⚠ **Test fixtures are fine.** A test that uses `alice` is not a finding unless it
would fail for `sme-2` — that was review 02 and it is done.

## 5. Reporting

`jira done`, then message `architect` with, per finding: **where**, **what it
should come from**, and **whether two offices could legitimately differ**. Plus
what you scanned and found correctly fixed.
