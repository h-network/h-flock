# BUILD 82 results — usage and cost records

## Result

`ActivityTailer` in `src/flock/watchdog/activity.py` extracts token usage
records directly during log-tailing passes over Claude (`message.usage`) and
Codex (`token_count` / payload usage) session files. Each usage record emits the
four canonical token buckets (`input`, `cache_read`, `cache_write`, `output`)
under `writer: "usage"` and dedupes repeated session entries by request ID per
agent.

The correlation join compares each usage record's timestamp against the agent's
preceding delivery markers:
- The first usage record after a delivery marker for `stream_id` S (and before
  the next marker for that agent) is attributed to S, attaching `stream_id` and
  `correlation_id`.
- Multiple messages received during a single agent turn produce one usage
  record attributed to the latest marker; subsequent usage events without new
  markers omit `stream_id` and `correlation_id` (degrading gracefully to
  unattributed usage as per section 3 rather than guessing).
- `delivery.markers` in `src/flock/port/openers.py` has a documented ceiling of
  500 markers and `pending.verify` has a documented ceiling of 100 markers. When
  a marker is absent or trimmed under load, the usage record cleanly omits
  `stream_id` and `_EMIT_USAGE_LUA` atomically increments the agent's observable
  counter `usage.unattributed`, making attribution loss transparent to operators.
- Deduplication and attribution sets (`_seen_requests` and `_attributed_markers`)
  are strictly scoped per-agent, preventing cross-agent suppression.
- Redis claim and emission are performed atomically via Lua transaction
  (`_EMIT_USAGE_LUA`), evaluating `SISMEMBER`, `XADD`, and `SADD` in a single
  atomic step. Emission failures in Redis abort before touching in-memory caches
  or Redis sets, eliminating both restart duplicate and permanent loss windows.

`src/flock/bus/resp.py` implements `xrange` and `xlen` over the synchronous
RESP2 client, and `office usage` (`src/flock/office/cli.py`) reads the
aggregated tenant usage stream directly without silent empty-table fallbacks.
`office usage` supports `--agent <name>`, `--since <ISO>`, and `--json`
output, and formats token counts (`k`, `M`, `-` for 0) with per-model and total
USD cost columns.

Pricing data is loaded from `container/config/pricing.json` (baked into the
image at `/app/container/config/pricing.json` and `/etc/flock/pricing.json`, with
an embedded fallback in `src/flock/office/pricing.py`). Operator-specified
`FLOCK_PRICING_FILE` configurations that are missing or contain malformed JSON
fail loudly with explicit `FileNotFoundError` or `ValueError` rather than
silently falling back. Model matching uses longest-prefix lookup (`claude-opus-4`
matches `claude-opus-4-8`). Models absent from pricing (such as local models)
are flagged explicitly as `unpriced` rather than reported as silent zero cost.

## TEST SIGN-OFF — full repository gate

    claim            ActivityTailer extracts 4 usage buckets, dedupes request IDs per agent via atomic Lua claim/emit, correlates delivery markers with observable unattributed counters, prices via longest prefix with unpriced flags and fail-loud config, and office usage reads real RESP xrange and formats summaries
    source sha       471c1d885f4e284f8a7547ef056c6b6cb943492f
    artefact         COMMIT
    host             local — hermetic in-memory Redis double, real ephemeral redis-server (/usr/bin/redis-server), session fixtures, and citation reads
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container build, accept.sh, live tenant, four-agent Nemotron live run, and live LLM API calls
    population       433 tests and 5 subtests; all repository tests collected (real redis-server Lua atomic claim test RAN, 0 skipped)

    control          ten property mutations documented below
    expected locus   exact bucket extraction, same-agent deduplication, unpriced flagging, cache non-decorativeness, marker correlation/omission, cross-agent isolation, emission failure recovery, fail-loud pricing configuration, RESP xrange execution, and real Lua atomic claim on real redis-server
    observed locus   same for all ten
    signature        each named test failed with exit 1 on property mutation and passed upon restoration

    evidence         /tmp/build82-pytest.log sha256 3e2e314d9e3865ac66d2c51a89c9d43f0576c2d1c743ce5f8e9fb9cbc7ae77c8

    verdict          PASS
    VERIFIED BY      PENDING — independent lane required before merge — author of the change? NO

