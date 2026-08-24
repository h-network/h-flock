# BUILD 119 results — judge only harness traffic

## Change

`judge()` now scopes custody records to the harness namespace: a record is in
scope when its source or destination starts with `bench-`. It reports
`PACKET_SCOPE ... ignored_out_of_scope=N`; unrelated tenant traffic is not
silently treated as a packet result. A `bench-*` opened record with no matching
`bench-*` sent record remains a stray and returns rc3.

## Controls

Behavioral subprocess controls cover both halves:

- An unrelated `architect → telegram` opened record is ignored and the clean
  bench fixture returns rc0.
- An injected `bench-9 → bench-1` opened record remains in scope and returns
  rc3 with `reason=stray`.

Loss, duplicate, and clean fixture controls continue to pass unchanged.

Targeted gate: `PYTHONPATH=. pytest -q tests/test_packet_switching.py tests/test_conservation_contract.py` — 8 passed.

`accept.sh` and harness wiring remain out of scope.

## TEST SIGN-OFF

    claim            packet harness judges only its own bench traffic while retaining bench-scoped stray detection
    source sha       branch tip
    host             NOT MATERIAL — fixture controls; no live run requested
    command          pytest -q tests/test_packet_switching.py tests/test_conservation_contract.py
    exit status      0, read unpiped
    EXCLUDED         accept.sh wiring, live acceptance, payload integrity
    control          unrelated opened record plus in-scope bench stray
    expected locus   packet-switching.sh judge scope and rc3 stray branch
    observed locus   same
    signature        8 passed; unrelated traffic rc0; bench stray rc3
    verdict          PASS
    VERIFIED BY      PENDING
