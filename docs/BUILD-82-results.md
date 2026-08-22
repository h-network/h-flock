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
- `delivery.markers` in `src/flock/port/openers.py` retains 10,000 markers per
  agent, preventing silent trimming under load.
- Empty or trimmed marker histories omit `stream_id` directly without error.
- Deduplication and attribution sets (`_seen_requests` and `_attributed_markers`)
  are strictly scoped per-agent, preventing cross-agent suppression.
- Redis claim and emission are performed atomically via Lua transaction
  (`_EMIT_USAGE_LUA`), evaluating `SISMEMBER`, `XADD`, and `SADD` in a single
  atomic step. Emission failures in Redis abort before touching in-memory caches
  or Redis sets, eliminating both restart duplicate and permanent loss windows.

Pricing data is loaded from `container/config/pricing.json` (baked into the
image at `/app/container/config/pricing.json` and `/etc/flock/pricing.json`, with
an embedded fallback in `src/flock/office/pricing.py`). Operator-specified
`FLOCK_PRICING_FILE` configurations that are missing or contain malformed JSON
fail loudly with explicit `FileNotFoundError` or `ValueError` rather than
silently falling back. Model matching uses longest-prefix lookup (`claude-opus-4`
matches `claude-opus-4-8`). Models absent from pricing (such as local models)
are flagged explicitly as `unpriced` rather than reported as silent zero cost.

`office usage` (`src/flock/office/cli.py`) reads the aggregated tenant usage
stream from Redis, supports `--agent <name>`, `--since <ISO>`, and `--json`
output, and formats token counts (`k`, `M`, `-` for 0) with per-model and total
USD cost columns.

## TEST SIGN-OFF — full repository gate

    claim            ActivityTailer extracts 4 usage buckets, dedupes request IDs per agent via atomic Lua claim/emit, correlates delivery markers, prices via longest prefix with unpriced flags and fail-loud config, and office usage formats summaries
    source sha       ddab2d98b44ab24c130775d83c4b3cda50e7a082
    artefact         COMMIT
    host             local — hermetic in-memory Redis double, session fixtures, and citation reads
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container build, accept.sh, live tenant, four-agent Nemotron live run, and live LLM API calls
    population       428 tests and 5 subtests; all repository tests collected

    control          eight property mutations documented below
    expected locus   exact bucket extraction, same-agent deduplication, unpriced flagging, cache non-decorativeness, marker correlation/omission, cross-agent isolation, emission failure recovery, and fail-loud pricing configuration
    observed locus   same for all eight
    signature        each named test failed with exit 1 on property mutation and passed upon restoration

    evidence         /tmp/build82-pytest.log sha256 f7188a18b57d1c9a29f61ccadf44ca488443f8de1bbefd1ddd1864866fb8f2b7

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
    evidence         /tmp/build82-control1.log sha256 c3c314100d2d6b66238e2deeba75e9e3133772b03cff28abcd173c11849de4ee

Restored behavior extracts 812 input, 40,311 cache_read, 1,902 cache_write, and
1,204 output tokens, computing exactly $0.198609 USD.

### 2. Request ID deduplication (same agent)

Property mutation: disabled `_seen_requests` check in `ActivityTailer._emit_usage`.

    command          pytest -q tests/test_usage.py::test_duplicate_request_in_one_file_is_counted_once
    exit status      1, read unpiped
    expected locus   ActivityTailer._emit_usage deduplication check in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py emitted records count
    signature        AssertionError: Duplicate request ID was emitted more than once (len=2, expected 1)
    evidence         /tmp/build82-control2.log sha256 4a0b20700b43a256d43b66998cea19ea78022b10d258912e97159dd59041c76a

Restored behavior suppresses duplicate request records and emits exactly one usage event.

### 3. Unpriced model flagging

Property mutation: changed missing model pricing to return `(0.00, True)` instead of `(None, False)`.

    command          pytest -q tests/test_usage.py::test_unpriced_model_is_flagged_unpriced_not_zero
    exit status      1, read unpiped
    expected locus   calculate_cost missing model branch in src/flock/office/pricing.py
    observed locus   tests/test_usage.py is_priced assertion
    signature        AssertionError: assert True is False
    evidence         /tmp/build82-control3.log sha256 d3013e34fc8cb25ab1eab2255316fa6c9f82d8512bf566df5063387be2732d74