## Controls

### 1. Claude fixture extraction and exact USD pricing

Property mutation: mutated `claude-opus-4` cache_read pricing rate from 1.50 to 0.00 in `container/config/pricing.json`.

    command          pytest -q tests/test_usage.py::test_claude_fixture_extracts_four_buckets_and_exact_usd
    exit status      1, read unpiped
    expected locus   calculate_cost rate lookup in src/flock/office/pricing.py
    observed locus   tests/test_usage.py assertion on expected cost
    signature        AssertionError: assert 0.1381425 == 0.198609
    evidence         /tmp/build82-control1.log sha256 61608392391c324d1e6587fc8a1e0b67baded59d3b9c95573d192217f0ef64e6

Restored behavior extracts 812 input, 40,311 cache_read, 1,902 cache_write, and
1,204 output tokens, computing exactly $0.198609 USD.

### 2. Request ID deduplication (same agent)

Property mutation: disabled `SISMEMBER` in `_EMIT_USAGE_LUA` and in-memory `_seen_requests` check in `ActivityTailer._emit_usage`.

    command          pytest -q tests/test_usage.py::test_duplicate_request_in_one_file_is_counted_once
    exit status      1, read unpiped
    expected locus   ActivityTailer._emit_usage deduplication check in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py emitted records count
    signature        AssertionError: Duplicate request ID was emitted more than once (len=2, expected 1)
    evidence         /tmp/build82-control2.log sha256 736da823de29cd42ed0037181155f9074256e31246d8e2bea9fada6a6f068a0b

Restored behavior suppresses duplicate request records and emits exactly one usage event.

### 3. Unpriced model flagging

Property mutation: changed missing model pricing to return `(0.00, True)` instead of `(None, False)`.

    command          pytest -q tests/test_usage.py::test_unpriced_model_is_flagged_unpriced_not_zero
    exit status      1, read unpiped
    expected locus   calculate_cost missing model branch in src/flock/office/pricing.py
    observed locus   tests/test_usage.py is_priced assertion
    signature        AssertionError: assert True is False
    evidence         /tmp/build82-control3.log sha256 faf7d0fa6e1a33335a66b5f6d3a2396c44adaae0e0dc853ca6c005e706c23ed3

Restored behavior flags `nemotron-lightning` as `is_priced=False` and cost `None`, displaying `unpriced` in `office usage`.

### 4. Cache buckets non-decorativeness

Property mutation: zeroed out `cache_read` and `cache_write` in `calculate_cost`.

    command          pytest -q tests/test_usage.py::test_cache_buckets_are_not_decorative
    exit status      1, read unpiped
    expected locus   calculate_cost token multiplication in src/flock/office/pricing.py
    observed locus   tests/test_usage.py difference assertion
    signature        AssertionError: assert 0.0 == pytest.approx(2.4375)
    evidence         /tmp/build82-control4.log sha256 516e3d494fae8ceabf7f2725185ce0c2a23caec73a2394694ba4cad524757291

Restored behavior includes cache buckets and reflects a $2.4375 USD cost difference on 1M cache_read / 50k cache_write tokens.

### 5. Delivery marker correlation and omission

Property mutation: removed `_attributed_markers` tracking so every subsequent usage record reused the preceding marker.

    command          pytest -q tests/test_usage.py::test_correlation_joins_marker_and_omits_unattributable_usage
    exit status      1, read unpiped
    expected locus   ActivityTailer._correlate_delivery attribution check in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py second record stream_id assertion
    signature        AssertionError: 'stream_id' in records[1]
    evidence         /tmp/build82-control5.log sha256 32d8d26d34f311e7a27424fde9abb0175fdb7e295cf545152076a135410bf3cc

Restored behavior joins the first usage record after a marker and omits `stream_id` and `correlation_id` from subsequent turns that lacked new delivery markers.

