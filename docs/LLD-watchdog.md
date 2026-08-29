# LLD — watchdog

**Status:** built and running. One `flock.watchdog` process runs per tenant.

The watchdog observes conditions that merit human attention. It does not decide
why an agent is quiet, repair an agent, or participate in envelope delivery.
Those limits are part of the design: an observation must not change the state it
is trying to describe.

## 1. Process boundary

The entrypoint starts the watchdog beside the switch. It is a separate process
with its own cadence and failure boundary:

```
Redis board, presence and blocked state ─┐
tmux window-activity metadata ───────────┼─> flock.watchdog ─> alerts Stream
CLI credential files ───────────────────┘                    └> container log
```

The switch is the tenant's data path. Watchdog policy, external observations or
a slow tmux call must not delay forwarding, so none of this work runs in the
switch's pass. The watchdog imports shared bus and tmux library functions, but
it neither receives nor sends envelopes.

Each ordinary pass:

1. reads roster fields and keeps participants whose port_type is `tmux`;
2. obtains all window activity timestamps with one tmux `list-windows` call;
3. evaluates ticket stalls; and
4. reports retained `blocked` verdicts.

Credential accounts are checked at most once an hour within the same process.
The window lookup, stall check, blocked check and credential check have separate
failure boundaries. One failing job writes a lifecycle error to stdout with the
job name and both exception class and message; independent jobs still run in the
same pass, and the process continues.

## 2. Stall rule: three signals together

A `stalled` alert requires all three available observations:

| signal | condition | what it establishes |
|---|---|---|
| board | the first `tasks.doing` ticket has a valid `started_ts` at least `WATCHDOG_STALL_SEC` old | the agent took work and has not marked it done |
| presence | state is not `working` | there is no current model-level activity |
| window | the window's last activity is at least `WATCHDOG_SILENCE_SEC` old | the terminal is not producing output |

Any one alone is noise:

- Ticket age cannot distinguish a legitimate long build from a failure.
- Presence can become idle during one long-running tool call: the tool event was
  recorded once, then no further model event arrives.
- A quiet window is normal while an agent thinks, waits without a ticket, or is
  simply idle.

The conjunction covers those ordinary cases. In particular, a long tool call
may have old presence while its continuing terminal output suppresses the
alert. A `working` presence likewise suppresses an alert even when the ticket is
old and the window is quiet.

A missing window is not treated as a reason to suppress an otherwise qualifying
stall. It is a stronger factual observation than silence: the alert carries
`"window_missing": true` and `"no_output_s": null`. It still requires an old
ticket and presence that is not `working`; a missing idle window with no work is
not an alert.

Some CLIs do not expose activity. Missing or `unknown` presence does not make up
a false value: the watchdog may alert when the board and window conditions hold,
sets `no_activity_s` to `null`, and names `"activity"` in `unchecked`. The
record therefore states which part of the rule could not be confirmed.

The watchdog does not label an agent "stuck" or "wedged". It reports only the
measurements:

```json
{"v":1,"ts":"…","kind":"stalled","agent":"sme-2",
 "ticket":"review the auth change","doing_age_s":840,
 "no_activity_s":540,"no_output_s":420,"unchecked":[]}
```

The ticket must have a non-empty `id`. After an alert, the watchdog stores that
id at `<prefix>:agent:<name>:alerted` with the cooldown TTL. The same ticket is
not reported again while that key remains; a different ticket can be.

## 2a. Doing-duration: a direct, board-only alert to the lead

A second, independent rule, added after §2 was already shipping: any agent's
first `tasks.doing` ticket whose `started_ts` is at least `WATCHDOG_DOING_ALERT_SEC`
old (default `900`, 15 minutes) is reported **directly to the tenant's lead**,
regardless of presence or window state. It is evaluated every ordinary pass,
alongside and independently of §2 and §3 — the same ticket can produce both a
`stalled` record on the alerts stream and a doing-duration message to the lead.

⚠ **Board-only is deliberate, not an oversight.** §2's three-signal rule exists
so the *passive* alerts stream does not cry wolf at an ordinary long build — a
human reading it later needs it to mean something. This rule is not passive: it
is a message that lands in front of the one person whose job is to weigh it, so
the bar is lower on purpose. A human, not a heuristic, decides whether 15
minutes on this ticket is normal.