Restored behavior flags `nemotron-lightning` as `is_priced=False` and cost `None`, displaying `unpriced` in `office usage`.

### 4. Cache buckets non-decorativeness

Property mutation: zeroed out `cache_read` and `cache_write` in `calculate_cost`.

    command          pytest -q tests/test_usage.py::test_cache_buckets_are_not_decorative
    exit status      1, read unpiped
    expected locus   calculate_cost token multiplication in src/flock/office/pricing.py
    observed locus   tests/test_usage.py difference assertion
    signature        AssertionError: assert 0.0 == pytest.approx(2.4375)
    evidence         /tmp/build82-control4.log sha256 da0d6df8dc7eb24b0e487bd505b8550034f3274acc4bbd9eefd9708e863a3000

Restored behavior includes cache buckets and reflects a $2.4375 USD cost difference on 1M cache_read / 50k cache_write tokens.

### 5. Delivery marker correlation and omission

Property mutation: removed `_attributed_markers` tracking so every subsequent usage record reused the preceding marker.

    command          pytest -q tests/test_usage.py::test_correlation_joins_marker_and_omits_unattributable_usage
    exit status      1, read unpiped
    expected locus   ActivityTailer._correlate_delivery attribution check in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py second record stream_id assertion
    signature        AssertionError: 'stream_id' in records[1]
    evidence         /tmp/build82-control5.log sha256 5c49b3aebeb36e08dd247ef04efe0b0cdcac43edee785b2aae62a87c416b7fa8

Restored behavior joins the first usage record after a marker and omits `stream_id` and `correlation_id` from subsequent turns that lacked new delivery markers.

### 6. Cross-agent deduplication isolation

Property mutation: made `_seen_requests` a single global set across all agents.

    command          pytest -q tests/test_usage.py::test_same_request_id_across_different_agents_is_not_suppressed
    exit status      1, read unpiped
    expected locus   ActivityTailer._seen_requests per-agent mapping in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py distinct agent count assertion
    signature        AssertionError: Expected 2 records (1 per agent), got 1
    evidence         /tmp/build82-control6.log sha256 92242bc9f191bbc8f25fa732615b334689ee6939b7dd7412a5b183abc9bf9b70

Restored behavior isolates request tracking per agent so shared or colliding request IDs across agents emit independently.

### 7. Emission failure recovery and zero premature commit

Property mutation: marked request as seen in memory even when Redis emission failed.

    command          pytest -q tests/test_usage.py::test_emission_failure_does_not_prematurely_commit_seen_request
    exit status      1, read unpiped
    expected locus   ActivityTailer._emit_usage exception handler in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py seen check assertion
    signature        AssertionError: 'msg_recoverable_001' in tailer._seen_requests['bus']
    evidence         /tmp/build82-control7.log sha256 ab10ae2d6a20487018b58bb8a37e9c30e9004d24e9d35b05d44b98869f7ee69c

Restored behavior aborts on Redis write failure without marking the request seen, allowing successful replay on restart.

### 8. Explicit pricing configuration failure

Property mutation: swallowed `FileNotFoundError` in `load_pricing` to silently fall back.

    command          pytest -q tests/test_usage.py::test_explicit_flock_pricing_file_missing_or_malformed_fails_loudly
    exit status      1, read unpiped
    expected locus   load_pricing explicit env handler in src/flock/office/pricing.py
    observed locus   tests/test_usage.py pytest.raises assertion
    signature        Failed: DID NOT RAISE <class 'FileNotFoundError'>
    evidence         /tmp/build82-control8.log sha256 a6ae0635ea0175160de8fd2b5387aec6494ba75015633e699f17d58a64c5adcc

Restored behavior fails loudly when an operator specifies an invalid or missing `FLOCK_PRICING_FILE`.

## Citation gate

    source sha       ddab2d98b44ab24c130775d83c4b3cda50e7a082
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    population       676 citations, 550 unique
    result           0 hard failures, 49 near misses
    evidence         /tmp/build82-citations.log sha256 4b707acd25093c547be65cec2ee04adb589c443411bbdcca5fa00d58f2f1f737
