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
`src/` for any `FLOCK_WRITER` assignments (including bracket assignment, `setdefault`,
`update`, `putenv`) and literal `"fault-injection"` writer settings without brittle
line-number exemptions.

- **Clean run**: `python3 -m pytest tests/test_fault_injection.py -k test_shipping_source_has_no_writer_assignments` passes with exit 0.
- **Negative mutation**: Mutating `src/flock/switch/service.py` with
  `os.environ["FLOCK_WRITER"] = "fault-injection"` triggers the assertion in
  `test_shipping_source_has_no_writer_assignments` at `tests/test_fault_injection.py:128`
  identifying `src/flock/switch/service.py:270` and exits 1:

      FAILED tests/test_fault_injection.py::test_shipping_source_has_no_writer_assignments
      AssertionError: Illegal FLOCK_WRITER assignments in shipping source:
        src/flock/switch/service.py:270:os.environ["FLOCK_WRITER"] = "fault-injection",
      MUTATION_EXIT=1

The mutation was restored before generating final gate logs.

## TEST SIGN-OFF

    claim            writer: fault-injection documented in CONTRACTS as scenario-only, structural check confirms absent in src/, and --keep console transfer documented in BUILD-CONVENTION
    source sha       072ffd4
    artefact         COMMIT
    host             local — structural inspection and documentation audit
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live container execution, Docker image build, runtime benchmark
    population       514 tests and 5 subtests; all repository tests collected

    control          structural mutation: assign FLOCK_WRITER in src/flock/switch/service.py
    expected locus   test_shipping_source_has_no_writer_assignments assertion exit 1 at tests/test_fault_injection.py:128
    observed locus   same
    signature        AssertionError: Illegal FLOCK_WRITER assignments in shipping source: src/flock/switch/service.py:270; MUTATION_EXIT=1

    evidence         docs/evidence/build-104-controls.log sha256 57f968c6fbee82abd2b51e7cb0dd0c4158e6b58df333635c9877aedb9dc820ad
                     docs/evidence/build-104-pytest.log sha256 f82178ee4bb8c3cc5a5a81cd588a9113bb7e62d9e68e2e46183f29c03879b420

    verdict          PASS (structural claim verified with negative mutation control)
    VERIFIED BY      PENDING — assigned by architect

## Citation gate

    source sha       072ffd4
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 84 near misses
    evidence         docs/evidence/build-104-citations.log sha256 75c708bf0d2a557f76c01a0e8ce752d7a94aac0517580296b444463efe08f568

## Merged-tree verification

    merged with      main at 3d7900e
    result           clean merge; 514 passed + 5 subtests passed, exit 0; citations 0 hard / 84 near, exit 0
