# Build 57 — there is no ICMP

> ⚠ **The figures below name no host, and the spread between our two is 130×**
> — identical scripts read **6.5/s on the 4-vCPU lab** and **853/s on h-oracle**.
> Read every `/s` here as this build's own evidence on an unrecorded host,
> **never as a capability**. `BUILD-CONVENTION` §3.0 is the rule that followed;
> [`DRIFT`](DRIFT.md) §4 is the finding.

> ⚠ **STILL PARKED, and NOT the watchdog's.** `DESIGN-layers` §8.1: three of the
> five failure modes here are detected by the switch or a port **at the moment
> they happen** — those notifications belong at the point of detection, not in a
> later observer. Only the strand and the non-consuming destination need the
> watchdog, because nothing else can see them.
>
> ⚠ **PARKED, not filed. Do not start this.** The gap is real and recorded, but
> building it now is feature work ahead of proof. **The framework has never been
> shown to hold under duration, scale or injected failure** — that comes first,
> in build 58. Revisit after.
>
> Base on `main` when it is unparked. Owner: `bus`.

## 1. The gap, verified

**Nothing reads the dead queue.** `agent:<name>:dead` has six `rpush` sites and
exactly one read — `llen`, for a depth counter in an API response
(`api/app.py:598`). An envelope that cannot be delivered goes into a list and
**the origin is never told.**

In networking a router that cannot deliver sends **ICMP Destination
Unreachable** back to the source. h-flock drops it in a bucket nobody empties.

⚠ **Build 53 fixed only the near half.** A non-local address now raises
`send_refused` **synchronously at the sending port**, so the agent sees it. But
everything that fails *after* the port hands off is silent:

| failure | where | does the origin learn? |
|---|---|---|
| non-local address | sending port | ✅ yes, synchronous, build 53 |
| destination not in roster | switch | ❌ **no** |
| malformed frame | switch | ❌ **no** |
| unknown `kind`, no opener | receiving port | ❌ **no** |
| opener raised | receiving port | ❌ **no** |

## 2. ⚠ The fix needs no new mechanism

**A dead letter is delivered back to the origin's port as a frame.** The origin's
port de-assembles it and delivers by `port_type` exactly as it would any other
frame — a paste into a tmux pane, a mailbox entry for an api client.

That is the model's own symmetry doing the work: *every hop is a port, and every
port both assembles and de-assembles* (`DESIGN-layers` §2.1a). **Do not build a
notification system.** If you find yourself adding one, the model is wrong and
that is a finding worth more than the build.

## 3. What to decide, and say which you chose

- **`kind`.** A returned failure is presumably `Undeliverable` — a new kind with
  an opener at the far edge. It carries the original `stream_id`, the reason,
  and where it stopped.
- **Loops.** ⚠ **An undeliverable notification that is itself undeliverable must
  not generate another one.** That is a broadcast storm with extra steps.
  Networking's answer is that ICMP errors do not trigger ICMP errors. State your
  rule.
- **Does the origin's own `dead` queue still get the original?** Probably yes —
  the queue is the record, the notification is the feedback. They are not
  alternatives.

## 4. ⚠ What this is NOT

Not delivery receipts, not acknowledgement, not at-least-once. **h-flock is
at-most-once with zero retries and that is deliberate and load-bearing.** This
build reports failures that already happen; it does not add reliability, and it
must not quietly become a retry mechanism.

## 5. Done when

- each row of §1's table that says ❌ produces a notification at the origin
- ⚠ **negative control per [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1**: send
  to a name that is not in the roster and prove the origin is told — then break
  the return path on purpose and prove a test goes red
- the loop rule is implemented and has a test that would catch a storm
- `python3 -m pytest -q` green (356 at the time of writing)
- `container/accept.sh` green; `fabric-bench` 100×20 at 2,000/2,000, ≥ 6/s,
  zero dead letters — ⚠ one tenant at a time, output to a lab-local file

## 6. Reporting

`jira done`, then message `architect` with the commit, the chosen `kind` and
loop rule, the negative-control proof, and the lab evidence.
