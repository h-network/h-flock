# Build 68 results — bound ingress and expose the pop

Worked from main at ebbf0d4. Implementation checkpoints are afe442d and
806c8a5 on bus/build-68-bound-and-see.

## Result

The ingress bound fixed build 67 fault A for the reason predicted: once the
queue reached the bound, the switch dead-lettered instead of forwarding, and
therefore issued no kick and spawned no port. The extended post-bound CPU
sample fell to a 5.96% median and 34.55% peak, versus build 67's 1084.93%
median and 1366.48% peak.

The first 100x20 fabric benchmark delivered all 2,000 frames with zero dead
letters at 5.91/s. That result is inconclusive on cost: main-only runs on the
same lab that day ranged from 6.00 to 6.45/s, so comparing the branch with the
best historical run does not distinguish a regression from host variance. A
paired main/branch run remains pending.

## Bound and horizon

INGRESS_MAX defaults to 300 frames and is environment-overridable. At build
67's measured rate of about 10 forwards/s, that is a 30-second horizon. At
366.56 bytes per measured frame it retains about 110 KiB per full ingress.
The number is deliberately a short failure horizon, not a memory ceiling: the
measured unbounded queue needed 82.3 hours to reach 1 GiB.

Fault A sent 500 frames to a paused destination:

- popped: 500
- forwarded and kick_started: 300 each
- dead_lettered for full ingress: 200
- final destination ingress depth: 300
- final source dead depth: 200
- pre-bound CPU: median 890.99%, peak 1167.27% over 15 samples
- immediate post-bound CPU: median 195.75% over 2 samples
- extended post-bound CPU: median 5.96%, peak 34.55% over 10 samples

The build 67 harness returned 3 because its old gate requires all 500 frames
to remain in ingress. Its own metrics showed ingress 300; the return is the
expected negative result for that pre-bound assertion, not a framework
failure.

## Popped visibility and its residual

The switch records popped immediately after BLPOP returns and after deriving
the source from the popped queue, before structural frame validation. It
extracts only string-valued record metadata from the unvalidated JSON. A
malformed frame is recorded with stream_id unknown and is not joinable to a
normal custody set; its source egress, pop time, failure reason, raw dead-list
value and dead-list location remain knowable.

The invisible window is smaller, not closed. SIGKILL can still land after
BLPOP removes the frame and before the complete stdout write. Making that
transition atomic would require a processing-list pattern such as BLMOVE,
which changes the delivery guarantee toward at-least-once and is deliberately
outside this build.

## Negative controls

With the over-bound condition temporarily disabled, the bound test retained
three frames instead of two and exited 1. Restoring it left two in ingress,
put the rejected raw frame in the source dead list, emitted dead_lettered, and
issued no kick. A send whose resulting depth equalled the bound still emitted
forwarded and kick_started.

With the early popped call temporarily removed, a validator that inspected
the captured records saw no popped event and the test exited 1. Restoring the
call made that same validator observe popped before it raised EnvelopeError.

## Other verification

- PYTHONPATH=src:. pytest -q: 379 passed, 5 subtests passed
- accept.sh: exit 0; PASS=26 FAIL=0; sim-blocked PASS=19 FAIL=0
- teardown removed only h-flock-bus68; docker ps then showed only h-cli

