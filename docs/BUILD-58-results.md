# Build 58 — conservation result

Commit under test: `ed061e9` on `tmux/build-58-conservation`.

## Result

The first required negative control passed silently. Per the build's explicit
stop rule, the harness is worthless as conservation evidence and no loss
control, 10,000-envelope run, injection, or growth measurement was attempted.

The cause is in the harness rather than the framework: its setup programs use a
heredoc with `docker exec` but omit `-i`. Docker therefore attaches no stdin;
Python reads an empty program, exits successfully, and neither writes the ledger
nor injects the duplicate. Reconciliation then balances an empty set and the
outer control reports the silent pass. This is the same false-green mechanism
already documented in `fabric-bench`: `-i` is load-bearing for an embedded
Python program.

No correction or rerun was made in this build. The failed negative control is
the result the spec requires us to preserve.

## Raw lab-local output

```text
conservation container=h-flock-conservation-tenant-1 stations=100 rounds=100 work=/tmp/conservation-evidence
== negative control: duplicate ==
RECONCILE sent=0 delivered_once=0 duplicates=0 dead=0 lost_attributed=0 lost_unexplained=0
PARSE_FAILURES docker_json=0 dead_json=0 event_ts=0
INJECTION_COVERAGE seconds=0.000 fraction=0.000000
HARNESS DEFECT: intentional duplicate passed silently
```

The scoped `h-flock-conservation` project was removed with `down -v`; the lab
was left with only the operator-owned `h-cli` container.

## Authorized correction and rerun

The branch was rebased onto `main` at `3b23dc0`, and commit `f9f2b37` added
stdin attachment to the shared `docker exec` helper. The harness was then
rerun from the top. The duplicate was genuinely delivered twice, but the
duplicate control failed for the wrong reason and again stopped the build
before the loss control or stressed run:

```text
== negative control: duplicate ==
{"ts":"2026-08-14T12:06:06.303Z","module":"port","event":"opened","stream_id":"dc0608c0f60f4439a6b376366f9ae1fd","correlation_id":"3aaccbbac44e430f89b2810e30675092","source":"cons-0","destination":"cons-1"}
{"ts":"2026-08-14T12:06:07.177Z","module":"port","event":"opened","stream_id":"dc0608c0f60f4439a6b376366f9ae1fd","correlation_id":"3aaccbbac44e430f89b2810e30675092","source":"cons-0","destination":"cons-1"}
RECONCILE sent=1 delivered_once=0 duplicates=0 dead=0 lost_attributed=0 lost_unexplained=1
PARSE_FAILURES docker_json=0 dead_json=0 event_ts=0
INJECTION_COVERAGE seconds=0.000 fraction=0.000000
LOSS_UNEXPLAINED negative-duplicate dc0608c0f60f4439a6b376366f9ae1fd none
HARNESS DEFECT: duplicate control failed for wrong reason rc=1
```

The two `opened` records were emitted by `flock.port` processes launched via
attached `docker exec`. They reached the harness's top-level output but not the
container's Docker log. Reconciliation reads only the captured `docker logs`,
so it saw neither opening and classified the ledger entry as unexplained loss
instead of a duplicate. This proves the negative control still cannot validate
the evidence path. No second correction or further run was made.

The scoped project was again removed with `down -v`; the lab was left with only
the operator-owned `h-cli` container.

## Attempt three: real path controls and stressed run

Commit `3495c9c` routed the duplicate control through the source egress queue.
PID 1's switch therefore performed both forwards and spawned both ports. Both
negative controls then failed the reconciler with their required, specific
exit codes before the stressed phase began:

```text
RECONCILE sent=1 delivered_once=0 duplicates=1 dead=0 lost_attributed=0 lost_unexplained=0
PARSE_FAILURES docker_json=0 dead_json=0 event_ts=0
DUPLICATE negative-duplicate 6e8064819e474893990ca0b2abb51d60 2

RECONCILE sent=1 delivered_once=0 duplicates=0 dead=0 lost_attributed=0 lost_unexplained=1
PARSE_FAILURES docker_json=0 dead_json=0 event_ts=0
LOSS_UNEXPLAINED negative-loss b45663326ca447ff9058576df71c7000 none
```

The stressed phase sent all 10,000 uniquely numbered envelopes and performed
all eight scheduled injections: five port kills and three switch kills. Egress
eventually drained to zero. One frame remained intact in Redis indefinitely:

```text
sequence=9935
stream_id=21aaaee976694d398f9396d13f36bd30
queue=pod:acme:tenant:conservation:agent:cons-36:ingress
queue_depth=1
delivering=0
```

