# LLD — watchdog

**Status:** built and running. One `flock.watchdog` process runs per tenant.

The watchdog observes conditions that merit human attention. It does not decide
why an agent is quiet, repair an agent, or participate in envelope delivery.
Those limits are part of the design: an observation must not change the state it
is trying to describe.

## 1. Process boundary

The entrypoint starts the watchdog beside the router. It is a separate process
with its own cadence and failure boundary:

```
Redis board, presence and blocked state ─┐
tmux window-activity metadata ───────────┼─> flock.watchdog ─> alerts Stream
CLI credential files ───────────────────┘                    └> container log
```

The router is the tenant's data path. Watchdog policy, external observations or
a slow tmux call must not delay forwarding, so none of this work runs in the
router's pass. The watchdog imports shared bus and tmux library functions, but
it neither receives nor sends envelopes.

Each ordinary pass:

1. reads roster fields and keeps participants whose VAB is `tmux`;
2. obtains all window activity timestamps with one tmux `list-windows` call;
3. evaluates ticket stalls; and
4. reports retained `blocked` verdicts.

Credential accounts are checked at most once an hour within the same process.
An exception aborts only the current pass, writes a lifecycle error to stdout,
and leaves the process running for the next pass.

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

## 3. `blocked`: a retained delivery verdict

The router, not the watchdog, owns:

```
<prefix>:agent:<name>:blocked    HASH    { since, stream_id }
```

After the verification delay, the router writes this key on the first delivery
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

The limit is history, not a special terminal screen. The router judges only an
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
state explicitly with `office status`. The watchdog sends no envelope to the
lead or to any other agent.

That restriction prevents the observation from clearing its own symptom. If a
lead agent were automatically told that a peer had an old ticket and a quiet
window, its natural response would be to message the peer. The paste itself
creates window activity and may create an input event, resetting the evidence
without fixing the underlying condition. It would also turn a false positive
into an automated interruption. A human can read the factual record and decide
whether intervention is warranted; the watchdog cannot.

Alert records are facts, not diagnoses. Their common fields are `v`, `ts` and
`kind`; the remaining fields are specific to `stalled`, `blocked`, or
`credential` as shown in this document.

## 5. Credential warnings

Once an hour, the watchdog walks the default CLI accounts and discovered
profile directories under `/home/ubuntu`.

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
past is not a warning about the future.
Missing or malformed Claude and agy credential files produce no expiry claim.
An expiry beyond the warning window produces no alert.

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

`REDIS_URL`, `POD` and `TENANT` identify the tenant. `TMUX_SESSION` defaults to
the tenant name; `TMUX_SOCKET` selects an explicit tmux socket when present.

## 7. Invariants

1. The watchdog is observation, never part of routing or custody.
2. It reports and never repairs.
3. A fully checked stall needs old work, no current model activity, and a quiet
   window together; unavailable activity is disclosed in `unchecked`.
4. The router is the sole writer of `blocked`; the watchdog never derives or
   clears that state.
5. `blocked` is a limited delivery-verification verdict, not a diagnosis.
6. Alerts go to the Redis Stream and container log for humans, never into an
   agent's ingress queue.
7. No terminal content is captured or parsed.
