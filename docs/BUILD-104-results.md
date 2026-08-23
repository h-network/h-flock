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

Per `docs/TEST-SIGNOFF.md`, the structural checker inspects `src/` for any
`FLOCK_WRITER` assignments (excluding the single environment read in
`src/flock/bus/logging.py:8`).

- **Clean run**: The checker finds zero assignments and exits 0.
- **Negative mutation**: Mutating `src/flock/switch/service.py` with
  `os.environ["FLOCK_WRITER"] = "fault-injection"` triggers the checker at
  `src/flock/switch/service.py:270` and exits 1:

      STRUCTURAL_VIOLATION:
        src/flock/switch/service.py:270:        os.environ["FLOCK_WRITER"] = "fault-injection",
      MUTATION_EXIT=1

The mutation was restored before generating final gate logs.

## TEST SIGN-OFF

    claim            writer: fault-injection documented in CONTRACTS as scenario-only, structural check confirms absent in src/, and --keep console transfer documented in BUILD-CONVENTION
    source sha       3fa126b
    artefact         COMMIT
    host             local — structural inspection and documentation audit
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         live container execution, Docker image build, runtime benchmark
    population       513 tests and 5 subtests; all repository tests collected

    control          structural mutation: assign FLOCK_WRITER in src/flock/switch/service.py
    expected locus   structural checker exit 1 at src/flock/switch/service.py:270
    observed locus   same
    signature        STRUCTURAL_VIOLATION: src/flock/switch/service.py:270; MUTATION_EXIT=1

    evidence         docs/evidence/build-104-controls.log sha256 a85e99353e857c5dacd0847a4be2c7e5102eb5eaca6af0c683efed241ed2e8dc
                     docs/evidence/build-104-pytest.log sha256 0c3a8689c94edf95e94d03d25c72dcb5f121458dbc24cac4f83066f73aa84c35

    verdict          PASS (structural claim verified with negative mutation control)
    VERIFIED BY      PENDING — assigned by architect

## Citation gate

    source sha       3fa126b
    artefact         COMMIT
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 84 near misses
    evidence         docs/evidence/build-104-citations.log sha256 96fe30d3f709f77eb35518b1a1e9207ead3581fd8b4a998922974c7ec854fd0d

## Merged-tree verification

    merged with      main at cef37d8
    result           clean merge; 513 passed + 5 subtests passed, exit 0; citations 0 hard / 84 near, exit 0
