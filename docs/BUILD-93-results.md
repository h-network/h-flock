# BUILD 93 results — document the surface three builds actually shipped

## Result

Reference documentation in `docs/API.md` and `docs/CONTRACTS.md` has been updated to match the contracts shipped across builds 87, 88, and 91:

1. **`office send` Shipped Contract (`docs/API.md:12`, `docs/CONTRACTS.md:439-460`):**
   - Documented the single-argument requirement for positional message text and explicit payload sources:
     - `office send -a <destination> "<text>"`
     - `office send -a <destination> --stdin` (refuses empty stdin)
     - `office send -a <destination> --file <path>` (direct file read without shell interpretation)
     - `office send --agent=<destination> "<text>"` (equals syntax)
     - `office send -a <destination> -- --<leading-dash-body>` (double-dash syntax)
   - Stated the purpose of the acknowledgement message `sent to <destination>: <N> bytes (<stream_id>)`: the UTF-8 byte count confirms the accepted payload size.
   - Stated the distinction with `office broadcast`: `broadcast` deliberately keeps `argparse.REMAINDER`, accepting unquoted multi-word arguments (`office broadcast <text>...`).

2. **`office usage` and `office status` (`docs/CONTRACTS.md:468-478`):**
   - Documented that Codex rows price against the active model resolved from `turn_context` (e.g. `gpt-5.6-sol` pricing against `gpt-5`) rather than falling back to `unpriced`.
   - Documented that Codex rows surface a rate-limit column (`used_percent`, `plan_type`). Noted explicitly that rate limits are verified against the captured rollout fixture `tests/fixtures/codex-session-captured.jsonl` and remain unproven against a live codex agent in acceptance.
   - Documented that agy agents read `not measurable (agy)` in `status` and `model: "not measurable"` with `-` counts and `unpriced` in `usage`.
   - Documented that `office usage --json` carries `"measurable": false` on unmeasurable rows (`agy`), while claude and codex rows omit the key.

3. **Control Opener Records & Desired-State Limit (`docs/CONTRACTS.md:334-343`):**
   - Documented that control openers in `src/flock/control/openers.py:29-56` emit `{start,stop,pause,resume}_agent_accepted` upon acknowledging desired-state mutations in Redis (`writer: control`, with `destination: <agent>` and `correlation_id` when present).
   - Documented that pre-mutation exceptions/refusals emit `{start,stop,pause,resume}_agent_failed` with `reason` before dead-lettering, while partial-mutation failures emit `{start,stop,pause,resume}_agent_incomplete`.
   - Explicitly stated the contract limit: `_accepted` records desired-state acknowledgement in Redis, not actual tmux window or process creation. Actual window lifecycle is reconciled asynchronously by `tmuxhost.reconcile_once`.

4. **Profile Validation & Token Authentication (`docs/CONTRACTS.md:461-464`):**
   - Documented that `--profile <account>` is validated against configured account directories (`available_profiles()`) at both the office client CLI (`office hire`) and fabric opener (`StartAgent`), rejecting unknown accounts with an explicit error listing available accounts.

## Lines Modified in `docs/CONTRACTS.md`

- Lines 318–325 (`bus` attempt-record paragraph) were left completely untouched.
- Control opener records were inserted at lines 334–343 (immediately following the `event: usage` paragraph).
- Section 5 `office` command surface was updated at lines 439–478.

---

## TEST SIGN-OFF

    claim            living documentation in API.md and CONTRACTS.md accurately describes shipped office send forms, byte acknowledgement, broadcast REMAINDER contrast, usage rate limits and agy unmeasurability, and control opener accepted/failed records
    source sha       0e9ef0e54d3205fa8130830cbdb94e24ef4bca1f
    artefact         COMMIT
    host             local — pytest runner and citation validation
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container image/build, accept.sh, live tenant
    population       490 tests and 5 subtests; all repository tests collected (0 skipped)

    control          checked against source implementations in src/flock/office/cli.py, src/flock/control/openers.py, and src/flock/watchdog/activity.py
    evidence         docs/evidence/build-93-0e9ef0e-pytest.log sha256 b4892d7022b46f4d32c1bc4e749946823eb3c4ef81322e3a2b82ef27edd1921e

    verdict          PASS
    VERIFIED BY      PENDING — author of the change? NO

## Citation gate

    source sha       0e9ef0e54d3205fa8130830cbdb94e24ef4bca1f
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 56 near misses
    evidence         docs/evidence/build-93-0e9ef0e-citations.log sha256 7bc8dcd0684928cd162f1f3e0cc70582d3159ef82345e785f7c1576475c73dcd
