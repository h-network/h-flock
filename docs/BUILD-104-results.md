# BUILD 104 results — document writer: fault-injection and console transfer

## Result

`docs/CONTRACTS.md` now documents `writer: fault-injection` alongside the
standard operational process labels (`control`, `switch`, `port`, `tmuxhost`,
`watchdog`, `container`, `usage`, `bench-send`, `bench-port`). It states
explicitly that `writer: fault-injection` is set via `FLOCK_WRITER=fault-injection`
exclusively by scenario harnesses in `container/scenarios/` when deliberately
provoking synthetic failure shapes (`forward_unknown`, `stop_agent_incomplete`) on
disposable tenants, that it never appears in normal operation, and that no shipping
code in `src/` emits, assigns, or references the `fault-injection` writer or `FLOCK_WRITER`
beyond the single read in `src/flock/bus/logging.py:8`.

`docs/BUILD-CONVENTION.md` §3.0 now documents that `container/accept.sh --keep`
transfers ownership of the background console proxy host process to the operator
(`kept: container=<name>; console_pid=<pid> (stop console: kill <pid>)`), making
the operator responsible for killing the process to prevent leaked host proxies.

## Structural control

The claim *"writer: fault-injection never appears in normal operation and is unreferenced in shipping source"*
is a **structural claim**: no shipping code path in `src/` sets `FLOCK_WRITER` or
assigns/references `"fault-injection"`.

Per `docs/TEST-SIGNOFF.md`, this invariant is persistently controlled by
`test_shipping_source_has_no_writer_assignments` in
`tests/test_fault_injection.py:110-147`:
- **Population anchor**: Asserts `len(py_files) >= 10` in `src/`.
- **Known-read anchor**: Asserts that the single known environment read `_WRITER = os.environ.get("FLOCK_WRITER")` in `src/flock/bus/logging.py` was parsed and encountered exactly once.
- **AST traversal**: Rejects any other `FLOCK_WRITER` identifier/constant, and rejects any literal `"fault-injection"` anywhere in `src/`.

- **Clean run**: `python3 -m pytest tests/test_fault_injection.py -k test_shipping_source_has_no_writer_assignments` passes with exit 0.
- **Negative mutation 1 (Missing scan root)**: Repointing `src_dir` to `ROOT / "missing-src"` triggers the population assertion at `tests/test_fault_injection.py:115` and exits 1.
- **Negative mutation 2 (FLOCK_WRITER / fault-injection setter)**: Mutating `src/flock/switch/service.py` with `os.environ.update(
 {"FLOCK_WRITER": "fault-injection"}
)` inside `step()` triggers the assertion at `tests/test_fault_injection.py:146` identifying `src/flock/switch/service.py:105` and exits 1.

Both mutations were restored before generating final gate logs.

## TEST SIGN-OFF

    claim            writer: fault-injection documented in CONTRACTS as scenario-only, structural check confirms absent in src/, and --keep console transfer documented in BUILD-CONVENTION
    source sha       e6f5a87
    artefact         COMMIT
    host             local — structural inspection and documentation audit
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live container execution, Docker image build, runtime benchmark
    population       514 tests and 5 subtests; all repository tests collected

    control          structural mutations: (1) repoint scan root to missing-src; (2) assign FLOCK_WRITER / fault-injection in src/flock/switch/service.py
    expected locus   (1) assertion exit 1 at tests/test_fault_injection.py:115; (2) assertion exit 1 at tests/test_fault_injection.py:146
    observed locus   same
    signature        (1) AssertionError: Expected at least 10 python files in src/, found 0; (2) AssertionError: Illegal FLOCK_WRITER or fault-injection in shipping source: src/flock/switch/service.py:105; MUTATION_EXIT=1

    evidence         docs/evidence/build-104-controls.log sha256 2c5c5363bc542229bfcc844b5c4125c976efa833e305c0f588150ab98c116070
                     docs/evidence/build-104-pytest.log sha256 c67ba43da7d296b0375f2750347a43a3361d3c63a11eaf5e8be4b86dabcb1031

    verdict          PASS (structural claim verified with negative mutation controls)
    VERIFIED BY      PENDING — assigned by architect

## Citation gate

    source sha       e6f5a87
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 85 near misses
    evidence         docs/evidence/build-104-citations.log sha256 57bffaa13f8708210a2a79debd1d51c1b721b591951f2c03b8b6c2962e808180

## Merged-tree verification

    merged with      main at 3d7900e
    result           clean merge; 514 passed + 5 subtests passed, exit 0; citations 0 hard / 85 near, exit 0