The message is delivered as plain text, not the alerts stream:

```
[alert from watchdog] <agent> has been working on "<ticket title>" for <N> min, request an update
```

`<N>` is `doing_age_s // 60`. The pane also carries the ordinary `[message from
watchdog]` wrapper every delivery gets (§4) — the `[alert from watchdog]`
tag inside the text is what marks it as this rule's output rather than a peer
message, since the outer wrapper is identical for both.

**Re-alerts once per threshold crossing, not once per poll and not only once.**
`doing_age_s // WATCHDOG_DOING_ALERT_SEC` gives a crossing number (1 at 15m, 2
at 30m, …); the watchdog stores `<ticket_id>:<crossing>` at
`<prefix>:agent:<name>:doing.alerted` and only sends again once the current
crossing exceeds the stored one. A ticket open for hours keeps nudging the
lead at each 15-minute mark; a ticket still in the same 15-minute window does
not repeat every `WATCHDOG_INTERVAL`. A different ticket id resets the count.
This is a separate key from `alerted` (§2), which cools down the `stalled`
alert on a fixed TTL instead — the two rules do not share state.

**Delivery bypasses the switch's forwarding hop, not the envelope format.** The
watchdog is not a roster member (§1) and has no egress queue for the switch to
poll, so `office send`'s normal path — write to the sender's own egress,
let the switch forward it — has nothing to drain it. The watchdog instead
builds the same v4 envelope `office send` would (source `watchdog`, kind
`Message`), admits it onto the lead's `ingress` list, and kicks
`flock.port <lead>` itself — the same two steps the switch performs after
popping a normal envelope from egress. The rendering the lead sees
(`message_opener`, the `[message from watchdog]` wrapper, delivery
verification markers) is identical to any other message; only the egress hop
is skipped, because nothing was ever going to consume it.

⚠ **The ingress write goes through `flock.bus.queues.admit_ingress`, the same
atomic bound the switch uses for every other forward — not a plain `rpush`.**
Before this, a lead whose port stopped draining ingress had no depth cap on
how many watchdog nags kept accumulating there: the one unbounded write into a
participant's ingress in an otherwise `INGRESS_MAX`-bounded system. Both
processes read `INGRESS_MAX` themselves and pass it explicitly — the primitive
takes no ambient configuration (`CONTRACTS.md`, `flock.bus.queues`). A full
queue logs `lead_alert_capacity` and drops the alert; a Redis/`eval` exception
logs `lead_alert_unknown` instead of treating it as a confirmed rejection,
since the write may have committed before the error — mirroring `send_unknown`
and `forward_unknown` elsewhere in the bus. Neither outcome is retried, and
neither is a dead-letter: these are best-effort nags, not durable envelopes
anyone is owed, and the board or `unreplied` state that triggered the nag is
untouched either way, so it simply re-fires on its own next threshold crossing
once the lead's port recovers.

If the tenant has no lead (`<prefix>:lead` unset), or the lead is not a `tmux`
participant, the check is silently skipped — there is nowhere to deliver a
pane message to.

## 2b. Todo-duration: the same alert for a ticket nobody has taken yet

Second rule in the family, same shape as §2a: any ticket in an agent's
`tasks.todo` whose `created_ts` is at least `WATCHDOG_TODO_ALERT_SEC` old
(default `300`, 5 minutes) is reported to the lead the same way — direct pane
message, not the alerts stream, board-only trigger.

⚠ **Presence-independent for a different reason than §2a's.** §2a's ticket is
already `doing`, so an agent could be `working`, `idle` or silent and the rule
still cares only about the board. Here there is no work in progress to have a
presence opinion about at all: the agent may be perfectly healthy and simply
not have looked at its board yet. That is exactly the condition this rule
exists to surface, so presence was never going to be part of it.

```
[alert from watchdog] <agent> has an unpicked ticket "<ticket title>" waiting <N> min
```

`<N>` is `todo_age_s // 60`.

