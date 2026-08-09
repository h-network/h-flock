# Build 20 — presence, and log records that reach the log

> Two things the system knows and cannot say: what an agent is doing right now,
> and what an agent's own tools did.
>
> **Base on `main`.** Branch `<lane>/build-20-<piece>`, push to origin.

---

# A. Presence — `bus` produces, `api` serves

## A1. What it is

**One sampled state per agent**, so an app can show "typing" and the watchdog can
later ask "stuck?" without either inventing its own observation.

⚠ **Sampled, never waited on.** A client polls; nothing holds a connection open
per agent. The economics were settled in build 18: sampling is one pass for the
tenant, waiting is one process per question.

## A2. The states — three, and no more

| state | means |
|---|---|
| `working` | activity within `PRESENCE_WORKING_SECONDS` (default 30) |
| `idle` | a feed exists, and nothing recent in it |
| `unknown` | **no feed at all** — agy, or a window running no CLI |

⚠ **`unknown` is not `idle`.** An agy agent and a bare shell produce no activity
ever, so calling them idle is a lie a client would render as "ready". Three
states, and the third one admits what we cannot see.

⚠ **Do not add `stuck`, `wedged` or `blocked`.** Those are judgements with
thresholds, they belong to the watchdog, and putting them here makes an app's
typing indicator inherit watchdog policy. Presence reports; it does not conclude.

## A3. Produced by the router, on the pass it already makes

After the activity tail, write per agent:

```
  <prefix>:agent:<name>:presence      HASH
  { "state": "working|idle|unknown", "since": "<ISO ts>", "last_activity": "<ISO ts|>" }
```

⚠ **`since` is when the state was entered, not when it was sampled.** A client
showing "working for 4 minutes" needs the former; a sample time tells it nothing
and changes every 2 seconds.

## A4. Served — `api`

Add to the existing `GET /agents/{agent}`, which already returns depths:

```json
{ "agent": "sme-2", "depths": {…},
  "presence": { "state": "working", "since": "…", "last_activity": "…" } }
```

⚠ **Extend the existing route; do not add `/presence`.** It is one small fact
about an agent and the route for facts about an agent exists. A client polling
for presence gets depths for free and makes one call, not two.

An agent with no presence yet reports `unknown` — never a missing key, never a
`404`.

---

# B. Log records that reach the log — `bus`

## B1. The problem, exactly

`office` runs **inside an agent's window**, so every `log_record` it makes goes to
that pane and nowhere else. Measured: an envelope sent by an agent produces
`popped`, `forwarded`, `received`, `opened` centrally — and **`sent` is missing**.

So `LLD-bus-and-router` §4's "four records across a delivered envelope's life" is
true for api-sent envelopes and false for agent-sent ones, which is most of them.

## B2. The fix is the pattern we already have twice

The board solved this by writing to a file the container collects, and the
activity feed by having the router tail a file. Do the same:

- `flock.bus.log_record`, when `FLOCK_LOG_FILE` is set, **also** appends the JSON
  line to that file. The entrypoint sets it for agent windows.
- the router **tails that file** into its own stdout, on the pass it already
  makes, with a byte offset like the activity tailer.

⚠ **Keep writing to stdout as well.** In a window that goes to the pane, which is
useful to the agent as its own confirmation — `TODO.md` is explicit that removing
it is the wrong fix.

⚠ **Never let logging fail a command.** Same rule as `record_task_event`: wrap
it, swallow everything.

⚠ **Do not deduplicate.** A record emitted by a container process reaches stdout
directly and is not in the file; one from a window is in the file only. If that
ever stops being true, dedupe is a decision with a reason, not a precaution.

## B3. Done when

- an agent running `office send` produces a `sent` record **in the container log**
- the same record still appears in that agent's pane
- `LLD-bus-and-router` §4's four-record claim is true for an agent-sent envelope —
  check it end to end and say so
- an unwritable log file does not break `office send`
- the router's pass is not measurably slower

---

## C. One line for the lead — `tmux`, small

`SPRINTS-next` §1 settled that **the lead is positional: the first agent in the
roster.** No variable, no configuration. What is missing is that nothing tells an
agent, so they treat every peer as having equal standing and nothing moves — one
said, correctly, *"frontend isn't my principal — you are."*

- **`office peers` marks the lead** — `architect (lead), backend, frontend`.
  Computed from the roster at call time, so it cannot go stale.
- **The guide gains one sentence**, near the top: the office has a lead, `office
  peers` shows who, and their direction is the office's direction.

⚠ **Do not name the lead in the guide text.** The guide is written to a file once,
at window creation; the roster changes. Put the *rule* in the guide and the
*name* in `peers`, which reads live.

⚠ **One sentence.** `TODO.md` is blunt about this: agents stop reading early, and
every paragraph added pushes something out of the part that gets read.

---

## Reporting

`jira done`, then message `architect` with paths, the exact shapes, and status.
⚠ For §B, report the **observed** four records for an agent-sent envelope, not
that the code looks right — that claim has been wrong once already.
