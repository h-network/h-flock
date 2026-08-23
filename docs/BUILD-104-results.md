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
`tests/test_fault_injection.py`, which statically inspects all python files in
`src/` for any `FLOCK_WRITER` assignments (excluding the single environment read in
`src/flock/bus/logging.py:8`).

- **Clean run**: `python3 -m pytest tests/test_fault_injection.py -k test_shipping_source_has_no_writer_assignments` passes with exit 0.
- **Negative mutation**: Mutating `src/flock/switch/service.py` with
  `os.environ["FLOCK_WRITER"] = "fault-injection"` triggers the assertion in
  `test_shipping_source_has_no_writer_assignments` at `tests/test_fault_injection.py:124`
  identifying `src/flock/switch/service.py:270` and exits 1:

      FAILED tests/test_fault_injection.py::test_shipping_source_has_no_writer_assignments
      AssertionError: Illegal FLOCK_WRITER assignments in shipping source:
        src/flock/switch/service.py:270:os.environ["FLOCK_WRITER"] = "fault-injection",
      MUTATION_EXIT=1

The mutation was restored before generating final gate logs.

## TEST SIGN-OFF

    claim            writer: fault-injection documented in CONTRACTS as scenario-only, structural check confirms absent in src/, and --keep console transfer documented in BUILD-CONVENTION
    source sha       92aedfe
    artefact         COMMIT
    host             local — structural inspection and documentation audit
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live container execution, Docker image build, runtime benchmark
    population       514 tests and 5 subtests; all repository tests collected

    control          structural mutation: assign FLOCK_WRITER in src/flock/switch/service.py
    expected locus   test_shipping_source_has_no_writer_assignments assertion exit 1 at tests/test_fault_injection.py:124
    observed locus   same
    signature        AssertionError: Illegal FLOCK_WRITER assignments in shipping source: src/flock/switch/service.py:270; MUTATION_EXIT=1

    evidence         docs/evidence/build-104-controls.log sha256 87f0001b0b09fe54224705a305f9bc1a6a13fa8f65a9ba69de043dd0a1c14fea
                     docs/evidence/build-104-pytest.log sha256 fa2b05cba684af7fbab2453e01965348cdc7cab9517f65de1070855f1bcd8a11

    verdict          PASS (structural claim verified with negative mutation control)
    VERIFIED BY      PENDING — assigned by architect

## Citation gate

    source sha       92aedfe
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 84 near misses
    evidence         docs/evidence/build-104-citations.log sha256 01a8392c85c9ade5ce9abc15e68899f84790ac43afde71cc0a76f205dd001a0a

## Merged-tree verification

    merged with      main at 3d7900e
    result           clean merge; 514 passed + 5 subtests passed, exit 0; citations 0 hard / 84 near, exit 0