**State is a HASH, not a STRING, because `todo` is not a one-ticket slot.**
`tasks.doing` holds at most one entry, so `doing.alerted` (§2a) can be a single
`<ticket_id>:<crossing>` string. `tasks.todo` can hold several tickets at once,
and each independently ages — so `<prefix>:agent:<name>:todo.alerted` is a HASH
keyed by ticket id, each field holding the last crossing number sent for that
id. A ticket taken, cancelled or deleted leaves the board; the next pass
diffs the hash's fields against the ids still present in `todo` and drops
whatever no longer matches, so the hash does not grow with tickets that will
never be evaluated again.

Delivery reuses the exact mechanism §2a introduced (`_notify_lead`): same
envelope build, same direct write to the lead's `ingress`, same
`flock.port <lead>` kick, same silent no-op when there is no `tmux` lead.

## 2c. Hold-duration: the same alert for a ticket parked too long

Third rule in the family, same shape as §2b: any ticket in an agent's
`tasks.hold` whose `held_ts` is at least `WATCHDOG_HOLD_ALERT_SEC` old
(default `3600`, 60 minutes) is reported to the lead — direct pane message,
board-only trigger, presence-independent for the same reason as §2b: a held
ticket has no work in progress to have a presence opinion about.

⚠ **The threshold is an hour, not minutes, on purpose.** `hold` is often a
deliberate, legitimate wait on something external — it is not itself a
problem the way an unpicked `todo` ticket or a stalled `doing` ticket is. The
rule is not "nag whenever something is parked"; it is "force a decision once a
park has gone on long enough to stop looking like a wait and start looking
like abandonment." A ticket that genuinely needs to stay parked past that
point is a signal the ticket itself is wrong, not that the alert should keep
tolerating it — the right response is usually `cancel` or `delete`, not
silence.

```
[alert from watchdog] <agent> has had "<ticket title>" on hold for <N> min
```

`<N>` is `hold_age_s // 60`.

**`held_ts` falls back to `created_ts` when absent**, the same fallback
`office list`'s own `_ticket_age` uses (`office/cli.py`) — a ticket held by an
older client, or before `held_ts` existed, has nothing else to measure age
from. Using `created_ts` there is an approximation (it also counts time spent
in `todo`/`doing` before the hold), not a precise hold duration, but it is
closer to the truth than refusing to report at all.

**State is a HASH, keyed by ticket id, same reasoning as `todo.alerted`**:
`tasks.hold` is not a one-ticket slot either, so
`<prefix>:agent:<name>:hold.alerted` tracks each held ticket's crossing count
independently and drops entries for tickets that leave `hold` (resumed,
cancelled or deleted), the same pruning §2b's `todo.alerted` does.

Delivery reuses `_notify_lead` unchanged — same envelope, same direct
`ingress` write, same kick, same silent no-op with no `tmux` lead.

## 2d. Unreplied-duration: a client message nobody answered

Fourth in the family, and the one member whose trigger is not the board.
Any tmux agent that has `bus.send` open an `unreplied` entry (below) and left
it open past `WATCHDOG_UNREPLIED_ALERT_SEC` (default `60`, one minute) is
reported to the lead the same way as §2a-c: direct pane message, board-only
delivery mechanism reused unchanged, not the alerts stream.

```
<prefix>:agent:<name>:unreplied    HASH    { <client>: {"count", "since"} }
```

**Written by `send()` itself, not by the watchdog.** Both directions of a
client conversation pass through the same door (`flock.bus.doors.send`): a
telegram-bot POST to `/agents/<agent>/envelopes` with `as: telegram` calls it
exactly as `office send` does, just with `source` and `destination` swapped.
`send` reads both port types itself, via two roster lookups — ⚠ not a reuse
of `require_allowed`'s work, which checks policy export/import tags and
never touches port_type (corrected after `bus`'s module-boundary sweep;
LLD-bus-and-switch §1 carries the same correction). Reading it directly
rather than asking a caller to declare "this needs a reply":

- `api` port_type → `tmux` port_type, kind `Message` or `Attachment`: opens or
  extends the destination agent's `unreplied` field for that client. `count`
  increments; `since` is kept at the *first* unanswered message's timestamp,
  not overwritten by each new one.
