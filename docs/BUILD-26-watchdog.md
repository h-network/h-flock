# Build 26 — the watchdog

> Design is [`SPRINTS-next.md`](SPRINTS-next.md) §3, written before any of its
> signals existed. They all exist now.
>
> **Base on `main`.** Branch `bus/build-26-watchdog`, push to origin.

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

## 5. Who it tells, and how

An envelope to the **lead**, read from `<prefix>:lead`. Through the bus like
anything else.

The message states facts and stops:

```
[watchdog] sme-2 took "review the auth change" 14m ago, has not finished it,
has produced no model activity for 9m and no terminal output for 7m.
```

⚠ **Do not classify why.** Not "stuck", not "wedged", not "probably waiting on
approval". Every attempt to say *why* is a guess made from outside, and a wrong
one costs more than the alert is worth. Report what is true and let a person
look.

⚠ **Say what could not be checked.** An agy agent has no activity feed, so
presence is `unknown` and one of the three signals is missing. The alert must say
so rather than implying three-signal confidence. Same for a bare shell.

⚠ **No lead, no alert.** If `<prefix>:lead` is unset, log it and stay quiet
rather than picking someone.

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

## 7. `blocked` — the one thing the screen is read for

**`blocked` means: we delivered, and it was not consumed.** One condition.

```
  <prefix>:agent:<name>:blocked    watchdog only    { since, stream_id }
```

⚠ **Do not match failures. Check the expectation.** Matching means enumerating —
trust dialog, login prompt, feedback survey, model picker, approval prompt, and
whatever the next release adds, per CLI, per version. That is the swamp we
refused to build. Checking that what we expected actually happened is one rule
that never grows.

The expectation is already ours: after a delivery there should be an `input`
event, and our `[message from …]` should **not** still be sitting in the pane.

⚠ **Look only for a string we wrote.** `[message from ` and nothing else. Never a
prompt, a footer, a spinner or a dialog title. If this ever needs to know what a
CLI renders, it has become the thing we refused to build.

⚠ **This covers every failure at once** — trust dialog, login, survey, modal,
wedged process — because in all of them our own text sits unconsumed, and we
never need to know which.

⚠ **Only learnable after sending**, so an agent broken before anyone messages it
reads `idle`. That is correct rather than a gap: the harm exists only when work
is being sent, and that is when we find out.

### Why it is not a presence state

Presence is written by the router from files, every couple of seconds. `blocked`
is written by the watchdog from a screen. **One writer per key** — two writers on
one key has silently overwritten things twice already (the window environment,
and the guide's lead sentence). `office status` and the api merge them and report
`blocked` when set, because it is the more consequential fact.

⚠ **It clears only when a later delivery is consumed**, never on a timer. A stale
`blocked` holds work, which is safe. A stale `working` sends work into a hole,
which is not.

## 7b. Where it is used

⚠ **Not in the delivery path.** The adapter does not check it and must not — that
is invariant 7, and it would put a screen-derived value in front of every
message.

It is for the **lead's routing decision**: `office status` reports it, and the
lead's guide says an agent that is `blocked` will not receive work, so hold it
and say so rather than trying to fix the agent.

This is the only place in the system permitted to read a pane, because it is
observation and out-of-band (HLD invariant 7).

**One job:** an agent that is alerting on the three signals **and** has our
`[message from …]` text visible in its input box is a message that was never
submitted. Say so in the alert — it is directly actionable, and it is the one
failure a human fixes in a second.

⚠ **Look only for our own marker.** `[message from ` and nothing else. No modal
detection, no prompt parsing, no state inference from chrome. The moment this
grows a per-CLI pattern it has become the thing we refused to build.

⚠ **Only when already alerting.** Not on every pass, not for healthy agents.

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

- a stalled ticket with a silent window and no activity produces **one** alert to
  the lead
- the same ticket does not alert again within the cooldown
- an agent working a long `Bash` — silent presence, printing window — produces
  **no** alert
- an agy agent's alert says which signal was unavailable
- an unset lead produces a log line and no alert
- a credential within the warning window produces an alert naming the account
- codex reports `unknown` rather than `fine`
- an unsubmitted `[message from …]` in a pane appears in the alert
- `WATCHDOG_ENABLED=0` exits cleanly
- the router is untouched

## 10. Reporting

`jira done`, then message `architect` with the settings, the alert wording, and
status. ⚠ Report a **real alert** produced against the lab tenant — a stalled
ticket you created deliberately — not a unit test's version of one.
