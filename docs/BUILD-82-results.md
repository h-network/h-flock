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
  markers omit `stream_id` and `correlation_id`.
- `pending.verify` and `delivery.markers` in `src/flock/port/openers.py` retain
  markers without length-based trimming, preserving unresolved markers until
  verified and correlated.
- Empty or trimmed marker histories omit `stream_id` directly without error.
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

    claim            ActivityTailer extracts 4 usage buckets, dedupes request IDs per agent via atomic Lua claim/emit, correlates delivery markers, prices via longest prefix with unpriced flags and fail-loud config, and office usage reads real RESP xrange and formats summaries
    source sha       8ab9db43ac2d864a3d6f4cb9d8a92dfed5b885cd
    artefact         COMMIT
    host             local — hermetic in-memory Redis double, real local redis-server probes, session fixtures, and citation reads
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container build, accept.sh, live tenant, four-agent Nemotron live run, and live LLM API calls
    population       432 tests and 5 subtests; all repository tests collected

    control          ten property mutations documented below
    expected locus   exact bucket extraction, same-agent deduplication, unpriced flagging, cache non-decorativeness, marker correlation/omission, cross-agent isolation, emission failure recovery, fail-loud pricing configuration, RESP xrange execution, and real Lua atomic claim
    observed locus   same for all ten
    signature        each named test failed with exit 1 on property mutation and passed upon restoration

    evidence         /tmp/build82-pytest.log sha256 50324ff2a500ec33eeadf045a692ecde1dd32cadb3d33828257ed4d5bb745d07

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
    evidence         /tmp/build82-control1.log sha256 b1c2240490b211af7a2ec7756bdff4986141b997c4241ce88956984310d1b1ad

Restored behavior extracts 812 input, 40,311 cache_read, 1,902 cache_write, and
1,204 output tokens, computing exactly $0.198609 USD.

### 2. Request ID deduplication (same agent)

Property mutation: disabled `SISMEMBER` in `_EMIT_USAGE_LUA` and in-memory `_seen_requests` check in `ActivityTailer._emit_usage`.

    command          pytest -q tests/test_usage.py::test_duplicate_request_in_one_file_is_counted_once
    exit status      1, read unpiped
    expected locus   ActivityTailer._emit_usage deduplication check in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py emitted records count
    signature        AssertionError: Duplicate request ID was emitted more than once (len=2, expected 1)
    evidence         /tmp/build82-control2.log sha256 a3d545c3519b4422908ba66b5fc471b22ac7b57b5c896a9dca76c7a53d728b09

Restored behavior suppresses duplicate request records and emits exactly one usage event.

### 3. Unpriced model flagging

Property mutation: changed missing model pricing to return `(0.00, True)` instead of `(None, False)`.

    command          pytest -q tests/test_usage.py::test_unpriced_model_is_flagged_unpriced_not_zero
    exit status      1, read unpiped
    expected locus   calculate_cost missing model branch in src/flock/office/pricing.py
    observed locus   tests/test_usage.py is_priced assertion
    signature        AssertionError: assert True is False
    evidence         /tmp/build82-control3.log sha256 4b71a2240fd02e4dd09db6ab185ea74b49de5766253b17f18cc9613d802baf94

Restored behavior flags `nemotron-lightning` as `is_priced=False` and cost `None`, displaying `unpriced` in `office usage`.

### 4. Cache buckets non-decorativeness

Property mutation: zeroed out `cache_read` and `cache_write` in `calculate_cost`.

    command          pytest -q tests/test_usage.py::test_cache_buckets_are_not_decorative
    exit status      1, read unpiped
    expected locus   calculate_cost token multiplication in src/flock/office/pricing.py
    observed locus   tests/test_usage.py difference assertion
    signature        AssertionError: assert 0.0 == pytest.approx(2.4375)
    evidence         /tmp/build82-control4.log sha256 851df091437b387791d5d5f2a002b7ddba7cb41180251c2d0405fd8c9a2e4d40

Restored behavior includes cache buckets and reflects a $2.4375 USD cost difference on 1M cache_read / 50k cache_write tokens.

### 5. Delivery marker correlation and omission

Property mutation: removed `_attributed_markers` tracking so every subsequent usage record reused the preceding marker.

    command          pytest -q tests/test_usage.py::test_correlation_joins_marker_and_omits_unattributable_usage
    exit status      1, read unpiped
    expected locus   ActivityTailer._correlate_delivery attribution check in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py second record stream_id assertion
    signature        AssertionError: 'stream_id' in records[1]
    evidence         /tmp/build82-control5.log sha256 933ae4d3ffede0419667bf5de9b062b54125a4c1fd2ddd2b8615528568e500ad

