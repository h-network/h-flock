# Build 63 — Redis persistence, and why the obvious answer is wrong

> **Base on `main`.** Branch `api/build-63-persistence`, push to origin.
> Owner: `api`. ⚠ Touches `container/` (`tmux`'s) — told.
> ⚠ **§2 is a recommendation, not a decision. Read §4 before building.**

## 1. The problem, with today's evidence

Redis runs with `appendonly no` and an empty `save` — **nothing survives a
restart.** Measured cost, twice in one day:

- the office container was restarted after `accept.sh` destroyed it: **all three
  lanes lost their boards**, 154 completed tickets between them, and tickets in
  `doing` vanished mid-build
- a second restart later did it again

⚠ **The recovery cost is not the tickets.** It is that lanes went idle waiting
for someone to notice, and I re-filed work from memory rather than from a record.

## 2. ⚠ The obvious fix is wrong, and this is the point of the build

"Turn on AOF" would also persist the **queues** — and that is a hazard, not a
feature:

`DESIGN-layers` §7 records the coupling: build 53's frame is a **hard v2** that
rejects flat v1, and **that is free today only because a restart leaves no
envelopes to reject.** Persist the queues and every future wire change needs a
dual-read window, forever.

**So separate durable state from transport state:**

| | survives a restart? | why |
|---|---|---|
| board — `todo`/`doing`/`hold`/`done` | ✅ **yes** | it is a work record; losing it costs real time |
| streams — messages, activity, alerts | ✅ probably | history someone reads |
| **queues — `egress`, `ingress`** | ❌ **no** | in-flight transport. At-most-once **permits** loss, and a stale envelope from an old wire version is worse than a lost one |
| dead letters | ⚠ **decide and say why** | a record of failure, or debris? |
| roster | ❌ no | already derived from `.env` at every container start |

**Recommended shape:** enable AOF, and **purge transport keys at boot** in
`entrypoint.sh` before anything starts consuming. Durable boards, empty queues,
and the hard-v2 property preserved.

## 3. ⚠ What this must not do

- **Not change delivery guarantees.** At-most-once with zero retries is
  deliberate. Persisting queues would edge toward at-least-once **by accident**,
  which is the worst way to acquire a guarantee
- **Not make the tenant slower.** Measure `fabric-bench` before and after;
  `appendfsync everysec` should be invisible, but **measure rather than assume** —
  the loopback Redis here is already 25× slower than a healthy one
- **Not persist across a version change.** If the boot purge fails, a stale
  envelope reaches a switch that will reject it. State what happens then

## 4. ⚠ Open for the operator — do not decide this alone

**Is the board the only thing that must survive?** I have proposed yes, plus
streams. If h-flock is ever expected to resume in-flight work across a restart,
that is a different product with different guarantees, and it changes this build
completely. **Ask before building if §2's split looks wrong to you.**

## 5. Done when

- the split in §2 is implemented, or a different one is agreed and implemented
- ⚠ **negative control** per [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1:
  restart a tenant with work on a board and envelopes in queues, and show the
  **board intact and the queues empty**. Then break the purge deliberately and
  show a stale envelope is detected rather than silently forwarded
- `fabric-bench` 100×20 before and after: 2,000/2,000, **≥ 6/s**, same container,
  same run
- `container/accept.sh` green; `python3 -m pytest -q` green (367 at the time of
  writing)

## 6. Reporting

`jira done`, then message `architect` with: the split implemented, the
before/after throughput, the negative-control proof, and what you decided about
dead letters and why.
