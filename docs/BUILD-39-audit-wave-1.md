# Build 39 — audit remediation, wave 1

> `docs/AUDIT.md` section 1 only: the crashes, the data loss and the silently
> wrong behaviour. Sections 2–6 follow in later waves, after this one is
> verified on the lab.
>
> **Base on `main`.** Branch `<lane>/build-39-<piece>`, push to origin.

## 0. How to work a row — this part is not optional

**Confirm before fixing.** Every row cites the lines its auditor read. Open
them. Decide whether the finding is real *at the current commit*.

⚠ **Rejecting a row is a success, not a failure.** Two of these came from
models that could not run the code, and a previous auditor on this project cited
files that did not exist. If a row is wrong, say why with the same precision the
finding claimed, and it gets closed.

⚠ **"Deliberate, not broken" is also an outcome.** If the behaviour was chosen,
say so and point at where it was decided. Then fix the *documentation* instead,
if the doc is what misleads.

**Each fix needs a test that fails before it.** Not a test that passes after —
one that would have caught this. Say in your report which test that is.

## 1. `tmux` lane

| # | finding | first lines to open |
|---|---|---|
| 1 ✅ | `.append()` on the `set` from `list_windows` — the `__init__` path raises | `tmuxhost/host.py:201`, `tmux/ops.py:56` |
| 2 ✅ | `REDIS_PASSWORD` reaches every agent window and is never unset | `container/entrypoint.sh:108-114`, `:232`, and `:27` for the pattern to copy |
| 5 | two codex agents without profiles share one session directory, so activity is attributed to the wrong agent | `switch/activity.py:86`, `tmux/ops.py:236-240` |
| 16 | an port that cannot get the busy tag spins forever | `port/runner.py:161-168`, `bus/resources.py:45` |

⚠ **Row 2 is the one I would not leave sitting.** It undoes the isolation claim
the moment anyone sets a Redis password — and the fix pattern already exists
four lines away, where `API_TOKEN` is unset for exactly this reason.

⚠ **Row 1 is verified and one character of intent** — but ask *why the path was
never exercised*, because that is the more useful answer.

## 2. `bus` lane

| # | finding | first lines to open |
|---|---|---|
| 3 | `StopAgent` destroys an api client's unread mailbox; docs promise retention | `bus/resources.py:13` |
| 4 | retiring `host` deletes the control endpoint, and the empty roster then spins the switch against Redis — one chain | `bus/keys.py:8`, `control/openers.py:16`, `switch/service.py:38-40` |
| 6 | destructive `BLPOP` before `popped` is emitted — an envelope can vanish unrecorded | `switch/service.py:45`, `:48`, `:52-67` |
| 14 | the activity tailer restarts from byte 0 when the newest session file changes | `switch/activity.py` |
| 15 | one undecodable byte in the window-log spool re-emits forever and never truncates | `switch/windowlog.py` |

⚠ **Row 6 is the interesting one.** At-most-once is deliberate (`AUDIT.md` 44:
zero connection retries is load-bearing). The question is not "make it
at-least-once" — it is whether the *loss window* can be made visible. Do not
change the delivery guarantee to close this row.

## 3. `api` lane

| # | finding | first lines to open |
|---|---|---|
| 7 | the session door never recovers from a broken tmux stream, though the LLD says it does | `session/app.py:135`, `session/control.py:252-253` |
| 8 | one oversized `%output` line kills the reader permanently | `session/control.py:220`, `:71-76` |
| 9 | non-ASCII terminal output is corrupted | `session/control.py:193-203`, `session/app.py:159-164` |
| 10 | a slow viewer grows the session process without bound — **found by both offices** | `session/control.py:40-45`, `session/app.py:159-167` |
| 11 | the SSE endpoints do blocking Redis I/O on the event loop | `api/app.py:516`, `:659`, `:443` |
| 12 | one malformed roster row makes `/board` return `404` for the whole tenant | `api/app.py:705-712`, `bus/roster.py:6-8` |
| 13 | the pane→agent map assumes one pane per window; duplicate names merge terminals — **both offices** | `session/control.py:128-139`, `:185-203` |

⚠ **Rows 8, 9 and 13 are all the same reader.** Read them together before
changing anything — a fix for one that ignores the others will be rewritten.

## 4. Done when

- every row is **confirmed or rejected in writing**, with lines
- each confirmed row is fixed, with a test that fails without the fix
- `python3 -m pytest -q` green (303 at the time of writing)
- ⚠ **the tenant still boots.** Build 36 shipped a guard that proved itself and
  broke every container, because nobody started a tenant the ordinary way
  afterwards. I will run the lab pass; do not report done without saying whether
  you could run anything yourself

## 5. Reporting

`jira done`, then message `architect` with **the commit you worked from**, the
row numbers you confirmed, the row numbers you rejected and why, and what you
ran. ⚠ **If you cannot run docker in your lane, say so** — that answer has been
the right one twice this week.