- `tmux` port_type → `api` port_type, any envelope kind: deletes the source
  agent's `unreplied` field for that destination client outright. Any reply
  closes the whole backlog, not one message at a time.
- `tmux` → `tmux` traffic never touches this key. Ticket age already covers
  peer responsiveness through §2a-c; this rule exists only for the one
  direction those three cannot see — an agent owing a human on the other end
  of a client, not another agent.

```
[alert from watchdog] <agent> has <count> unanswered message(s) from <client>, oldest <N> min old
```

`<N>` is `age_s // 60`, where `age_s` is measured from `since`, so it reflects
the oldest unanswered message, not the most recent.

⚠ **Re-alerts back off exponentially, unlike §2a-c's fixed period.** Those
three re-alert at a fixed multiple of their threshold because their
thresholds are already long (5-60 minutes) — a fixed period there is not
frequent enough to spam. A client reply is different: it deserves a fast
*first* nag, and 60 seconds is short enough that a fixed re-alert period at
that cadence would page the lead once a minute for the entire length of any
genuinely long task, which optimizes for the wrong failure mode. Instead
`<prefix>:agent:<name>:unreplied.alerted` stores the threshold that was just
used per client, and the next required age is double it: 60s, 120s, 240s,
480s, ... A message still unanswered a minute in surfaces within that
minute; a five-minute task produces two nags on the way, not five.

**A client the agent has since answered leaves `unreplied` entirely** (the
whole field, not decremented) — the next pass diffs `unreplied.alerted`'s
fields against what is still present and drops what no longer matches, same
pruning §2b and §2c already do for tickets that leave `todo`/`hold`.

## 3. `blocked`: a retained delivery verdict

The switch, not the watchdog, owns:

```
<prefix>:agent:<name>:blocked    HASH    { since, stream_id }
```

After the verification delay, the switch writes this key on the first delivery
it judges unverified. A later verified delivery deletes it. The first `since`
is retained so duration means how long the condition has existed, not how
recently it was noticed.

`blocked` means exactly: **a delivery was judged unverified and no verified
delivery has been observed since**. It does not mean that the agent is stuck,
and it is not proof that the CLI acted on or understood anything. The watchdog
only reads the verdict, reports its age, and may include it in a stall alert.

### Measured limits

The deterministic lab run established the boundary:

| state | observed result |
|---|---|
| healthy new Claude with no activity history | delivery unjudged; not blocked |
| non-consuming pane with prior activity history | blocked |
| credential-free Codex at its login prompt, with prior activity | blocked |
| credential-free Claude at its login prompt, with prior activity | blocked |
| bare shell | never marked |
| agy | never marked *(row is from the original lab run; see the correction below)* |

The limit is history, not a special terminal screen. The switch judges only an
agent that has previously produced an activity offset or feed. A new agent's
first delivery is dropped unjudged even if the agent is unable to consume it;
the watchdog therefore has no `blocked` verdict to report. Bare shells are not
verified at all, so they cannot become `blocked`.

⚠ **CORRECTED 2026-08-27 — agy is no longer in that set.** The lab run above
predates `~/.gemini/antigravity-cli/history.jsonl` being wired into
`ActivityTailer` (`watchdog/activity.py`'s `_agy_events`, same fix as HLD §8's
correction). `VERIFIABLE_CLIS` in `port/openers.py` now includes `agy`, so a
delivery to an agy agent with prior activity history is marked and judged
exactly like claude/codex: **verified** if a later `input` line for that
agent's `workspace` follows the marker, **blocked** if none does before the
verification delay elapses. Confirmed live against `_input_times()` reading a
real agy agent's activity stream, not re-run in the lab — the underlying
mechanism is CLI-agnostic and was never agy-specific.

No screen is scraped to fill that limit. Measurement showed that a consumed
message remains visible in terminal scrollback, making it indistinguishable
from pending input without CLI-specific rendering knowledge. That approach
marked a healthy agent blocked and was removed.

A standalone blocked alert is emitted once per `(agent, since, stream_id)` per
watchdog process:

