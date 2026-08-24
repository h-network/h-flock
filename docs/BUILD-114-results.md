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

## Verification status

Targeted gate: `PYTHONPATH=. pytest -q tests/test_packet_switching.py tests/test_conservation_contract.py` — 7 passed.

No live tenant or burst result is claimed in this implementation checkpoint;
those runs require a reserved correctness tenant and are separate from the
fixture controls above.
