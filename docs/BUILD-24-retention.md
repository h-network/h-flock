# Build 24 — caps, so nothing grows forever

> **Base on `main`.** Branch `bus/build-24-retention`, push to origin.

## 1. What actually grows

Streams are already capped at `MAXLEN ~ 1000` — mailbox, activity,
`pending.verify`. What is not:

| | grows with | |
|---|---|---|
| `tasks.done` | every finished ticket | LIST |
| `dead` | every undeliverable envelope | LIST |
| `window.log.jsonl` | every log record from a window | file |
| `tasks.jsonl` | every board action | file |

⚠ **Caps, not clocks.** A count needs no correct time, no timezone, and no
sweeper process. "Keep the last N" is checkable by looking; "keep 30 days" needs
someone to trust a clock and something to run on a schedule.

## 2. The two lists — trimmed by the router, on the pass it already makes

`LTRIM key -N -1` per agent, alongside the activity tail and the presence sample.

```
  BOARD_DONE_MAX    default 500
  DEAD_MAX          default 500
```

⚠ **Trim in the router, not at every writer.** `dead` is written by the router
*and* the adapter; `tasks.done` by `office done` and `office cancel`. Four call
sites that must all remember a cap is how the cap gets forgotten — the same
shape as the `StopAgent` key list. One pass, one place.

⚠ **`LTRIM` keeps the newest.** The oldest finished tickets and oldest
dead-letters go first, which is the right end to lose: a dead-letter matters when
it is fresh, and nobody audits a board's hundredth-oldest ticket.

## 3. `window.log.jsonl` is a spool, not an archive

The router tails it and re-emits to stdout, so **everything in it has already
been copied somewhere durable**. It needs no history at all.

Cap by size: when it exceeds `WINDOW_LOG_MAX_BYTES` (default 8 MB) **and the
router has consumed to the end**, truncate it and reset the offset to 0.

⚠ **Only truncate when the offset has reached the end.** Otherwise you discard
records the router has not forwarded, which is a silent loss of exactly the thing
this file exists to prevent — `sent` records that reach nowhere else.

⚠ **Agents append to it concurrently**, so a record can land between the check
and the truncate. Accept that; it is one record at an 8 MB boundary. Do not build
locking for it, and do not pretend it cannot happen — log the truncation with the
byte count so the gap is visible if anyone ever chases one.

## 4. `tasks.jsonl` is left alone, deliberately

One line per board action, and board actions are human-paced. It is the board's
only history and the cheapest thing here to keep.

⚠ **If it ever needs a cap, it needs rotation instead** — it is an archive, not a
spool, and truncating it loses the beginning, which is the part you would want.

## 5. Done when

- a board with 600 finished tickets keeps the newest 500
- a `dead` queue past the cap keeps the newest
- `window.log.jsonl` past the cap is truncated **only** with the offset at the
  end, and the truncation is logged with the byte count
- an agent's records still reach stdout across a truncation — check one lands
  after it
- `tasks.jsonl` is untouched
- the three caps are env-overridable with the documented defaults, and appear in
  `CONTRACTS` beside the other settings

## 6. Reporting

`jira done`, then message `architect` with the settings, defaults, and status.
⚠ Report the **truncation case observed** — write past the cap, then confirm a
later record still reaches the log.