```json
{"v":1,"ts":"…","kind":"blocked","agent":"sme-2",
 "since":"…","stream_id":"…","unconsumed_s":420}
```

This deduplication is in memory. A process restart may report a still-current
blocked identity again, which is preferable to silently losing it.

## 4. Human alerts, never agent messages

Every alert is appended as compact JSON in the single `alert` field of the
tenant Redis Stream:

```
<prefix>:alerts    STREAM    MAXLEN ~ 1000
```

The identical JSON is printed as one line to the container log. Humans receive
it through `GET /alerts` or `GET /alerts/stream`; an agent can inspect current
state explicitly with `office status`. The watchdog sends no envelope to a peer
agent.

That restriction prevents the observation from clearing its own symptom. If an
ordinary agent were automatically told that a peer had an old ticket and a
quiet window, its natural response would be to message the peer. The paste
itself creates window activity and may create an input event, resetting the
evidence without fixing the underlying condition. It would also turn a false
positive into an automated interruption. A human can read the factual record
and decide whether intervention is warranted; the watchdog cannot.

Alert records are facts, not diagnoses. Their common fields are `v`, `ts` and
`kind`; the remaining fields are specific to `stalled`, `blocked`, or
`credential` as shown in this document.

⚠ **§2a-d are the exception, and it is to the lead only.** All
four share one delivery mechanism (`_notify_lead`) and the same scope. HLD
§8c works out
why the lead does not re-create the symptom-clearing problem above:
the lead is the one participant in this fabric that a human's own judgment is
meant to reach through, per HLD §8c's "why there is a lead at all" — a title
is what makes an agent take direction rather than negotiate it, but it is also
the one address in the roster where a human is expected to actually be
reading. Messaging the lead is not messaging an agent in the sense this
section means; it is the closest thing this fabric has to messaging the human
running it. No other participant gets this treatment, and this section's
restriction is otherwise unchanged.

## 5. Credential warnings

Once an hour, the watchdog walks the `tmux` roster and reads each enrolled
agent's `provider`, `launch` and `profile` keys. An agent with a provider name
is skipped because it talks directly to the tenant's configured model server and
uses no vendor account credential. For the remaining agents, the watchdog checks
each distinct CLI account in use once; an unused profile directory is not
evidence of a running account and is ignored. If an account ceases to require a
credential because every user moved to providers, its stale
`credential.alerted` field is cleared.

⚠ **A Claude account backed by `CLAUDE_OAUTH_TOKEN_<ACCOUNT>` is skipped
entirely, not read as `absent`.** `tmux.ops` injects that environment value
straight into the matching window as `CLAUDE_CODE_OAUTH_TOKEN`, so no
`.credentials.json` is ever written and none is expected — reading the file
would report a healthy account as missing. **Known limit:** the watchdog has
no way to tell an expired or revoked token from a live one here; catching that
would need a remote authentication probe, not a file read, and none exists.

| CLI | source | interpretation |
|---|---|---|
| Claude | `claudeAiOauth.refreshTokenExpiresAt` | alert when within the warning window |
| agy | — | **unknown**: `token.expiry` is the *access* token |
| Codex | no expiry in its credential file | report `unknown`, never infer `fine` |

The Claude refresh-token expiry is used, not its short-lived access token.

⚠ **Only Claude records a refresh expiry.** agy's `token.expiry` tracks its
*access* token — measured: the same file read hours apart showed the value moving
forward while the login stayed valid, because the CLI refreshes it itself. It
produced a real alert on the lab tenant saying *"expiring"* about a timestamp
already in the past, for an account that was working. **agy is `unknown`, like
codex.** Two of three cannot be checked, and saying so is the honest answer.

⚠ **`expired` and `expiring` are different words.** A timestamp already in the
past is not a warning about the future. A missing, unreadable or malformed
credential file for any CLI is `absent`: regardless of expiry support, that
account cannot work without a human login. An expiry beyond the warning window produces no alert on fresh startup.

