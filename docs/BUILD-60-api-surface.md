# Build 60 — the API surface has grown two features it does not document

> **Base on `main`.** Branch `api/build-60-api-surface`, push to origin.
> Owner: `api` — `docs/API.md` and `clients/` are theirs.

## 1. What is undocumented

Builds 53 and 54 changed what an external application can observe, and
`API.md` records only half of it.

| added | in `API.md`? |
|---|---|
| the **frame** — `v`, `l2`, `l3` replacing a flat envelope (build 53) | partly — 8 mentions, verify it is complete and correct |
| a send can be **refused by policy**, returning **422** (build 54) | ⚠ **nothing. Zero mentions of policy or `send_refused`** |

⚠ **The door already behaves correctly** — `api/app.py:664` turns an
`EnvelopeError` into `HTTPException(422, detail=...)`. This build is not a bug
fix. It is that an application developer receives
`422: policy denied: no shared export/import tag` with **no way to learn that
tags exist**, what governs them, or whether it is their fault.

## 2. What to write

- **The frame on the wire.** Verify the existing 8 mentions describe what
  `build()` actually produces today: `v, kind, stream_id, correlation_id, ts,
  l2, l3, payload`. ⚠ Generate one and compare field by field — do not trust the
  prose, including the prose you wrote.
- **Policy.** Export/import tags, intersection, **permit when absent inside a
  tenant** (`DESIGN-layers` §7.5), and that a refusal is **synchronous, before
  the envelope is enqueued** — so a 422 means nothing was sent, not that
  something was sent and lost.
- **`send_refused`** as a custody record, alongside the five in `CONTRACTS` §3.
- ⚠ **A qualified non-local destination also 422s** (build 53) — the same status
  for a different reason. Say how a caller distinguishes them.

## 3. ⚠ The clients are the second half

`clients/telegram/bot.py` and `clients/web/server.py` post envelopes. **Find out
what they do with a 422 today** and report it, before changing anything.

If they surface it as a generic failure, a user sees "send failed" when the real
answer is "you are not permitted to message that participant" — which is the
kind of thing this project has repeatedly found *after* shipping. ⚠ **Report
what you found first; the fix is a second commit.**

## 4. Done when

- `API.md` covers §2, with the frame verified against a generated one
- what the clients currently do with a 422 is **reported**, then improved
- ⚠ **negative control** per [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1: post a
  denied send through the door and show the **422 and its body**; and post a
  permitted one and show it still succeeds. **A policy that has only ever
  permitted is not known to deny — through the door as well as in the library.**
- `python3 -m pytest -q` green (361 at the time of writing)

## 5. ⚠ Not in scope

Do not change policy behaviour, the frame, or the door's status codes. This
build documents what exists and makes clients handle it. **If you find the door
doing something you think is wrong, report it and stop** — that is a finding,
not a fix.
