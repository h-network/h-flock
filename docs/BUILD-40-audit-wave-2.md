# Build 40 — audit remediation, wave 2

> `docs/AUDIT.md` sections 2, 3 and 4: failures that read as success, the hire
> path, and the watchdog. Wave 1 (section 1) is merged, 320 tests, plumbing
> 25/25 and simulator 19/19 on a fresh tenant.
>
> **Base on `main`.** Branch `<lane>/build-40-<piece>`, push to origin.

## 0. The rules that worked in wave 1 — unchanged

- **Confirm before fixing.** Open the cited lines. Decide whether the finding is
  real *at the current commit*.
- ⚠ **Rejecting a row is a success.** Wave 1 closed row 16 that way, with
  citations showing the behaviour was chosen and diagnosable. That row took less
  time than fixing it would have and left the design intact.
- **Every fix needs a test that fails without it.** Sixteen of wave 1's did; I
  check.
- ⚠ **Say what you could not run.** All three lanes said "no docker" and all
  three were right to. I run the lab pass.

## 1. `tmux` lane — a failure that reads as success, and the hire path

| # | finding | first lines to open |
|---|---|---|
| 17 | `paste_text` discards every tmux return code, so a failed paste reports a successful open — **both offices found this** | `tmux/ops.py:364-378`, `port/openers.py:68-82` |
| 18 | `list_windows` cannot distinguish "tmux failed" from "no windows" | `tmux/ops.py:56-60` |
| 23 | a hired agent's guide names no lead, and its trust is seeded into the wrong account | `tmux/ops.py:311-319`, `control/runner.py:70-76` |
| 24 | hiring an existing name cannot apply changed launch configuration | `control/openers.py:43-69`, `tmux/ops.py:337-348` |
| 25 | a third window-creation path still ignores `endpoint` | `tmuxhost/host.py:167-170`, `control/runner.py:56-68` |

⚠ **17 and 18 are one question**: what does this codebase do when tmux says no?
Answer it once. ⚠ **Row 18 has a trap** — `list_windows` returning an empty set
on failure is also what makes the reconcile loop safe. Read the callers before
changing the return type.

⚠ **23, 24 and 25 are the same defect three times:** the hire path is a second
implementation of window creation that keeps drifting from the boot path. The
useful fix may be to delete one of them rather than patch it a third time — say
which you think it is.

## 2. `api` lane — the error vocabulary

| # | finding | first lines to open |
|---|---|---|
| 19 | malformed WebSocket input kills the connection instead of producing an error frame | `session/app.py:168`, `:220` |
| 20 | an SSE stream that fails mid-flight cannot return its status code | `api/app.py:446`, `:490-492` |
| 21 | a Redis failure during a stream read is reported as `422`, and `API.md` tells clients not to retry `422` | `api/app.py:444-447`, `docs/API.md:677` |
| 22 | malformed `as` values can produce 5xx despite the documented 422 contract | `api/app.py:600-617`, `bus/roster.py:15-19` |

⚠ **These four are one contract.** 21 and 22 point in opposite directions — one
returns 422 for something that is not the client's fault, the other returns 5xx
for something that is. Decide what each class of failure returns, write it in
`API.md`, then make the code match. A per-row patch will leave the vocabulary
just as incoherent.

## 3. `bus` lane — a queue that outlives its agent, and the watchdog

| # | finding | first lines to open |
|---|---|---|
| 26 | a departed agent's egress is never drained, so re-hiring the name delivers it | `switch/service.py` |
| 27 | the credential check has no idea what an endpoint agent is — a local-model agent needs no vendor login and is reported as missing one | `watchdog/service.py:208-228` |
| 28 | a stalled agent whose window is gone is never reported | `watchdog/service.py:171-173`, `:90-91` |
| 29 | one failing maintenance job silently disables the other four, and the log record names only the exception class | `watchdog/service.py` |

⚠ **Row 26 may be deliberate** — wave 1 kept an api client's inbox for exactly
this reason (a re-enrolled name gets its mail). Decide whether an *agent's*
egress deserves the same treatment or the opposite, and say which.

⚠ **Row 27 is real and current:** this office runs agents on a local vLLM and an
ollama endpoint, and the watchdog reports them as needing a vendor login.

## 4. Done when

- every row confirmed or rejected in writing, with lines
- each confirmed row fixed, with a test that fails without the fix
- `python3 -m pytest -q` green — 320 at the time of writing
- ⚠ **the tenant still boots.** I run that pass; do not claim it.

## 5. Reporting

`jira done`, then message `architect` with the commit you worked from, the rows
you confirmed, the rows you rejected and why, and what you ran.

⚠ **Report on every row you were given, including the ones you did not do.**
Wave 1 had a lane report accurately on two rows and silently leave two others,
and only reading the branch showed it.