The tenant `credential.alerted` hash stores the last reported status under an
`<account>:<cli>` field. A status is emitted once when it changes:
- When a credential fails or enters a warning state, its non-healthy status (`absent`, `expiring`, `expired`, `unknown`) is emitted and recorded in `credential.alerted`.
- When a previously alerted credential recovers or is refreshed to healthy (`present`), the watchdog emits a retraction record with `status: "present"` to the alert stream and deletes its field from `credential.alerted`. A steady-state healthy account emits nothing on subsequent passes.
- If an account is no longer in use, its stale `credential.alerted` field is cleared.

Per `BUILD-38-durable` §2, emitting `status: "present"` was chosen over §1's cursor-based clearable alerts because clearable alerts do not exist in the append-only stream. Emitting `status: "present"` enables stream consumers and console monitors to determine the current state by taking the latest record per `(account, cli)`.

The existing per-agent `alerted` key cannot hold this state: it contains a ticket ID, expires
with the stall cooldown, and one credential account may be shared by several
agents.

```json
{"v":1,"ts":"…","kind":"credential","account":"work",
 "cli":"claude","status":"expiring","expires_ts":"…"}
```

## 6. Configuration

| variable | default | purpose |
|---|---:|---|
| `WATCHDOG_ENABLED` | `1` | `0` makes the process exit cleanly |
| `WATCHDOG_INTERVAL` | `30` | seconds between ordinary passes |
| `WATCHDOG_STALL_SEC` | `600` | minimum age of a doing ticket |
| `WATCHDOG_SILENCE_SEC` | `300` | minimum window-output silence |
| `WATCHDOG_COOLDOWN_SEC` | `3600` | per-ticket stall-alert cooldown |
| `WATCHDOG_CREDENTIAL_WARN_DAYS` | `7` | refresh-token warning horizon |
| `WATCHDOG_DOING_ALERT_SEC` | `900` | age at which §2a messages the lead directly, and the re-alert period thereafter |
| `WATCHDOG_TODO_ALERT_SEC` | `300` | age at which §2b messages the lead directly, and the re-alert period thereafter |
| `WATCHDOG_HOLD_ALERT_SEC` | `3600` | age at which §2c messages the lead directly, and the re-alert period thereafter |
| `WATCHDOG_UNREPLIED_ALERT_SEC` | `60` | age at which §2d first messages the lead directly; each re-alert doubles this as the next required age |
| `INGRESS_MAX` | `300` | bound `_notify_lead` passes to `admit_ingress` for the lead's ingress list — the switch's own variable (`LLD-bus-and-switch`), read here too so both processes honor the same cap without a shared config source |

`REDIS_URL`, `POD` and `TENANT` identify the tenant. `TMUX_SESSION` defaults to
the tenant name; `TMUX_SOCKET` selects an explicit tmux socket when present.

## 7. Invariants

1. The watchdog is observation, never part of routing or custody.
2. It reports and never repairs.
3. A fully checked stall needs old work, no current model activity, and a quiet
   window together; unavailable activity is disclosed in `unchecked`, while a
   known-missing window is reported explicitly.
4. ⚠ **CORRECTED 2026-08-19.** This read *"the switch is the sole writer of
   `blocked`; the watchdog never derives or clears that state."* That inverted
   when `DeliveryVerifier` moved from `flock/switch/` to `flock/watchdog/`:
   **the watchdog is now the sole writer**, at `watchdog/verification.py:120`
   (clear) and `:123` (set). The switch never touches it. Found by `api`
   reviewing build 77 — the move updated eight docs for the file *paths* and
   missed the sentence about *ownership*.
5. `blocked` is a limited delivery-verification verdict, not a diagnosis.
6. ⚠ **AMENDED — §2a, §2b, §2c and §2d are the exception.** Every `stalled`,
   `blocked` and `credential` alert still goes only to the Redis Stream and
   container log, never into any agent's ingress queue. §2a's doing-duration,
   §2b's todo-duration, §2c's hold-duration and §2d's unreplied-duration
   messages are the exception, and it is narrower than "an agent's ingress
   queue" in general: all four are addressed only to whichever participant is
   currently the tenant's `lead` (HLD §8c), never to the agent the ticket or
   message names, and never to any other peer. If there is no lead, or the
   lead is not `tmux`, none of the four fall back to any other participant —
   they send nothing.
7. No terminal content is captured or parsed.
