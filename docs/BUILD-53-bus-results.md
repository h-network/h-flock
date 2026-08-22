# Build 53 bus results

> ⚠ **The figures below name no host, and the spread between our two is 130×**
> — identical scripts read **6.5/s on the 4-vCPU lab** and **853/s on h-oracle**.
> Read every `/s` here as this build's own evidence on an unrecorded host,
> **never as a capability**. `BUILD-CONVENTION` §3.0 is the rule that followed;
> [`DRIFT`](DRIFT.md) §4 is the finding.

Tested commit `2412423` on `bus/build-53-frame`, after merging main at
`5b0efb3`.

## Compatibility decision

This is a **hard v2 Redis wire change**. Flat v1 envelopes are rejected rather
than upgraded. All repository mailbox consumers were changed in this build.
HTTP send bodies keep their existing shape because they are port input, not
Redis wire frames.

The implementation needed no switch, tags, filtering, L4, or second pod.

## Falsifiability

The permanent test gives L2 and L3 contradictory destinations and requires the
local switch to follow L2. With the production L2 line it passed. I then changed
the decision to `envelope["l3"]["destination"]` on purpose. The test failed:

```text
FAILED tests/test_bus.py::DoorsAndRouterTest::test_router_forwards_on_l2_without_reading_l3_destination
1 failed in 0.04s
negative_control_exit=1
```

The production L2 line was restored before the full run.

## Component benchmark

Prediction before measuring: frame assembly and storage would increase because
both layered headers are retained; L2 lookup would be effectively flat because
both paths still pay one Redis membership query. The lab run used 1,000
interleaved A/B iterations and medians:

```text
assemble_iterations=1000
flat_assemble_median_us=14.03
frame_assemble_median_us=39.96
flat_json_bytes=229
frame_json_bytes=306
flat_redis_delta_2000_bytes=495856
frame_redis_delta_2000_bytes=618648
roster=10 flat_decision_median_us=644.29 l2_decision_median_us=632.33
roster=100 flat_decision_median_us=795.85 l2_decision_median_us=791.47
roster=1000 flat_decision_median_us=961.16 l2_decision_median_us=954.57
```

The frame adds 77 JSON bytes in this fixture and 122,792 bytes across 2,000
Redis list values. Assembly adds 25.93 microseconds at the median. The L2
decision did not regress at any measured roster size.

## Address and custody gates

The suite proves bare `bob` and qualified-local `acme:hq:bob` produce identical
L2 and each produces the complete `sent`, `popped`, `forwarded`, `received`,
`opened` record sequence under one stream ID.

A live non-local send failed before writing egress and emitted its refusal:

```text
{"ts":"2026-08-13T18:45:26.398Z","module":"bus","event":"send_refused","source":"architect","destination":"acme:sales:bob","reason":"no route to non-local destination 'acme:sales:bob'"}
raised=no route to non-local destination 'acme:sales:bob'
egress_before=0 egress_after=0
```

## Regression gates

```text
356 passed, 5 subtests passed
sim-blocked: PASS=19 FAIL=0
PASS=25 FAIL=0
accept_exit=0
```

The lab-local `fabric-bench` result:

```text
submitted 2000 packets in 7.7s  =  258/s at the sender
expected 2000, delivered 2000
end to end: 353.9s  =  6 delivered/s
redis memory: 1929 KiB -> 2818 KiB
dead_before=0 dead_after=0 dead_delta=0
```

The one `dead_lettered` log record was the acceptance suite's deliberately
malformed stream-id fixture at 18:33:09, before benchmark submission. No dead
list entry remained before or after the benchmark.
