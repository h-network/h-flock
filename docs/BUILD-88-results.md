# BUILD 88 results — usage truth: codex model, last-not-total, agy unmeasurable, rate limits

## Result

`ActivityTailer` in `src/flock/watchdog/activity.py` and `office` CLI in `src/flock/office/cli.py` have been updated to ensure token usage and cost accounting are accurate, session-scoped, and recoverable:

1. **Codex Model Resolution & Session Lifecycle (§1):**
   - Model state is strictly scoped to the session file path (`_codex_session_models[path_text]`), never persisted globally per agent across rotated sessions.
   - `session_meta` (`payload.base_instructions.provenance.model`) is authoritative for its own session file when beginning to tail that rollout.
   - Subsequent `turn_context` records (`payload.model`) update the active model for succeeding turns in that session.
   - On watchdog restart at a persisted mid-session offset, `_codex_model_at_offset` scans pre-offset records to reconstruct the active model, preventing fallthrough to `"unknown"` when resuming after `turn_context`.
   - *Honesty limit of fixture:* In `tests/fixtures/codex-session-captured.jsonl`, all three `turn_context` records carry `gpt-5.6-sol` because that session did not switch models. Mid-session model changes and session rotation are verified by `test_codex_mid_session_model_change` and `test_codex_session_rotation_resets_model`.

2. **Session Ownership Contract:**
   - `_codex_session_belongs_to` retains strict `/workdir/{agent}` ownership based on line 1 `session_meta` cwd, preventing arbitrary paths (e.g. `/tmp/sme-1`) from being claimed.

3. **Last vs Total Token Usage (§2):**
   - `_codex_usage` extracts `last_token_usage` for turn-level incremental accounting, never cumulative `total_token_usage`.
   - Verified on live fixture `tests/fixtures/codex-session-captured.jsonl` where `last` vs `total` diverge on ordinals 141 (64,831 vs 533,066), 288 (80,177 vs 1,810,189), and 414 (111,751 vs 3,332,258). Summing turns yields 270,891 input tokens rather than an inflated 5.69M tokens.

4. **agy Not Measurable (§3):**
   - agy stores internal state in SQLite and Protobuf under `~/.gemini/antigravity-cli/` without token count metrics.
   - `office usage` and `office status` explicitly identify agy agents as `not measurable` (`not measurable (agy)` in status activity feed, `not measurable` under usage model column with `measurable: false` in JSON), preventing misleading zero, absent, or unknown reporting.

5. **Codex Rate Limits (§4):**
   - `_codex_usage` extracts `rate_limits` from `token_count` events (`primary.used_percent`, `primary.resets_at`, `plan_type`).
   - `office usage` captures and surfaces rate limits in table output (e.g. `18% (prolite)`) and under `"rate_limits"` in `--json` output.

6. **Attribution Question (§5):**
   - Decided to close the attribution question: the loss of attribution when delivery markers are trimmed past 500 entries is bounded by design, and omission of `stream_id` represents the graceful degradation specified in BUILD-82 §3. A counter that fires on uncorrelated records conflates normal turn execution with true loss, reproducing the `delivery_unverified` noise defect.

---

## Negative Controls (Falsifiability)

- **Control 1 (Model resolution from turn_context):**
  - *Mutation:* Revert `_codex_usage` to ignore `turn_context` model and use `payload.get("model") or "unknown"`.
  - *Observed locus:* `test_codex_captured_session_fixture_model_and_tokens` FAILED with `assert 'unknown' == 'gpt-5.6-sol'`.
- **Control 2 (Last vs Total token usage):**
  - *Mutation:* Change `_codex_usage` to read `total_token_usage` instead of `last_token_usage`.
  - *Observed locus:* `test_codex_captured_session_fixture_model_and_tokens` FAILED with `assert 533066 == 64831` on ordinal 141.
- **Control 3 (Session rotation model reset):**
  - *Mutation:* Leak previous session's model across rotation without path-scoped reset.
  - *Observed locus:* `test_codex_session_rotation_resets_model` FAILED with `assert 'gpt-5.6-sol' == 'gpt-5-codex'`.
- **Control 4 (Offset restart recovery):**
  - *Mutation:* Omit `_codex_model_at_offset` recovery upon resuming at mid-session offset.
  - *Observed locus:* `test_codex_restart_at_mid_session_offset_recovers_model` FAILED with `assert 'unknown' == 'gpt-5.6-sol'`.
- **Control 5 (Ownership strictly rejects arbitrary cwd):**
  - *Mutation:* Accept arbitrary cwd ending with `/{agent}`.
  - *Observed locus:* `test_codex_session_ownership_rejects_arbitrary_cwd` FAILED with `assert True is False` on `/tmp/sme-2`.
- **Control 6 (Codex rate limits):**
  - *Mutation:* Omit `rate_limits` extraction in `_codex_usage`.
  - *Observed locus:* `test_office_usage_surfaces_codex_rate_limits` FAILED.

---

## TEST SIGN-OFF — full repository gate

    claim            ActivityTailer resolves codex model from turn_context, scopes model to session path with offset recovery, extracts last_token_usage per turn, captures rate limits, and office status/usage names agy agents as not measurable
    source sha       af3f8ef
    artefact         COMMIT
    host             local — hermetic in-memory Redis double, captured codex fixture, and unpiped test runner
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container build, accept.sh, live tenant, four-agent Nemotron live run, and live LLM API calls
    population       454 tests and 5 subtests; all repository tests collected (0 skipped)

    control          six property mutations documented above
    evidence         /tmp/build88-negative.log sha256 44a6b7395eb5e54bb2907437c9001ecafc36a8fab72ed5bbd3995b3c4957c24f
                     /tmp/build88-pytest.log sha256 1e836c9bb591688e946e6da5ee7fbfe25daa9de61eb05eec8ac4128381fe7bcf

    verdict          PASS
    VERIFIED BY      PENDING — independent lane required before merge

## Citation gate

    source sha       af3f8ef
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    result           0 hard failures, 45 near misses
    evidence         /tmp/build88-citations.log sha256 a03211736acb84d4589c79223c912ed688637866cbcd326210dd2c1ff4a38367
