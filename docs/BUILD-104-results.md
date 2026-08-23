# BUILD 104 results — document writer: fault-injection and console transfer

## Result

`docs/CONTRACTS.md` now documents `writer: fault-injection` alongside the
standard operational process labels (`control`, `switch`, `port`, `tmuxhost`,
`watchdog`, `container`, `usage`, `bench-send`, `bench-port`). It states
explicitly that `writer: fault-injection` is set via `FLOCK_WRITER=fault-injection`
exclusively by scenario harnesses in `container/scenarios/` when deliberately
provoking synthetic failure shapes (`forward_unknown`, `stop_agent_incomplete`) on
disposable tenants, and that it never appears in normal operation.

`docs/BUILD-CONVENTION.md` §3.0 now documents that `container/accept.sh --keep`
transfers ownership of the background console proxy host process to the operator
(`kept: container=<name>; console_pid=<pid> (stop console: kill <pid>)`), making
the operator responsible for killing the process to prevent leaked host proxies.

## Structural control

The claim *"writer: fault-injection never appears in normal operation"* is a
**structural claim**: no shipping code path in `src/` sets `FLOCK_WRITER` or
assigns `"fault-injection"`.

Per `docs/TEST-SIGNOFF.md`, this invariant is persistently controlled by
`test_shipping_source_has_no_writer_assignments` in
`tests/test_fault_injection.py:110-128`, which statically inspects all python files in
`src/` and rejects every `FLOCK_WRITER` occurrence except the exact known read line
`_WRITER = os.environ.get("FLOCK_WRITER")` in `src/flock/bus/logging.py`, and rejects
the literal string `"fault-injection"` anywhere in `src/`.

- **Clean run**: `python3 -m pytest tests/test_fault_injection.py -k test_shipping_source_has_no_writer_assignments` passes with exit 0.
- **Negative mutation**: Mutating `src/flock/switch/service.py` with
  `os.environ.update({"FLOCK_WRITER": "fault-injection"})` triggers the assertion in
  `test_shipping_source_has_no_writer_assignments` at `tests/test_fault_injection.py:128`
  identifying `src/flock/switch/service.py:270` and exits 1:

      FAILED tests/test_fault_injection.py::test_shipping_source_has_no_writer_assignments
      AssertionError: Illegal FLOCK_WRITER or fault-injection in shipping source:
        src/flock/switch/service.py:270:os.environ.update({"FLOCK_WRITER": "fault-injection"}),
      MUTATION_EXIT=1

The mutation was restored before generating final gate logs.

## TEST SIGN-OFF

    claim            writer: fault-injection documented in CONTRACTS as scenario-only, structural check confirms absent in src/, and --keep console transfer documented in BUILD-CONVENTION
    source sha       14b549d
    artefact         COMMIT
    host             local — structural inspection and documentation audit
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live container execution, Docker image build, runtime benchmark
    population       514 tests and 5 subtests; all repository tests collected

    control          structural mutation: assign FLOCK_WRITER in src/flock/switch/service.py via update/dict
    expected locus   test_shipping_source_has_no_writer_assignments assertion exit 1 at tests/test_fault_injection.py:128
    observed locus   same
    signature        AssertionError: Illegal FLOCK_WRITER or fault-injection in shipping source: src/flock/switch/service.py:270; MUTATION_EXIT=1

    evidence         docs/evidence/build-104-controls.log sha256 aac5d25362e66d9c1043c19c4226fb0ab161561416ce467a2bb0224a3fb57183
                     docs/evidence/build-104-pytest.log sha256 ef82ac323b87acef285772325ec22d24c8411370bd7abd56b92fc20daac4b880

    verdict          PASS (structural claim verified with negative mutation control)
    VERIFIED BY      PENDING — assigned by architect

## Citation gate

    source sha       14b549d
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 84 near misses
    evidence         docs/evidence/build-104-citations.log sha256 ed759311eb26b7ed420990b1a2f7e52dee0993bab07bfb810dab227b43e69249

## Merged-tree verification

    merged with      main at 3d7900e
    result           clean merge; 514 passed + 5 subtests passed, exit 0; citations 0 hard / 84 near, exit 0
