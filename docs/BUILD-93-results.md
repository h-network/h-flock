# BUILD 93 results — document the surface three builds actually shipped

## Result

Reference documentation in `docs/API.md` and `docs/CONTRACTS.md` has been updated to match the contracts shipped across builds 87, 88, and 91, and internal contradictions in `CONTRACTS.md` regarding asynchronous window lifecycle reconciliation have been resolved:

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

3. **Control Opener Records & Desired-State Limit (`docs/CONTRACTS.md:334-344`):**
   - Documented that control openers in `src/flock/control/openers.py:29-58` emit `{start,stop,pause,resume}_agent_accepted` upon acknowledging all desired-state mutations in Redis (`writer: control`, with `destination: <agent>` and `correlation_id` when present).
   - Documented that request validation errors before mutation emit `{start,stop,pause,resume}_agent_failed` with `reason` before dead-lettering, whereas any Redis write exception (including the first write, where outcome is UNKNOWN with no writes acknowledged) emits `{start,stop,pause,resume}_agent_incomplete`.
   - Explicitly stated the contract limit: `_accepted` records desired-state acknowledgement in Redis, not actual tmux window or process creation. Actual window lifecycle is reconciled asynchronously by `tmuxhost.reconcile_once`.

4. **Reconciled Async Window Lifecycle in `docs/CONTRACTS.md` (`docs/CONTRACTS.md:528-531`, `577-584`):**
   - Updated the Kinds and Payloads table (`StartAgent` / `StopAgent` rows) to state that `StartAgent` publishes desired launch state and enrols while `tmuxhost` reconciles the window/CLI, rather than asserting synchronous window creation.
   - Updated subsection heading and text at lines 577–584 to state that `StartAgent` and `StopAgent` publish desired state and actual reconciliation is asynchronous.

5. **Profile Validation (`docs/CONTRACTS.md:467-474`):**
   - Documented that `--profile <account>` is validated against the canonical Redis `accounts` set (`available_profiles()`) at both the office client CLI (`office hire`) and fabric opener (`StartAgent`), rejecting unknown accounts with an explicit error listing available accounts.

## Lines Modified in `docs/CONTRACTS.md`

- Lines 318–325 (`bus` attempt-record paragraph) were left completely untouched.
- Control opener records were inserted at lines 334–344 (immediately following the `event: usage` paragraph).
- Section 5 `office` command surface was updated at lines 439–492.
- Section 6 table and subsection were reconciled at lines 528–531 and 577–584.

---

## Negative Controls

All controls ran against source `08218d2d603a11eead3e3905be80e0f7692c8bb8`.
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

---

## TEST SIGN-OFF

    claim            living documentation in API.md and CONTRACTS.md accurately describes shipped office send forms, byte acknowledgement, broadcast REMAINDER contrast, usage rate limits and agy unmeasurability, control opener accepted/incomplete/failed records, and reconciled async window reconciliation
    source sha       08218d2d603a11eead3e3905be80e0f7692c8bb8
    artefact         COMMIT
    host             local — pytest runner and citation validation
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container image/build, accept.sh, live tenant
    population       490 tests and 5 subtests; all repository tests collected (0 skipped)

    control          four property mutations: first-write incomplete emission, validation failure emission, canonical Redis accounts validation, and office send byte count acknowledgement
    expected locus   the four named tests in Negative Controls
    observed locus   the same four tests in Negative Controls
    signature        start_agent_incomplete mismatch; start_agent_failed mismatch; DID NOT RAISE SystemExit; byte count string mismatch

    evidence         docs/evidence/build-93-08218d2-controls.log sha256 b9edaf9d6f371ce1fdc78359a441d27e7e76fb9a25173bf490bb6fedc52bc103
                     docs/evidence/build-93-08218d2-pytest.log sha256 1332cb90bf20f856dba7b3c5b9309e3eaf6b15947ad1680600e7bc7bd9ac401a

    verdict          PASS
    VERIFIED BY      PENDING — author of the change? NO

## Citation gate

    source sha       08218d2d603a11eead3e3905be80e0f7692c8bb8
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 56 near misses
    evidence         docs/evidence/build-93-08218d2-citations.log sha256 b44f5a954615c3fd3d4a9eddf60abdeb98fad65c409f0e9b95b8db1af32fa11a
