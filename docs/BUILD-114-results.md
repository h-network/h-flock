# BUILD 114 results — packet switching harness

## Boundary

`container/scenarios/packet-switching.sh` composes the existing sender, bench
port, and unicast reconciler. Its measured clock is **popped → forwarded**:
the envelope has been removed from egress and the switch has written ingress.
The run does not include a port, terminal, or application, and it never reads a
payload. It counts envelopes only.

The `steady` mode starts the synthetic receiver first. `burst` queues the
envelopes while that receiver is absent, then starts it and lets it drain.

## Decision and composition

The harness prints submitted and custody-stage counts, duplicates, losses,
indeterminate forwards, and the named-boundary throughput. It delegates
conservation classification to `reconcile-unicast.py`: 0 is clean, 1 is an
unexplained loss, 2 is a duplicate, 5 is `INDETERMINATE_FORWARD`, and 100 is
incomplete setup or evidence. A stray opened stream is rejected before
reconciliation with rc3. It is not wired to `accept.sh`.

## Negative controls

The subprocess regression controls in `tests/test_packet_switching.py` execute
the harness against retained fixtures and demonstrate distinct failures:

| mutation | expected result |
|---|---|
| remove the opened record | rc1, `PACKET_RESULT rc=1` |
| add a second opened record | rc2, duplicate conservation failure |
| add an opened record for an unsent stream | rc3, `PACKET_RESULT rc=3 reason=stray` |

The clean fixture returns rc0. These controls deliberately exercise the
reconciler rather than merely inspecting source text.

## Live verification

Runs used fresh, namespaced projects on the correctness lab and were torn down
with project-scoped `docker compose down -v`; the four pre-existing `hvab-*`
containers were not touched.

Steady mode (`h-flock-bus114steady`, 10 destinations × 2 rounds) was clean:
20 submitted, 20 popped, 20 forwarded, 20 received, and 20 opened; zero
duplicates or losses; boundary throughput 17.39 envelopes/s; rc0.

Burst mode (`h-flock-bus114burst`, 100 destinations × 2 rounds) was a genuine
RED: 200 submitted, 195 popped/forwarded/received/opened, zero duplicates or
strays, and five unexplained losses; boundary throughput 10.96 envelopes/s;
rc1. The lost stream IDs were:

    a8c3202917604b48b2d1f0298d804d68
    6e9e402b158646a0b66d855c15954cec
    ad1a834c8d2e465b9364d1a70cd1b0c6
    98692d8eec8f4f0881bd85d39f5c079d
    7c4d2740ee0744e580f982e0564b6009

Immutable custody snapshots are retained at
`docs/evidence/build-114-steady-custody.log` (sha256
`228bc00d85c1e36906b9823e5c505637a63749d042e2fbd52b98effdfa2e9f4a`) and
`docs/evidence/build-114-burst-custody.log` (sha256
`ea31ac21e3f048b4c8aee5f74fb0c4fb4bc11294ab930d8bc599fbe18147ddca`).

The burst RED is the result, not a throughput defect in the harness: it shows
that queued envelopes can be lost when the receiver is absent, and the
reconciler catches that at the packet boundary.

## Verification status

Targeted gate: `PYTHONPATH=. pytest -q tests/test_packet_switching.py tests/test_conservation_contract.py` — 7 passed.

No live tenant or burst result is claimed in this implementation checkpoint;
those runs require a reserved correctness tenant and are separate from the
fixture controls above.