Restored behavior joins the first usage record after a marker and omits `stream_id` and `correlation_id` from subsequent turns that lacked new delivery markers.

### 6. Cross-agent deduplication isolation

Property mutation: made `_seen_requests` a single global set across all agents.

    command          pytest -q tests/test_usage.py::test_same_request_id_across_different_agents_is_not_suppressed
    exit status      1, read unpiped
    expected locus   ActivityTailer._seen_requests per-agent mapping in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py distinct agent count assertion
    signature        AssertionError: Expected 2 records (1 per agent), got 1
    evidence         /tmp/build82-control6.log sha256 f9d3ea3938b12360d2d3656496064385f157fbcf4dff542ccdeaf63031cc9ea0

Restored behavior isolates request tracking per agent so shared or colliding request IDs across agents emit independently.

### 7. Emission failure recovery and zero premature commit

Property mutation: marked request as seen in memory even when Redis emission failed.

    command          pytest -q tests/test_usage.py::test_emission_failure_does_not_prematurely_commit_seen_request
    exit status      1, read unpiped
    expected locus   ActivityTailer._emit_usage exception handler in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py seen check assertion
    signature        AssertionError: 'msg_recoverable_001' in tailer._seen_requests['bus']
    evidence         /tmp/build82-control7.log sha256 ec7a83a35a6ce113640c6d4f69b4c162762224b9f5151f016af6d1700a0dc970

Restored behavior aborts on Redis write failure without marking the request seen, allowing successful replay on restart.

### 8. Explicit pricing configuration failure

Property mutation: swallowed `FileNotFoundError` in `load_pricing` to silently fall back.

    command          pytest -q tests/test_usage.py::test_explicit_flock_pricing_file_missing_or_malformed_fails_loudly
    exit status      1, read unpiped
    expected locus   load_pricing explicit env handler in src/flock/office/pricing.py
    observed locus   tests/test_usage.py pytest.raises assertion
    signature        Failed: DID NOT RAISE <class 'FileNotFoundError'>
    evidence         /tmp/build82-control8.log sha256 7d2322b458a39e2973b3e5fe8de437836f7b7f14fda2ee2c9b76bf9a5b2799fe

Restored behavior fails loudly when an operator specifies an invalid or missing `FLOCK_PRICING_FILE`.

### 9. Real RESP xrange execution in office usage

Property mutation: renamed `xrange` to `_disabled_xrange` in `src/flock/bus/resp.py`.

    command          pytest -q tests/test_usage.py::test_office_usage_runs_against_resp_redis_client
    exit status      1, read unpiped
    expected locus   Redis.xrange definition in src/flock/bus/resp.py
    observed locus   src/flock/office/cli.py _usage_command direct xrange invocation
    signature        AttributeError: 'Redis' object has no attribute 'xrange'
    evidence         /tmp/build82-control9.log sha256 3c0274780cf8ff7564f60fdbb41237f3f3749ee6b785971570dcd253e0b86c26

Restored behavior defines `xrange` on `flock.bus.resp.Redis` and executes stream reporting without silent swallows.

### 10. Real Lua atomic claim and emission script execution

Property mutation: removed `redis.call("SADD", seen_key, request_id)` from `_EMIT_USAGE_LUA`.

    command          pytest -q tests/test_usage.py::test_lua_script_atomic_claim_and_replay_dedupe_on_real_redis
    exit status      1, read unpiped
    expected locus   _EMIT_USAGE_LUA SADD claim in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py second emission deduplication assertion
    signature        AssertionError: assert 1 == 0
    evidence         /tmp/build82-control10.log sha256 e97143f8bf9c877bc8983fbef55ab16a81014bd79190bcfc03ef507535c77fff

Restored behavior atomically claims request IDs inside the Redis Lua transaction on real redis-server, suppressing replay duplication.

## Citation gate

    source sha       8ab9db43ac2d864a3d6f4cb9d8a92dfed5b885cd
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    population       676 citations, 550 unique
    result           0 hard failures, 49 near misses
    evidence         /tmp/build82-citations.log sha256 4b707acd25093c547be65cec2ee04adb589c443411bbdcca5fa00d58f2f1f737
