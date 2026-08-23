# BUILD 93 results — document the surface three builds actually shipped

## Result

Reference documentation in `docs/API.md` and `docs/CONTRACTS.md` has been updated to match the contracts shipped across builds 87, 88, and 91, and internal contracts regarding window lifecycle management have been accurately reconciled:

1. **`office send` Shipped Contract (`docs/API.md:12`, `docs/CONTRACTS.md:439-466`):**
   - Documented the single-argument requirement for positional message text and explicit payload sources:
     - `office send -a <destination> "<text>"`
     - `office send -a <destination> --stdin` (refuses empty stdin)
     - `office send -a <destination> --file <path>` (direct file read without shell interpretation)
     - `office send --agent=<destination> "<text>"` (equals syntax)
     - `office send -a <destination> -- --<leading-dash-body>` (double-dash syntax)
   - Stated the purpose of the acknowledgement message `sent to <destination>: <N> bytes (<stream_id>)`: the UTF-8 byte count confirms the accepted payload size.
   - Stated the distinction with `office broadcast`: `broadcast` deliberately keeps `argparse.REMAINDER`, accepting unquoted multi-word arguments (`office broadcast <text>...`).

2. **`office usage` and `office status` (`docs/CONTRACTS.md:480-492`):**
   - Documented that Codex rows price against the active model resolved from `turn_context` (e.g. `gpt-5.6-sol` pricing against `gpt-5`) rather than falling back to `unpriced`.
   - Documented that Codex rows surface a rate-limit column (`used_percent`, `plan_type`). Noted explicitly that rate limits are verified against the captured rollout fixture `tests/fixtures/codex-session-captured.jsonl` and remain unproven against a live codex agent in acceptance.
   - Documented that agy agents read `not measurable (agy)` in `status` and `model: "not measurable"` with `-` counts and `unpriced` in `usage`.
   - Documented that `office usage --json` carries `"measurable": false` on unmeasurable rows (`agy`), while claude and codex rows omit the key.

3. **Control Opener Records (`docs/CONTRACTS.md:334-345`):**
   - Documented that control openers in `src/flock/control/openers.py:29-58` emit `{start,stop,pause,resume}_agent_accepted` upon acknowledging all desired-state mutations in Redis (`writer: control`, with `destination: <agent>` and `correlation_id` when present).
   - Documented that request validation errors before mutation emit `{start,stop,pause,resume}_agent_failed` with `reason` before dead-lettering, whereas any Redis write exception (including the first write, where outcome is UNKNOWN with no writes acknowledged) emits `{start,stop,pause,resume}_agent_incomplete`.
   - Documented that `_accepted` records desired-state acknowledgement in Redis, not actual window or process creation. For `StartAgent`, window creation and CLI startup are reconciled asynchronously by `tmuxhost.reconcile_once`. For `StopAgent`, the opener attempts to kill the window synchronously inline after desired-state writes, with `tmuxhost` providing later cleanup fallback.

4. **Reconciled Window Lifecycle in `docs/CONTRACTS.md` (`docs/CONTRACTS.md:528-531`, `577-585`):**
   - Updated the Kinds and Payloads table (`StartAgent` / `StopAgent` rows): `StartAgent` publishes desired launch state and enrols while `tmuxhost` reconciles the window/CLI; `StopAgent` removes roster row, purges identity state, and kills the window inline (with `tmuxhost` cleaning up on reconcile).
   - Updated subsection heading and text at lines 577–585 to state that `StartAgent` publishes desired state (async creation in `tmuxhost`) while `StopAgent` attempts actual-state teardown synchronously inline with `tmuxhost` acting as fallback.

5. **Profile Validation (`docs/CONTRACTS.md:467-474`):**
   - Documented that `--profile <account>` is validated against the canonical Redis `accounts` set (`available_profiles()`) at both the office client CLI (`office hire`) and fabric opener (`StartAgent`), rejecting unknown accounts with an explicit error listing available accounts.

## Lines Modified in `docs/CONTRACTS.md`

- Lines 318–325 (`bus` attempt-record paragraph) were left completely untouched.
- Control opener records were inserted at lines 334–345 (immediately following the `event: usage` paragraph).
- Section 5 `office` command surface was updated at lines 439–492.
- Section 6 table and subsection were reconciled at lines 528–531 and 577–585.

---

## Negative Controls

All controls ran against source `e9257683cae13fa041f92e353272d53bf6273934`.
The exact outputs below are quoted from the immutable controls snapshot named in the sign-off:

