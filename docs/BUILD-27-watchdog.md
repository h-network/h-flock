# Build 27 — the watchdog

> Design is [`SPRINTS-next.md`](SPRINTS-next.md) §3, written before any of its
> signals existed. They all exist now.
>
> **Base on `main`.** Branch `<lane>/build-27-watchdog`, push to origin.
> `bus` builds the watchdog and the alerts stream; `api` serves the two routes.

## 1. Its own process

`flock.watchdog`, one per tenant, started by the entrypoint beside the router.

⚠ **Not a step in the router's pass**, unlike the activity tail, presence and
retention. Those are bounded Redis and file reads. The watchdog reads panes, and
**the router is the data path** — a `capture-pane` that hangs would stall
forwarding for the whole tenant. Position matters more than cost here (HLD
invariant 7).

⚠ **It reports and never repairs.** No re-pressing `Enter`, no re-pasting, no
`StopAgent`. If something needs doing, that is an envelope sent by whoever read
the report.

## 2. What it reads

| signal | source | says |
|---|---|---|
| `doing` age | the board's `started_ts` | took work, has not finished |
| presence | `<prefix>:agent:<n>:presence` | model-level activity, or none |
| window silence | `list-windows -F #{window_activity}` | terminal-level output, or none |
| credential expiry | the CLIs' own credential files | a login is running out |

⚠ **Presence and window silence are not the same signal**, and this is the whole
reason h-office's version works. Presence is model-level: an agent running a
twenty-minute `Bash` produces one `tool` event and then nothing, so presence
reads `idle` while it is plainly working. The window is still printing.
**A long build keeps printing; a wedged agent does not.**

⚠ **One `list-windows -F` covers the tenant.** Do not capture panes to get this.

## 3. When it speaks

**All three, together**, or it says nothing:

```
  a ticket in `doing` older than WATCHDOG_STALL_SEC     (default 600)
  AND presence is not `working`
  AND the window has been quiet for WATCHDOG_SILENCE_SEC (default 300)
```

⚠ **Any one of them alone is noise.** Elapsed time alone fires identically for a
fifteen-minute rebuild and a wedged agent — h-office measured exactly this, and
the lead learned to dismiss it and then dismissed a real one. That failure is the
thing to design against, not stalls.

## 4. Once per ticket, not once per pass

An alert every `WATCHDOG_INTERVAL` for the same ticket is how a signal becomes
wallpaper.

```
  <prefix>:agent:<name>:alerted     STRING, the ticket id, TTL WATCHDOG_COOLDOWN_SEC (default 3600)
```

⚠ Add `alerted` to the per-agent resource set from build 22, or the classification
test will fail — which is exactly what it is for.

## 5. Who it tells — a human, not an agent

```
  <prefix>:alerts        STREAM, MAXLEN ~ 1000      the record, with a cursor
  GET /alerts            ?after=<cursor>&limit=     catch-up
  GET /alerts/stream     SSE                        live
  the container log      one line each
```

⚠ **No envelope to the lead. No envelope to anyone.** The rule "reports, never
repairs" constrains the watchdog and says nothing about what happens next — and
what happens next, if an agent is told, is an LLM with `office` on its PATH
deciding to help. The system would repair; it would just do it through a proxy
with no accountability.

⚠ **The alert would clear its own symptom.** Told *"sme-2 stalled, window silent
7m"*, a lead messages sme-2 to ask. That paste produces window activity and an
`input` event. Silence resets, presence flips to `working`, the condition
evaporates — **and nothing was fixed.** We would have built a machine that
reliably converts a stall into a hidden stall.

⚠ **And a false positive would become an action.** The three-signal rule exists
because a long `Bash` looks identical to a wedge. A human reading that waits and
looks; an agent interrupts an agent that was working fine.

The lead already has the pull half: `office status`, and a guide telling it to
check before assigning and to hold work rather than fix. **Push goes to a person;
pull belongs to the lead.**

⚠ Notifying an agent later is a separate decision with its own answer to "and
then what?" — much easier to make once alerts exist and someone has read a few.

### What an alert says

Facts, then stop:

```json
{"v":1,"ts":"…","kind":"stalled","agent":"sme-2",
 "ticket":"review the auth change","doing_age_s":840,
 "no_activity_s":540,"no_output_s":420,"unchecked":[]}
```

⚠ **Do not classify why.** Not "stuck", not "wedged", not "probably waiting on
approval". Every *why* is a guess from outside, and a wrong one costs more than
the alert is worth.

⚠ **`unchecked` is not decoration.** An agy agent has no activity feed, so one of
the three signals is missing and the alert must say which. An alert that quietly
omits what it could not see is how a signal stops being trusted.

## 6. Credentials expiring — a slower, separate check

Once an hour is plenty. Per **account**, not per agent (`seed-home.sh check` now
does the same walk — reuse the shape).

- claude: `claudeAiOauth.refreshTokenExpiresAt`
- agy: `token.expiry`
- codex: **nothing recorded** — report `unknown`, never `fine`

⚠ **The refresh token, never the access token.** claude's access token expires
within hours and refreshes silently; alerting on it fires constantly and
correctly, which is the cry-wolf failure again. Warn at
`WATCHDOG_CREDENTIAL_WARN_DAYS` (default 7) before the *refresh* token expires.

## 7. `blocked` — superseded by build 28

⚠ **This section proposed finding `blocked` by scraping a pane, and it does not
work.** Measured on the lab tenant: a consumed message stays visible in the
transcript, so a whole-screen match for `[message from ` marks a *healthy* agent
blocked. Separating transcript from input box needs to know where a CLI renders
its input region — the render knowledge the whole design refuses.

Bottom-N lines separates the common case and fails on a wrapped message whose
prefix scrolls above the window. Cursor-row-only fails the same way.

→ [`BUILD-28-blocked.md`](BUILD-28-blocked.md) does it with no screen at all: the
router already judges every delivery and throws the verdict away. Retaining it
*is* "we delivered and it was not consumed".

**Do not build the scrape.** If build 28 fails on its own terms we will come back
knowing exactly why, which is worth more than guessing now.

## 8. Settings

```
  WATCHDOG_INTERVAL              30
  WATCHDOG_STALL_SEC             600
  WATCHDOG_SILENCE_SEC           300
  WATCHDOG_COOLDOWN_SEC          3600
  WATCHDOG_CREDENTIAL_WARN_DAYS  7
  WATCHDOG_ENABLED               1
```

⚠ `WATCHDOG_ENABLED=0` must stop the process cleanly, not leave it looping. A
watchdog nobody trusts gets turned off, and it should be turnable off.

## 9. Done when

- a stalled ticket with a silent window and no activity produces **one** alert on
  the stream, and **no envelope to any agent**
- the same ticket does not alert again within the cooldown
- an agent working a long `Bash` — silent presence, printing window — produces
  **no** alert
- an agy agent's alert says which signal was unavailable
- `GET /alerts` returns it with a cursor; `/alerts/stream` delivers one live
- a `blocked` agent is reported by `office status` without the watchdog writing
  anything else
- a credential within the warning window produces an alert naming the account
- codex reports `unknown` rather than `fine`
- an unsubmitted `[message from …]` in a pane appears in the alert
- `WATCHDOG_ENABLED=0` exits cleanly
- the router is untouched

## 10. Reporting

`jira done`, then message `architect` with the settings, the alert wording, and
status. ⚠ Report a **real alert** produced against the lab tenant — a stalled
ticket you created deliberately — not a unit test's version of one.
