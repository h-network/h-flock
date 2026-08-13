# Build 48 — RESP one-shot client results

Worked from main commit `9ae6dd519dc67e2e8baa7d38ceff13c09d739cfd`.
Implementation commit `e218987` is pushed on `bus/build-48-resp-client`.

## Verdict

**Not complete: the absolute latency gate failed.** The dependency removal
improved both the measured command and the end-to-end fabric, but `office
peers` and a real `flock.adapter` delivery did not measure under 200 ms on the
released lab host. The other acceptance criteria passed.

## Implementation

`flock.bus.resp.Redis` is a one-connection RESP2 client using only `socket`.
Bulk and array values remain bytes, matching redis-py without
`decode_responses`; nil bulk and nil array replies become `None`; integer
replies remain integers; Redis error replies raise `ResponseError`.

The specified command surface is implemented. Two additional commands were
required by the actual one-shot call graph: `SET` and `HSET`. The adapter
delivers control envelopes, and `flock.control.openers` uses both to write
launch, profile, endpoint, pause, and roster desired state. Omitting them would
make lifecycle acceptance fail even though they were absent from the spec's
inventory.

URL handling supports percent-decoded passwords, non-default ports, and Redis
database selection. `BLPOP` remains `BLPOP`.

## Unit and acceptance evidence

```text
345 passed, 5 subtests passed in 14.02s
```

```text
sim-blocked: PASS=19 FAIL=0
PASS=25 FAIL=0
passed: install, health, plumbing, simulator, console reachable
```

## Timing evidence

All measurements were made on h-lab with no other h-flock tenant running;
`h-cli` remained as operator-approved background load.

Main, measured as host wall time including the same `docker exec` boundary:

```text
office_peers_before_ms=1518.4,1340.1,2194.7,1543.0,1720.2
adapter_before_ms=2751.8
```

Branch, same host-side boundary:

```text
office_peers_after_docker_ms=1296.3,1447.3,1123.7,1421.3,2105.9
```

That boundary is dominated by Docker/host scheduling, so the command itself
was also measured from a persistent Python parent inside the same container.
After the benchmark settled:

```text
office_after_ms=381.5
adapter_after_ms=807.0 rc=0
```

Earlier five-sample branch office measurements were also above the gate:

```text
office_peers_after_inner_ms=248.8,455.6,548.8,274.4,377.0
```

The before median of 1543.0 ms versus the later after observation of 381.5 ms
is a material reduction, but neither program satisfies the specified under-200
ms criterion. This report does not convert the ratio into a pass.

## Fabric benchmark

The isolated requested shape passed delivery and exceeded the 2.64/s main
baseline:

```text
fabric-bench: 100 stations x 20 rounds on h-flock-bus-lab-tenant-1
  roster now holds 104 participants
  submitted 2000 packets in 7.3s  =  275/s at the sender
  expected 2000, delivered 2000
  end to end: 332.6s  =  6 delivered/s
  redis memory: 1740 KiB -> 2631 KiB
  retired 100 stations
```

Strict parsing from the benchmark start onward:

```text
bench_json_lines=8552 parse_failures=0 total_lines=8701
{'received': 2111, 'opened': 2111, 'popped': 2110, 'sent': 110, 'forwarded': 2110}
```

There were zero dead letters during the benchmark interval. One earlier
`dead_lettered` record in the same container was from an intentionally invalid
manual timing fixture at 12:15:37; the benchmark began after 12:19.