1. **First write failure emits incomplete (not failed):**
   - *Mutation:* Mutated `src/flock/control/openers.py` `_write_desired` to re-raise exception without `_IncompleteControl` on first write (`if not committed: raise exc`).
   - *Expected locus:* `tests/test_control.py::test_first_desired_write_exception_records_unknown_incomplete`.
   - *Observed locus:* `tests/test_control.py::test_first_desired_write_exception_records_unknown_incomplete` FAILED; exit 1.
   - *Snapshot signature:* `AssertionError: assert 'start_agent_failed' == 'start_agent_incomplete'` at `tests/test_control.py:633`.

2. **Pre-mutation validation failure emits failed (not incomplete):**
   - *Mutation:* Mutated `src/flock/control/openers.py` `_record_control` to emit `f"{kind}_incomplete"` instead of `f"{kind}_failed"` on general exceptions.
   - *Expected locus:* `tests/test_control.py::test_refused_start_records_failure_before_dead_letter`.
   - *Observed locus:* `tests/test_control.py::test_refused_start_records_failure_before_dead_letter` FAILED; exit 1.
   - *Snapshot signature:* `AssertionError: assert 'start_agent_incomplete' == 'start_agent_failed'` at `tests/test_control.py:484`.

3. **Canonical Redis accounts validation:**
   - *Mutation:* Mutated `src/flock/bus/accounts.py` `available_profiles` to return stale accounts `("default", "work", "stale-dir")` (simulating directory scanning).
   - *Expected locus:* `tests/test_office.py::test_hire_reads_canonical_accounts_from_redis`.
   - *Observed locus:* `tests/test_office.py::test_hire_reads_canonical_accounts_from_redis` FAILED; exit 1.
   - *Snapshot signature:* `Failed: DID NOT RAISE SystemExit` at `tests/test_office.py:690`.

4. **Office send byte count acknowledgement:**
   - *Mutation:* Mutated `src/flock/office/cli.py` `_send_command` to omit UTF-8 byte count from acknowledgement output.
   - *Expected locus:* `tests/test_office.py::test_send_reads_stdin_and_reports_utf8_bytes`.
   - *Observed locus:* `tests/test_office.py::test_send_reads_stdin_and_reports_utf8_bytes` FAILED; exit 1.
   - *Snapshot signature:* `AssertionError: assert 'sent to back...stream-stdin)' == 'sent to back...stream-stdin)'` (`- sent to backend: 12 bytes (stream-stdin)` vs `+ sent to backend: (stream-stdin)`) at `tests/test_office.py:192`.

5. **StopAgent synchronous inline window kill:**
   - *Mutation:* Mutated `src/flock/control/openers.py` `stop_agent` to omit `kill_window(agent)` inline (relying solely on tmuxhost reconciliation).
   - *Expected locus:* `tests/test_control.py::test_stop_agent_orders_roster_launch_then_window`.
   - *Observed locus:* `tests/test_control.py::test_stop_agent_orders_roster_launch_then_window` FAILED; exit 1.
   - *Snapshot signature:* `AssertionError: assert [('hget', 'po...ing', 'dave')] == [('hget', 'po...dow', 'dave')]; Right contains one more item: ('kill_window', 'dave')` at `tests/test_control.py:227`.

---

## TEST SIGN-OFF

    claim            living documentation in API.md and CONTRACTS.md accurately describes shipped office send forms, byte acknowledgement, broadcast REMAINDER contrast, usage rate limits and agy unmeasurability, control opener accepted/incomplete/failed records, and reconciled StartAgent async vs StopAgent synchronous window lifecycle
    source sha       e9257683cae13fa041f92e353272d53bf6273934
    artefact         COMMIT
    host             local — pytest runner and citation validation
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container image/build, accept.sh, live tenant
    population       490 tests and 5 subtests; all repository tests collected (0 skipped)

    control          five property mutations: first-write incomplete emission, validation failure emission, canonical Redis accounts validation, office send byte count acknowledgement, and StopAgent synchronous window kill
    expected locus   the five named tests in Negative Controls
    observed locus   the same five tests in Negative Controls
    signature        start_agent_incomplete mismatch; start_agent_failed mismatch; DID NOT RAISE SystemExit; byte count string mismatch; missing kill_window item

    evidence         docs/evidence/build-93-e925768-controls.log sha256 0bcd95c56ab033bb150203fc04b02acba15d5b2e62ddaf81ac9d23de935d6bcf
                     docs/evidence/build-93-e925768-pytest.log sha256 d5d298f4936a9434322b7d1ad095c62963de563ead046b1833d29b47d04bf28b

    verdict          PASS
    VERIFIED BY      PENDING — author of the change? NO

## Citation gate

    source sha       e9257683cae13fa041f92e353272d53bf6273934
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 56 near misses
    evidence         docs/evidence/build-93-e925768-citations.log sha256 ae3cc565bb4af8136e4dbf330b6b6b1c929a86de3b5c182c372671dffb0985e1
