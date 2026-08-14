# Build 43 — natsflock: replace the transport, keep everything else

> ⚠ **A spike, not a migration.** It exists to answer one question with evidence,
> and it is allowed — expected, even — to end in "no".
>
> **Base on `natsflock`, NOT on `main`.** Branch `bus/natsflock-<piece>`, push to
> origin. ⚠ **Nothing from this build goes near `main`** until the numbers argue
> for it. `main` is at 339 tests with all 50 audit rows closed and a benchmark
> baseline; that is what a spike must not risk.

## 1. The question

The bus is a small re-implementation of what NATS does natively. The three
things next on the list — a `(producer, recipient)` ACL, per-client keys at the
door, and cross-tenant routing — are NATS features rather than code we should
write. **So the question is not "is NATS good", it is: does h-flock survive the
swap with its properties intact?**

⚠ **Timing is the point.** If the answer is yes, it must land *before* those
three are hand-rolled, because they are exactly the code that would be thrown
away. That is why this is being asked now rather than later.

## 2. What must not change

- **`office send -a bob …` is byte-identical from an agent's point of view.**
  If an agent can tell, the spike has already failed.
- **Adapters, openers, boards, presence, activity, the watchdog, both doors** —
  untouched. This is a transport swap behind a stable contract.
- **Redis stays** for the roster, boards, presence, activity and locks. Do not
  take the opportunity to move those too; one variable at a time.

## 3. What moves

| today | proposed |
|---|---|
| `pod:acme:tenant:hq:agent:bob:ingress` (list) | subject `flock.acme.hq.agent.bob` |
| broadcast fan-out by the switch | each agent also subscribes `flock.acme.hq.broadcast` |
| egress list + switch forwarding loop | publish; the server routes |
| port `BLPOP` when kicked | **JetStream durable consumer per agent** — the queue must survive while no port is running, which is the whole reason for JetStream rather than core NATS |

⚠ **Single node. No clustering.** The majority of open `nats-server` issues are
RAFT, quorum and recovery in clustered mode — a surface this project would never
enable. Do not enable it to "test properly".

## 4. The pass/fail criterion — decided now, before anyone starts

**The five-record trace must survive.** `popped`, `forwarded`, `received`,
`opened`, joinable by `stream_id`, for a delivered unicast envelope.

⚠ **This is the strongest debugging property the project has** and it found two
defects last night that fifty audit rows and three lane test-runs missed. If it
degrades into generic broker metrics, **the spike says no** — we would have
traded our best diagnostic for someone else's clustering code.

⚠ **Publishing direct removes the switch's vantage point.** Today one process
sees every envelope. Say plainly where the records come from afterwards: the
edges, JetStream metadata, or a thin observer kept for the purpose. "We would
add that later" is not an answer.

## 5. Evidence required

Baselines from `main`, measured last night — reproduce them, do not invent new
ones:

- **integrity**: `container/scenarios/` + the log audit — 1,285 envelopes,
  `popped/forwarded/received/opened` complete for 1,283, zero dead-letters
- **the harness**: `bash container/accept.sh` — plumbing 25/25, simulator 19/19
- **the load**: four agents on the local provider for at least 30 minutes, then
  the same integrity audit

⚠ **Report the raw output.** A verdict without the numbers is not a result.

## 6. Two decisions to make deliberately, not inherit

1. **At-most-once is a choice, not an accident.** `LLD-bus-and-switch` records
   zero retries as load-bearing: retrying a destructive pop whose reply was lost
   can deliver an envelope twice. JetStream defaults to at-least-once with acks.
   Acking on receipt approximates today's behaviour — **choose it explicitly and
   write down why**.
2. **Audit row 6 may disappear.** The codex auditor found a loss window between
   the destructive pop and the `popped` record, and we recorded it as
   irreducible "without a reserve/ack journal or a different queue primitive".
   JetStream *is* that primitive. If the swap closes it, say so — that is a
   point in NATS's favour and belongs in the report.

## 7. What would make this a "no"

Say so plainly if any of these hold, and stop:

- the five-record trace cannot be reconstructed without a bespoke observer that
  is as much code as the bus it replaced
- the port's kick-and-exit lifecycle cannot map onto a durable consumer
  without becoming a daemon — **an office of idle agents must still cost nothing**
- `nats-py` being asyncio-first forces the switch or port into a rewrite
  rather than an adaptation
- two substrates end up worse than one: Redis for state, NATS for transport,
  and no clear seam between them

## 8. Reporting

`jira done`, then message `architect` with the commit you worked from, what
moved, the raw evidence from §5, your answers to §6, and a plain recommendation.

⚠ **"No" is a successful outcome.** So is "yes, but not until X". The failure
mode for this build is a half-migration that nobody wants to throw away.