### 6. Cross-agent deduplication isolation

Property mutation: made `_seen_requests` a single global set across all agents.

    command          pytest -q tests/test_usage.py::test_same_request_id_across_different_agents_is_not_suppressed
    exit status      1, read unpiped
    expected locus   ActivityTailer._seen_requests per-agent mapping in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py distinct agent count assertion
    signature        AssertionError: Expected 2 records (1 per agent), got 1
    evidence         /tmp/build82-control6.log sha256 594803221d4e900c34b19c1bd3da10d08fae323a388def46365389946ec3a9df

Restored behavior isolates request tracking per agent so shared or colliding request IDs across agents emit independently.

### 7. Emission failure recovery and zero premature commit

Property mutation: marked request as seen in memory even when Redis emission failed.

    command          pytest -q tests/test_usage.py::test_emission_failure_does_not_prematurely_commit_seen_request
    exit status      1, read unpiped
    expected locus   ActivityTailer._emit_usage exception handler in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py seen check assertion
    signature        AssertionError: 'msg_recoverable_001' in tailer._seen_requests['bus']
    evidence         /tmp/build82-control7.log sha256 b92f497e0fbad7b6f4a213d9c54d4f0f61dd101bf3f3137f689423373659d21d

Restored behavior aborts on Redis write failure without marking the request seen, allowing successful replay on restart.

### 8. Explicit pricing configuration failure

Property mutation: swallowed `FileNotFoundError` in `load_pricing` to silently fall back.

    command          pytest -q tests/test_usage.py::test_explicit_flock_pricing_file_missing_or_malformed_fails_loudly
    exit status      1, read unpiped
    expected locus   load_pricing explicit env handler in src/flock/office/pricing.py
    observed locus   tests/test_usage.py pytest.raises assertion
    signature        Failed: DID NOT RAISE <class 'FileNotFoundError'>
    evidence         /tmp/build82-control8.log sha256 617853d597b07fabbe57e31604f2eb3f0a6ec4426d09552f9541a34aa5697ec1

Restored behavior fails loudly when an operator specifies an invalid or missing `FLOCK_PRICING_FILE`.

### 9. Real RESP xrange execution in office usage

Property mutation: renamed `xrange` to `_disabled_xrange` in `src/flock/bus/resp.py`.

    command          pytest -q tests/test_usage.py::test_office_usage_runs_against_resp_redis_client
    exit status      1, read unpiped
    expected locus   Redis.xrange definition in src/flock/bus/resp.py
    observed locus   src/flock/office/cli.py _usage_command direct xrange invocation
    signature        AttributeError: 'Redis' object has no attribute 'xrange'
    evidence         /tmp/build82-control9.log sha256 b416096e393ece12754acf1068b395229413c767c15a1e012cf5551b62d132fe

Restored behavior defines `xrange` on `flock.bus.resp.Redis` and executes stream reporting without silent swallows.

### 10. Real Lua atomic claim and emission script execution on real redis-server

Property mutation: removed `redis.call("SADD", seen_key, request_id)` from `_EMIT_USAGE_LUA`.

    command          pytest -q tests/test_usage.py::test_lua_script_atomic_claim_and_replay_dedupe_on_real_redis
    exit status      1, read unpiped
    expected locus   _EMIT_USAGE_LUA SADD claim in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py sismember claim assertion against real redis-server
    signature        AssertionError: assert 0 (where 0 = sismember(seen_key, 'req_atomic_001'))
    evidence         /tmp/build82-control10.log sha256 e487dcc7fd78ba8feb7b35e564da6d90b1656cca262136723c1eb794e8d69dad

Restored behavior atomically claims request IDs inside the Redis Lua transaction on real `/usr/bin/redis-server`, suppressing replay duplication.

## Citation gate

    source sha       471c1d885f4e284f8a7547ef056c6b6cb943492f
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    population       676 citations, 550 unique
    result           0 hard failures, 49 near misses
    evidence         /tmp/build82-citations.log sha256 4b707acd25093c547be65cec2ee04adb589c443411bbdcca5fa00d58f2f1f737
