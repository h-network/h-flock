# Build 42 — bus lab results

Worked from 6c1f476b8ecb379351621b49a18ff9596e1e71eb on the lab tenant
bus-lab, published only on 8100 and 8101. Lab SSH answered and the tenant ran in
the lane-owned clone at /home/h-lab/bus-h-flock.

## Ranked findings

### 1. Critical — ordinary docker restart loses Redis-backed tenant state

Confirmed twice with container/scenarios/bus-graceful-restart.sh. Immediately
before each restart, Redis returned both a unique string sentinel and an
untouched ingress list of depth one. The same container returned healthy after
docker restart, but both keys were absent. This falsifies custody, retained
queue, board and roster durability across an ordinary restart; the observation
is broader than the two fixture keys because both unrelated Redis data types
disappeared.

Reproduce twice on a disposable tenant:

    CONTAINER=h-flock-bus-lab-tenant-1 POD=acme TENANT=bus-lab \
      bash container/scenarios/bus-graceful-restart.sh

### No second product finding

The broadcast and retained-egress scenarios did not falsify their invariants.
Ten unique broadcasts produced exactly ten mailbox entries in each of five app
participants. Retired egress stayed at depth one for two seconds while its name
was absent, then reached the api inbox exactly once after re-enrolment.

The first broadcast authoring attempt used non-hex fixture stream IDs. The
switch rejected all fifty with stream_id must be non-empty lowercase hex. That
is the documented parser boundary working, not a product defect; the committed
scenario generates valid 32-character lowercase hex IDs.

The baseline plumbing check reached its long failure simulator after its first
eleven sections. The execution channel timed out while the remote script kept
running, so I stopped only those orphaned bus-lab scripts and recreated bus-lab.
I did not interpret an execution-channel timeout as a framework failure.

## Raw output

Broadcast storm, valid second run:

    container=h-flock-bus-lab-tenant-1 tenant=bus-lab run=broadcast-1786483482-3690673 broadcasts=10
    roster=api,architect,bus-probe-1,bus-probe-2,bus-probe-3,bus-probe-4,bus-probe-5,host,sme-2,
    queued=10 source_egress=0
    bus-probe-1 inbox=10 matching=10
    bus-probe-2 inbox=10 matching=10
    bus-probe-3 inbox=10 matching=10
    bus-probe-4 inbox=10 matching=10
    bus-probe-5 inbox=10 matching=10
    source_egress_after=0
    payload_log_records=0

Retained egress:

    container=h-flock-bus-lab-tenant-1 tenant=bus-lab run=retained-1786483526-3694287
    after_retire roster_value=[] egress=0
    while_absent egress=1 inbox_matches=0
    after_reenrol roster_value=[api] egress=0 inbox_matches=1
    matching_logs:
    {"ts":"2026-08-11T21:25:33.179Z","module":"switch","event":"popped","stream_id":"00000000000000000000000000385ecf","correlation_id":"00000000000000000000000000385ecf","source":"retained-probe","destination":"api"}
    {"ts":"2026-08-11T21:25:33.180Z","module":"switch","event":"forwarded","stream_id":"00000000000000000000000000385ecf","correlation_id":"00000000000000000000000000385ecf","source":"retained-probe","destination":"api"}
    {"ts":"2026-08-11T21:25:33.861Z","module":"port","event":"received","stream_id":"00000000000000000000000000385ecf","correlation_id":"00000000000000000000000000385ecf","source":"retained-probe","destination":"api"}
    {"ts":"2026-08-11T21:25:33.863Z","module":"port","event":"opened","stream_id":"00000000000000000000000000385ecf","correlation_id":"00000000000000000000000000385ecf","source":"retained-probe","destination":"api"}

Graceful restart, run one:

    container=h-flock-bus-lab-tenant-1 tenant=bus-lab run=restart-1786483567-3696390
    before_restart sentinel=[restart-1786483567-3696390] queued=1
    h-flock-bus-lab-tenant-1
    after_restart health=healthy sentinel=[] queue_contains=0 queue_depth=0
    recent_startup:
    {"module":"container","event":"started","reason":"redis pid=12"}
    {"module":"container","event":"started","reason":"tmuxhost pid=26"}
    {"module":"container","event":"windows_ready","count":2}
    {"module":"container","event":"started","reason":"switch pid=64"}
    {"module":"container","event":"started","reason":"watchdog pid=65"}
    {"module":"container","event":"started","reason":"api pid=66"}
    {"module":"container","event":"started","reason":"session pid=67"}

Graceful restart, run two:

    container=h-flock-bus-lab-tenant-1 tenant=bus-lab run=restart-1786483589-3697346
    before_restart sentinel=[restart-1786483589-3697346] queued=1
    h-flock-bus-lab-tenant-1
    after_restart health=healthy sentinel=[] queue_contains=0 queue_depth=0

Parser rejection from the discarded invalid fixture run, repeated for all fifty
envelopes:

    {"ts":"2026-08-11T21:22:43.134Z","module":"switch","event":"dead_lettered","stream_id":"unknown","reason":"stream_id must be non-empty lowercase hex"}

## Cross-read

I read /tmp/tmux-window-loss.log. Its two runs show HTTP 202, then switch
forwarded, port received, port dead_lettered with reason window_missing,
and tmuxhost recreated the window. My reading is that the raw output proves
visible at-most-once loss during the reconcile gap; it does not prove a false
success inside the port because the terminal outcome is explicitly
dead_lettered. The tmux lane ranks that as a high availability finding: ordinary
reconciliation creates an at-most-once loss window despite rapid recovery, but
does not falsify observability. I agree with that reading; there is no disputed
interpretation to report.

## Not run

This build did not run for hours, fill the container disk, catch SIGKILL in the
sub-millisecond BLPOP-to-log window, or send real credentialed model work. The
lab tenant had no seeded account login. Presence history cost is covered by the
bounded-read invariant and scenario design but was not given an hours-long
measurement in this run.
