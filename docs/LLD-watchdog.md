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
`Message`), pushes it directly onto the lead's `ingress` list, and kicks
`flock.port <lead>` itself — the same two steps the switch performs after
popping a normal envelope from egress. The rendering the lead sees
(`message_opener`, the `[message from watchdog]` wrapper, delivery
verification markers) is identical to any other message; only the egress hop
is skipped, because nothing was ever going to consume it.

If the tenant has no lead (`<prefix>:lead` unset), or the lead is not a `tmux`
participant, the check is silently skipped — there is nowhere to deliver a
pane message to.

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
| agy | never marked |

The limit is history, not a special terminal screen. The switch judges only an
agent that has previously produced an activity offset or feed. A new agent's
first delivery is dropped unjudged even if the agent is unable to consume it;
the watchdog therefore has no `blocked` verdict to report. Bare shells and agy
are not verified at all, so they cannot become `blocked`.

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

⚠ **§2a is the one exception, and it is to the lead only.** HLD §8c
works out why the lead does not re-create the symptom-clearing problem above:
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
   **the watchdog is now the sole writer**, at `watchdog/verification.py:104`
   (clear) and `:108` (set). The switch never touches it. Found by `api`
   reviewing build 77 — the move updated eight docs for the file *paths* and
   missed the sentence about *ownership*.
5. `blocked` is a limited delivery-verification verdict, not a diagnosis.
6. ⚠ **AMENDED — §2a is one exception.** Every `stalled`, `blocked` and
   `credential` alert still goes only to the Redis Stream and container log,
   never into any agent's ingress queue. §2a's doing-duration message is the
   single exception, and it is narrower than "an agent's ingress queue" in
   general: it is addressed only to whichever participant is currently the
   tenant's `lead` (HLD §8c), never to the agent the ticket names, and never to
   any other peer. If there is no lead, or the lead is not `tmux`, §2a sends
   nothing rather than falling back to any other participant.
7. No terminal content is captured or parsed.
