# BUILD 88 results — usage truth: codex model, last-not-total, agy unmeasurable, rate limits

## Result

`ActivityTailer` in `src/flock/watchdog/activity.py` and `office` CLI in `src/flock/office/cli.py` have been updated to ensure token usage and cost accounting are accurate and honest:

1. **Codex Model Resolution (§1):**
   - Codex session rollouts store active model name in `turn_context` records (`payload.model`) emitted once per turn, with fallback in `session_meta` (`payload.base_instructions.provenance.model`).
   - `ActivityTailer` tracks the active model ordinal per agent, resolving `gpt-5.6-sol` from `turn_context` rather than falling through to `unknown` (which previously left all Codex records `unpriced`).
   - *Honesty limit of fixture:* In `tests/fixtures/codex-session-captured.jsonl`, all three `turn_context` records carry `gpt-5.6-sol` because that session did not switch models. Mid-session model changes are verified by `test_codex_mid_session_model_change`.

2. **Last vs Total Token Usage (§2):**
   - `_codex_usage` extracts `last_token_usage` for turn-level incremental accounting, never cumulative `total_token_usage`.
   - Verified on live fixture `tests/fixtures/codex-session-captured.jsonl` where `last` vs `total` diverge on ordinals 141 (64,831 vs 533,066), 288 (80,177 vs 1,810,189), and 414 (111,751 vs 3,332,258). Summing turns yields 270,891 input tokens rather than an inflated 5.69M tokens.

3. **agy Not Measurable (§3):**
   - agy stores internal state in SQLite and Protobuf under `~/.gemini/antigravity-cli/` without token count metrics.
   - `office usage` and `office status` explicitly identify agy agents as `not measurable` (`not measurable (agy)` in status activity feed, `not measurable` under usage model column with `measurable: false` in JSON), preventing misleading zero, absent, or unknown reporting.

4. **Codex Rate Limits (§4):**
   - `_codex_usage` extracts `rate_limits` from `token_count` events (`primary.used_percent`, `primary.resets_at`, `plan_type`).
   - `office usage` captures and surfaces rate limits in table output (e.g. `18% (prolite)`) and under `"rate_limits"` in `--json` output.

5. **Attribution Question (§5):**
   - Decided to close the attribution question: the loss of attribution when delivery markers are trimmed past 500 entries is bounded by design, and omission of `stream_id` represents the graceful degradation specified in BUILD-82 §3. A counter that fires on uncorrelated records conflates normal turn execution with true loss, reproducing the `delivery_unverified` noise defect.

---

## Negative Controls (Falsifiability)

- **Control 1 (Model resolution from turn_context):**
  - *Mutation:* Revert `_codex_usage` to ignore `turn_context` model and use `payload.get("model") or "unknown"`.
  - *Observation:* `test_codex_captured_session_fixture_model_and_tokens` FAILED with `assert 'unknown' == 'gpt-5.6-sol'`.
- **Control 2 (Last vs Total token usage):**
  - *Mutation:* Change `_codex_usage` to read `total_token_usage` instead of `last_token_usage`.
  - *Observation:* `test_codex_captured_session_fixture_model_and_tokens` FAILED with `assert 533066 == 64831` on ordinal 141.
- **Control 3 (Agy unmeasurable in office status & usage):**
  - *Mutation:* Omit `agy` special handling in `office usage` and `office status`.
  - *Observation:* `test_office_usage_names_agy_agent_not_measurable` and `test_status_names_agy_agent_not_measurable` FAILED.
- **Control 4 (Codex rate limits):**
  - *Mutation:* Omit `rate_limits` extraction in `_codex_usage`.
  - *Observation:* `test_office_usage_surfaces_codex_rate_limits` and `test_codex_captured_session_fixture_model_and_tokens` FAILED.

---

## TEST SIGN-OFF — full repository gate

    claim            ActivityTailer resolves codex model from turn_context, extracts last_token_usage per turn, captures rate limits, and office status/usage names agy agents as not measurable
    source sha       07cabc3
    artefact         COMMIT
    host             local — hermetic in-memory Redis double, captured codex fixture, and unpiped test runner
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container build, accept.sh, live tenant, four-agent Nemotron live run, and live LLM API calls
    population       451 tests and 5 subtests; all repository tests collected (0 skipped)

    control          four property mutations documented above

    VERIFIED BY      PENDING — author of the change? NO