This is a liveness gap, not evidence against at-most-once safety. A port pops
one envelope per kick. If a kicked port dies before its pop, subsequent traffic
for that destination moves the gap forward: each new kick drains the previous
frame and leaves the new frame queued. Delivery remains permanently one kick
behind. When production stops, the last frame is orphaned indefinitely because
no ingress sweeper, retry, or reaper exists.

### Why attempt three cannot support a safety conclusion

The stressed phase did not share the negative control's evidence path. It
stopped PID 1's switch and launched a test switch through `docker exec`, with
stdout redirected to `/tmp/conservation-switch.log` inside the container. The
ports it spawned inherited that stream. Reconciliation still read only
`docker logs`, so it saw none of the stressed run's `opened` records and
reported 9,999 absent frames plus the one stranded frame. That is an instrument
failure, not a framework loss count. The switch log cannot repair the evidence:
each switch restart truncates the same path, and its surviving final segment
contains only 6,728 of the 10,000 openings.

The drain limit also counted 2,400 loop iterations rather than 2,400 seconds.
Every iteration performs two `docker exec` probes and then sleeps, so under load
the intended 40-minute boundary silently became a multi-hour wait. The run was
stopped after 2,400 wall seconds once the absence of any ingress kick source was
confirmed mechanically.

Commit `9d74975` added a separate `stranded` category and an evidence-only
reconciliation mode. Its top-level initialization truncated `injections.tsv`
and `samples.tsv` before replay, however, destroying the coverage and growth
samples. The raw run log retains all eight injection windows, but the original
sample series is not recoverable. No duplicate count across the 10,000-frame
run can be claimed from this attempt.

## Attempt four: valid conservation result

Commit `1c8cc2b` made the evidence path structural: the controlled test switch
and every port it spawns inherit `/proc/1/fd/1`, so custody records reach the
same PID 1 stream read by `docker logs`. Evidence-only replay no longer
truncates the ledgers, and the drain deadline uses wall-clock seconds.

Both negative controls gated correctly before stressed traffic began. The
intentional duplicate produced one `DUPLICATE` row and exit 2; the intentional
drop produced one `LOSS_UNEXPLAINED` row and exit 1. All parse-failure counts
were zero in both controls.

Final reconciliation across all 10,000 unique sequence numbers was:

```text
RECONCILE sent=10000 delivered_once=9997 duplicates=0 dead=0 stranded=2 lost_attributed=1 lost_unexplained=0
PARSE_FAILURES docker_json=0 dead_json=0 ingress_json=0 event_ts=0
INJECTION_COVERAGE seconds=48.328 fraction=0.156559
STRANDED 9956 50a8ff8ddaa14da49ae32155171f7d85
STRANDED 9990 77e6f275c75c401392faee0e7b38d94d
LOSS_ATTRIBUTED 818 36ed04f6e84345c989772bd25894ca5c switch-kill:old=396,new=1427,target=2200
```

The categories sum to 10,000. At-most-once safety held with zero duplicates.
One envelope was lost, and its send/custody timing falls within the first
switch-kill attribution window. There were no unexplained losses.

Eight failures were injected: five port kills and three switch kills. The five
port kills resulted in two terminal strands, meaning two kills landed between
kick and pop. A kill outside that narrow window does not create a strand. The
two raw queued frames were captured before teardown, including their complete
envelopes, so `stranded` means retained intact in Redis rather than inferred
from an absent log record. Attempt three stranded one; attempt four stranded
two. This matches a probabilistic injection window rather than every port kill
causing a strand.

Growth samples are `elapsed_s used_memory_bytes queue_depth pid1_rss_kib`:

```text
0   1567176 0    1280
61  2545064 1136 1280
128 3384336 2484 1280
193 3956424 3995 1280
259 4921624 5509 1280
326 5604464 6354 1280
394 5353864 5585 1280
461 5556376 4849 1280
529 5687664 4042 1280
595 5532992 3301 1280
659 5760024 2655 1280
726 5712120 1884 1280
795 5710448 1084 1280
862 5881040 287  1280
928 5909544 2    1280
990 5888048 2    1280
```

Redis memory rose with queued traffic and levelled near 5.9 MB while the queue
drained. PID 1 RSS stayed at 1,280 KiB. The final queue depth of two is exactly
the two stranded frames.

The lab-local evidence bundle is
`/home/h-lab/tmux-build58-rerun/evidence-attempt4`, with SHA-256 checksums for
the 10,000-line ledger, eight-line injection ledger, raw ingress frames, growth
samples, Docker logs, top-level output, and reconciliation. The scoped tenant
was removed with `down -v`; only operator-owned `h-cli` remained.
