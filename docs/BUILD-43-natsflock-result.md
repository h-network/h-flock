# Build 43 — natsflock spike result

Worked from 7abbd133b16c61615ebe72e55611e4760be287f3. Recommendation:
**no transport swap**. This is a successful negative spike, stopped at the
pre-declared criterion in BUILD-43 §7 rather than expanded into a half-migration.

## What the probe moved

The disposable probe maps one ingress to subject
flock.acme.spike.agent.bob, stores it in a single-node file-backed JetStream,
and creates one explicit-ack durable pull consumer named agent_bob. Redis and
all h-flock code remain untouched. It then publishes with no consumer process,
disconnects, and starts a separate process to fetch and acknowledge the retained
message.

This is enough to answer the architectural question. It is not presented as an
h-flock implementation.

## Raw evidence

Run on the lab with nats:2.11-alpine and nats-py 2.11.0:

    server_image=nats:2.11-alpine client_image=python:3.12-slim
    [1] 2026/08/13 00:04:51.095590 [INF] Starting nats-server
    [1] 2026/08/13 00:04:51.097334 [INF] Starting JetStream
    [1] 2026/08/13 00:04:51.113898 [INF] Server is ready
    phase=publish-and-leave-no-port-running
    publish_ack stream=FLOCK_SPIKE sequence=1
    without_adapter num_pending=1 num_ack_pending=0 delivered_consumer_seq=0
    application_records=[]
    processes_after_publish:
    PID                 COMMAND             COMMAND
    107466              nats-server         nats-server -js -sd /data
    phase=start-one-explicit-port-process
    adapter_fetch stream_id=0123456789abcdef0123456789abcdef subject=flock.acme.spike.agent.bob stream_sequence=1 consumer_sequence=1 delivered=1 pending=0
    ack_point=receipt before opener
    after_ack num_pending=0 num_ack_pending=0 ack_floor_consumer_seq=1
    broker_application_records=[]
    server_monitoring_is_broker_state; application lifecycle records above remain empty

The server retained the message correctly while no port existed. It did not
and cannot start flock.port. A pull consumer needs a client fetch loop; a
push consumer needs a continuously subscribed client. Either is a resident
process. Polling pending counts from tmuxhost would merely move the switch into
tmuxhost and couple window reconciliation to transport. A separate dispatcher
would be the switch under a new name.

## Five-record criterion

The result fails the criterion. The publish edge can emit sent, and the port
edge can emit received/opened after it starts. JetStream exposes publish ack,
stream sequence, consumer sequence, delivery count and pending count. It does
not emit h-flock's per-envelope popped and forwarded application records.

Those two names could be printed by the port after fetch, but that would
collapse switch custody, broker forwarding and port receipt into one edge.
They would be synthetic labels rather than the two independent observations
that made the trace diagnostic. Alternatively, a bespoke observer can consume
every envelope and correlate consumer advisories, while a dispatcher wakes the
port. That is at least the two responsibilities of the existing small switch,
now split across NATS and new application code.

Generic broker metrics are therefore not a substitute, and manufacturing four
records at one edge does not preserve the property merely because the event
names still appear.

## The two deliberate decisions

### At-most-once

The probe configures explicit acknowledgment with max_deliver=1 and acknowledges
immediately on receipt, before an opener. This is the closest JetStream mapping
to today's at-most-once choice: an opener crash loses the delivery rather than
executing it twice. It deliberately declines JetStream's normal redelivery
benefit.

That choice exposes the mismatch. If the port is not resident, something
must launch it before the fetch can occur. If it is resident, the idle-agent
cost and kick-and-exit invariant are lost. If acknowledgment moves after the
opener, duplicate execution becomes possible and h-flock's delivery guarantee
changes.

### Audit row 6

It does not disappear under the required at-most-once mapping. A process can
die after JetStream hands it the message but before it records popped or sends
the receipt ack. max_deliver=1 prevents another delivery; acknowledging first
merely moves the invisible window to ack-before-log. Closing the window requires
redelivery or a separate application journal, neither of which preserves the
chosen semantics for free.

JetStream does improve the pre-consumer half: a publish acknowledged by the
server is retained while no port exists. That is real, but it does not close
the consumer-side observation window.

## Evidence deliberately not run

The 1,285-envelope integrity comparison, accept.sh 25/25 and 19/19, and the
four-agent 30-minute endpoint load were not run against NATS because there is no
candidate transport implementation to run them against. BUILD-43 §7 says to
stop when the port lifecycle needs a daemon or the trace needs a bespoke
observer. Both conditions were demonstrated before modifying h-flock.

Running the Redis baselines again would only reproduce the supplied baseline;
calling them NATS evidence would be false. Building enough dispatcher and trace
observer code to run the harness would ignore the spike's stop rule and produce
the half-migration the spec forbids.

The probe cleaned up its uniquely named NATS container and Docker network. It
published no ports and touched no h-flock tenant or operator container.
