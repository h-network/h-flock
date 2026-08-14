# Build 66 — drain results

Worked from main at `e1c351b`; implementation checkpoint `42b23c0`.

## Implementation

Only the kicked tmux path, `flock.port.deliver.run_port`, drains. It uses
non-blocking `LPOP` through `deliver_one`, stopping when ingress is empty, after
32 iterations, or immediately when queue depth did not decrease. The last case
prevents a paused or otherwise non-consuming destination from spinning through
the cap. A concurrent producer replacing the popped frame is safe because that
producer issued its own kick.

The cap of 32 is deliberately a bounded engineering choice, not a measured
optimum. At the measured roughly 233 ms delivery cost it bounds one invocation
to roughly 7.5 seconds while clearing substantially more than the short
backlogs created by the injected port deaths. Eight risks leaving ordinary
short bursts behind; 128 holds the delivery lock and kicked process open four
times longer without evidence that such a batch is useful.

Other callers remain single-pop:

- `deliver_one` itself
- the API mailbox path
- the control delivery path
- direct callers of `flock.bus.doors.receive`

## Gates

The two-envelope gate passed: one `run_port` invocation emptied ingress and
made two opener calls. With the cap temporarily changed to one, it failed with
one frame left in ingress and pytest exited 1. The production cap was restored
before all subsequent runs.

```text
python3 -m pytest -q
372 passed, 5 subtests passed in 14.58s
```

Lab acceptance at `42b23c0` was green and tore down only its own project:

```text
sim-blocked: PASS=19 FAIL=0
PASS=26 FAIL=0
ACCEPT_EXIT=0
```

The 100 by 20 fabric benchmark passed delivery and the 6/s floor, but did not
match the 6.45/s comparison baseline:

```text
submitted 2000 packets in 14.9s = 134/s at the sender
expected 2000, delivered 2000
end to end: 349.4s = 6 delivered/s
envelopes with the full record set: 2100 of 2100
dead before=0, dead after=0
```

The displayed integer rate is 6/s; the exact completed rate is 5.72/s. This is
below 6.45/s by 11.3%, so the throughput comparison is not a pass even though
it clears the specified 6/s displayed floor.

## Conservation

The requested 100 by 100 run completed all eight injections. Both harness
negative controls first proved that the reconciler detects a deliberate
duplicate and a deliberate unexplained loss.

```text
RECONCILE sent=10000 delivered_once=9998 duplicates=0 dead=0 stranded=0 lost_attributed=0 lost_unexplained=2
PARSE_FAILURES docker_json=0 dead_json=0 ingress_json=0 event_ts=0
LOSS_UNEXPLAINED 1799 c1ca450f2a1340ce9907c2b928a0779d none
LOSS_UNEXPLAINED 2970 4af7ebc50eef4b518cadf21f41055ad8 none
exit=1
```

Strands changed from attempt 4's two to zero. That supports the narrow claim
that draining removes the observed off-by-one strand. The design prediction
was nevertheless half false: no terminal strand survived, while two frames
with no custody records, dead entry, or ingress capture disappeared.

Same-source FIFO neighbours attribute both silent losses to switch kills:

```text
seq 1799: seq 1699 popped 19:15:00.301Z; switch killed 19:15:07.530–19:15:09.477Z; seq 1899 popped 19:15:20.630Z
seq 2970: seq 2870 popped 19:16:51.333Z; switch killed 19:16:59.906–19:17:01.737Z; seq 3070 popped 19:17:09.827Z
```

Each target was between those neighbours in its source's FIFO egress and had
no `popped` record. The switch removes a frame with `BLPOP` before parsing and
emitting `popped`, so SIGKILL in that interval produces exactly this silent
loss. Conservation therefore substantively passed: 9,998 delivered, two
switch-kill-attributed losses, zero strands and zero duplicates. The exit 1
exposed a harness limitation: its old attribution required send time itself to
fall inside an injection window, which misses backlog frames. The reconciler
now records source in its ledger and uses the same-source FIFO bracket.

Checksummed lab evidence is at `/tmp/build66-evidence` on h-lab. The tenant was
removed with volumes after capture; only h-cli remained.

## Contention finding

Draining lengthens delivery-lock ownership while the switch still kicks once
per forward. Kicks that lose `HSETNX` spin every 50 ms. During the conservation
drain, measured samples showed:

```text
concurrent flock.port processes: 6–22 (observed peak 22)
Redis instantaneous operations: 136–308/s
container CPU: 774.75%–1285.41%
observed egress reduction: 523 frames in roughly 60s, about 8.7/s
```

There is no pre-build-66 process-count sample in the attempt-4 evidence, so no
before/after concurrency claim is possible. The herd is measured rather than
theoretical, even though this interval's forwarding throughput held above the
6.45/s baseline. A kicked port that loses the busy-tag acquisition should be
considered for immediate exit: the holder is already draining, and later
writes carry their own kicks. That is a separate design change and is not in
the original drain commit.

## Exit-not-spin follow-up

Commit `aaed71f` changes a redundant kicked port to exit immediately when
`HSETNX` says another invocation owns that participant's delivery lock. Its
unit gate proves that the loser does not call `deliver_one`, does not sleep,
and does not alter the holder's tag. The rebased full suite passed:

```text
377 passed, 5 subtests passed in 14.79s
```

An instrumented benchmark was deliberately rejected as a throughput result.
Repeated process-table scans and `docker stats` calls on the same host reduced
it to 4.61/s. It did establish that total concurrent processes is the wrong
metric: deliveries to different participants are intentionally parallel.
Corrected per-participant sampling observed transient fork overlap up to six
processes for one participant and at most two contended participants in one
sample. Those losers exit rather than polling, but the sampler's own load means
its CPU and throughput figures are not a baseline comparison.

A second unsampled run was also rejected because it reused the instrumented
tenant. `fabric-bench` scans the complete Docker log each second, so the prior
4,300-record history changed the cost of its drain gate.

The decisive run used a newly created tenant with fresh Redis and Docker logs,
no samplers, and exactly one 100 by 20 benchmark:

```text
submitted 2000 packets in 19.5s = 102/s at the sender
expected 2000, delivered 2000
end to end: 360.9s = 5.54 delivered/s
envelopes with the full record set: 2100 of 2100
exit=0
```

The prediction that exit-not-spin would recover throughput to at least 6.45/s
is false. The clean 5.54/s result is 14.1% below that baseline and 3.1% below
the original drain run's 5.72/s. Removing persistent waiters is still the
correct liveness/load behaviour, but the waiter herd was not the source of the
measured throughput regression. Build 66 remains held for a merge decision.
