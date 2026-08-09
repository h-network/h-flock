# Build 19 — verify: did the delivery land?

> The adapter logs `opened` and everyone believes the message arrived. Sometimes
> it did not, and nothing anywhere records that.
>
> **Base on `main`.** Branch `<lane>/build-19-verify`, push to origin.

## 1. Measure first. Do not re-deliver

**This build reports and stops.** No retry, no re-paste, no dead-lettering.

⚠ **We do not know the failure rate.** h-office added its verify step after
measuring roughly one delivery in ten going astray; we have measured nothing.
Retrying on an unmeasured signal risks sending everything twice to fix a problem
that may be rare — and a duplicate message is not obviously better than a missing
one. Get the number, then decide.

## 2. The signal

A message that lands **starts a CLI turn**, which the CLI records in its own
session file — so it appears in the activity feed as `kind: input`.

| what happened | `input` event |
|---|---|
| delivered, agent begins the turn | **yes** |
| swallowed by an open modal | no |
| pasted but `Enter` not taken, sitting in the input box | no |
| delivered to an agent with no activity feed (agy) | no — see §5 |

⚠ **This reads no terminal.** That is the whole reason it waited for build 18.
An earlier sketch of verify grepped the pane for the text it had just pasted;
this looks at a data file the CLI writes itself, and survives every version bump.

## 3. Two halves

**`tmux` — mark the delivery.** After a successful paste, record that one
happened:

```
  <prefix>:agent:<name>:pending_verify     STREAM, XADD, MAXLEN ~ 100
  { "stream_id": "…", "ts": "…" }
```

⚠ **Only for a `Message` or `Command` paste into a tmux window.** `AddTicket`
pastes nothing and cannot be verified this way; an api client's mailbox write
needs no verification at all.

⚠ **Never fail a delivery because the marker could not be written.** Same rule as
`record_task_event`: wrap it, swallow it. Verification is an observation, not a
step in delivery.

**`bus` — check, on the router's existing pass.** For each marker older than
`VERIFY_AFTER_SECONDS` (default 10):

- an activity entry with `kind: input` and `ts` **after** the marker's `ts`
  → **verified**. Drop the marker.
- otherwise → **unverified**. Drop the marker, emit a log record.

```
  {"module":"router","event":"delivery_unverified","stream_id":"…","recipient":"…","waited":10}
```

⚠ **No new process.** The router already polls for activity every
`ACTIVITY_POLL_SECONDS`; this is a second thing done in the same pass.

## 4. The honest caveat: busy agents

An agent already mid-turn will not start a new one, so **`input` may not appear
for minutes** even though the message landed perfectly and is queued in the input
box — which is exactly the behaviour we rely on.

⚠ **So `unverified` means "not confirmed", never "lost".** Word the log record
that way, and expect false positives from busy agents. Getting that rate is half
the point of measuring.

If distinguishing them turns out to matter, the material is already there: an
agent producing *other* activity was busy, one producing none was not. **Do not
build that classification now** — collect first, and let the numbers say whether
it is worth it.

## 5. agy cannot be verified

No session file, no activity feed, no `input` event — so every agy delivery would
read `unverified`, forever.

⚠ **Do not mark deliveries to an agent with no activity feed.** A permanent false
alarm trains people to ignore the real ones, which is the exact failure the
watchdog design spends its length avoiding. Skip it and say so in the docs.

## 6. Done when

- a normal delivery to an idle claude or codex agent is **verified**
- a delivery into an open modal is **unverified**, with a log record naming the
  `stream_id` and the recipient
- an agy delivery produces **no marker at all**
- a marker that cannot be written does not fail the delivery
- markers do not accumulate — every one is dropped after it is judged
- the router's pass is not measurably slower
- `TODO.md` records the false-positive question as open, pending numbers

## 7. Reporting

`jira done`, then message `architect` with the key, the marker shape, the log
record, and status. ⚠ Report the **observed rate** if you can get one — a handful
of deliveries with the verdicts is worth more than the code review.
