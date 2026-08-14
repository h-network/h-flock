# Build 41 — audit remediation, wave 3 (the last one)

> `docs/AUDIT.md` sections 5 and 6: fourteen documented claims that are false,
> and seven fragility items. Waves 1 and 2 are merged — 332 tests, plumbing
> 25/25, simulator 19/19 on a fresh tenant.
>
> **Base on `main`.** Branch `<lane>/build-41-<piece>`, push to origin.

⚠ **This wave is mostly writing, which makes it the easiest one to do badly.**
Prose that sounds right and does not match the code is exactly the defect being
fixed. **Every corrected claim must be checked against the code first**, and I
will spot-check the claims rather than the prose.

⚠ **The rules that worked twice are unchanged.** Confirm before fixing.
Rejecting a row is a success — three rows have been correctly rejected so far.
Report on every row you were given, including the ones you did not do.

⚠ **Where the fix is a code change, prefer it.** A doc that describes awkward
behaviour accurately is worse than behaviour that needs no paragraph. Say which
you chose.

## 1. `bus` lane — rows 30, 32, 38, 39, 44, 48, 49, 50

| # | claim to check | |
|---|---|---|
| 30 ✅ | the LLD says the broadcast fan-out is "pipelined, not atomic"; `pipeline()` defaults to `transaction=True`, so it **is** atomic | `switch/service.py:78`, `LLD-bus-and-switch.md:637` |
| 32 | the five-record claim does not hold for `recipient: "all"` — per-recipient deliveries are indistinguishable | `bus/doors.py:53` |
| 38 | "the switch does not rewrite the envelope" is absolute in one place, contradicted by a documented exception in another | `LLD-bus-and-switch.md:632-635`, `:743-747` |
| 39 | `popped` is not emitted "before doing anything" and carries the corrected producer | `switch/service.py:52-67` |
| 44 | `Redis.from_url` yields **zero** connection retries — load-bearing, undocumented, and the obvious "improvement" would break at-most-once | `bus/` |
| 48 | presence pulls up to 1000 stream entries per agent per pass to read one timestamp | `bus/` |
| 49 | `waited` reports the configured threshold, not the actual wait | `switch/service.py` |
| 50 | dead code that hides an intent | — |

⚠ **Row 30 is verified and the interesting question is which way to fix it.**
Atomic fan-out may be better than the documented behaviour — if so, say so and
keep it, correcting the doc. If the non-atomic claim was load-bearing for some
reader, say what depended on it.

⚠ **Row 44 deserves a sentence in the LLD, not a change.** Zero retries is what
makes at-most-once true. Document why the obvious improvement is wrong.

## 2. `api` lane — rows 33, 34, 35, 40, 41, 45

| # | claim to check | |
|---|---|---|
| 33 | `API.md` tells browser developers to open the WebSocket with a Bearer header. **Browsers cannot send one** — found by both offices | `docs/API.md:625-642`, `session/app.py:88-96` |
| 34 | the close-code vocabulary is undocumented and `4401` never reaches a client | `session/app.py:180-219` |
| 35 | `/alerts` names a field the watchdog never writes; only a fallback saves it | `api/app.py:751`, `watchdog/service.py:103-107` |
| 40 | the wire encoding of terminal bytes is documented only in a comment in the reference client | `session/control.py:197`, `LLD-session.md:176` |
| 41 | an example response omits the `vab` field that is implemented and advertised | `api/app.py:584-598`, `docs/API.md:220-223` |
| 45 | nothing bounds the size of anything a client can send or ask for | `api/app.py:600-639`, `bus/doors.py:28` |

⚠ **Row 33 is the one that costs users time.** A developer follows the
documented instruction, it cannot work in a browser, and the failure looks like a
broken door. Document what *does* work — the console proxies server-side for
exactly this reason.

⚠ **Row 45 is a code row in a documentation section.** An unbounded request is
not a doc problem. Pick limits, state them in `API.md`, and reject past them with
the vocabulary from §7.

## 3. `tmux` lane — rows 36, 37, 43, 46, 47

| # | claim to check | |
|---|---|---|
| 36 | `LLD-port-tmux` §4 documents a pane read that does not exist and would break invariant 7 | `LLD-port-tmux.md:189-192` |
| 37 | `LLD-tmux-host` describes two bugs that were already removed | `tmuxhost/host.py:185-208`, `tmux/ops.py:136-142` |
| 43 | two smaller doc claims that are false today | `LLD-tmux-host.md:156`, `docs/TODO.md:54` |
| 46 | the Redis readiness wait has no deadline | `container/entrypoint.sh:128` |
| 47 | a configured Redis password is not URL-encoded, so reserved characters produce a broken `REDIS_URL` | `container/entrypoint.sh:107-113` |

⚠ **Row 47 is now narrower than when it was written.** Wave 2 stopped the URL
reaching agent windows, so this is about the switch and watchdog receiving a
malformed URL — still real, still worth encoding.

⚠ **Row 43 touches `docs/TODO.md`, which I own.** Tell me the line; do not edit.

## 4. Mine

Rows 31 and 42 — `CONTRACTS` §3 claiming nothing writes a log file when the
switch depends on one, and §9 omitting variables the container sets.

## 5. Done when

- every row confirmed or rejected in writing, with lines
- code rows have a test that fails without the fix
- `python3 -m pytest -q` green — 332 at the time of writing
- ⚠ **the tenant still boots.** I run that pass.

## 6. Reporting

`jira done`, then message `architect` with the commit you worked from, rows
confirmed, rows rejected and why, and what you ran.
