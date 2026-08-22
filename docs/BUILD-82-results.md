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
- Empty or trimmed marker histories omit `stream_id` directly without error.
- Deduplication and attribution sets (`_seen_requests` and `_attributed_markers`)
  are strictly scoped per-agent, preventing cross-agent suppression.
- Redis set updates (`sadd`) are performed after stream emission (`xadd`),
  eliminating the SADD-before-XADD loss window.

Pricing data is loaded from `container/config/pricing.json` (baked into the
image at `/app/container/config/pricing.json` and `/etc/flock/pricing.json`, with
an embedded fallback in `src/flock/office/pricing.py`). Model matching uses
longest-prefix lookup (`claude-opus-4` matches `claude-opus-4-8`). Models absent
from pricing (such as local models) are flagged explicitly as `unpriced` rather
than reported as silent zero cost.

`office usage` (`src/flock/office/cli.py`) reads the aggregated tenant usage
stream from Redis, supports `--agent <name>`, `--since <ISO>`, and `--json`
output, and formats token counts (`k`, `M`, `-` for 0) with per-model and total
USD cost columns.

## TEST SIGN-OFF — full repository gate

    claim            ActivityTailer extracts 4 usage buckets, dedupes request IDs per agent, correlates delivery markers, prices via longest prefix with unpriced flags, and office usage formats summaries
    source sha       87ba652c3d8db2a53ab2a3fcbee59ff88ad73626
    artefact         COMMIT
    host             local — hermetic in-memory Redis double, session fixtures, and citation reads
    command          python3 -m pytest -q
    exit status      0, read unpiped

    EXCLUDED         container build, accept.sh, live tenant, four-agent Nemotron live run, and live LLM API calls
    population       426 tests and 5 subtests; all repository tests collected

    control          six property mutations documented below
    expected locus   exact bucket extraction, same-agent deduplication, unpriced flagging, cache non-decorativeness, marker correlation/omission, and cross-agent isolation
    observed locus   same for all six
    signature        each named test failed with exit 1 on property mutation and passed upon restoration

    evidence         /tmp/build82-pytest.log sha256 1ff1231ea79b3fcac95a6c19943443c51bcdca956ac856b48f74675d39802825

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
    evidence         /tmp/build82-control1.log sha256 a95c0935685c6cb072c90e2938c7eee0e08fe366a7ac42de66f5c5b4cf0bd24d

Restored behavior extracts 812 input, 40,311 cache_read, 1,902 cache_write, and
1,204 output tokens, computing exactly $0.198609 USD.

### 2. Request ID deduplication (same agent)

Property mutation: disabled `_seen_requests` check in `ActivityTailer._emit_usage`.

    command          pytest -q tests/test_usage.py::test_duplicate_request_in_one_file_is_counted_once
    exit status      1, read unpiped
    expected locus   ActivityTailer._emit_usage deduplication check in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py emitted records count
    signature        AssertionError: Duplicate request ID was emitted more than once (len=2, expected 1)
    evidence         /tmp/build82-control2.log sha256 b9807827e8649ce303fc9695ffa63c7136ae33a8303afbd849f52d908bf4ba3d

Restored behavior suppresses duplicate request records and emits exactly one usage event.

### 3. Unpriced model flagging

Property mutation: changed missing model pricing to return `(0.00, True)` instead of `(None, False)`.

    command          pytest -q tests/test_usage.py::test_unpriced_model_is_flagged_unpriced_not_zero
    exit status      1, read unpiped
    expected locus   calculate_cost missing model branch in src/flock/office/pricing.py
    observed locus   tests/test_usage.py is_priced assertion
    signature        AssertionError: assert True is False
    evidence         /tmp/build82-control3.log sha256 eab98b52705a1a382d2b9165cb498b64e0bb1f1619c3d3cee546a59e8f41ec09

Restored behavior flags `nemotron-lightning` as `is_priced=False` and cost `None`, displaying `unpriced` in `office usage`.

### 4. Cache buckets non-decorativeness

Property mutation: zeroed out `cache_read` and `cache_write` in `calculate_cost`.

    command          pytest -q tests/test_usage.py::test_cache_buckets_are_not_decorative
    exit status      1, read unpiped
    expected locus   calculate_cost token multiplication in src/flock/office/pricing.py
    observed locus   tests/test_usage.py difference assertion
    signature        AssertionError: assert 0.0 == pytest.approx(2.4375)
    evidence         /tmp/build82-control4.log sha256 2cb57b3848031b4ffec71d1ad3a227f3ac155f043a8d427088a8e1fb55620a65

Restored behavior includes cache buckets and reflects a $2.4375 USD cost difference on 1M cache_read / 50k cache_write tokens.

### 5. Delivery marker correlation and omission

Property mutation: removed `_attributed_markers` tracking so every subsequent usage record reused the preceding marker.

    command          pytest -q tests/test_usage.py::test_correlation_joins_marker_and_omits_unattributable_usage
    exit status      1, read unpiped
    expected locus   ActivityTailer._correlate_delivery attribution check in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py second record stream_id assertion
    signature        AssertionError: 'stream_id' in records[1]
    evidence         /tmp/build82-control5.log sha256 3632267be6beaf75553151a480c37e16ee0d013b3aaf975559c4f39668ed4603

Restored behavior joins the first usage record after a marker and omits `stream_id` and `correlation_id` from subsequent turns that lacked new delivery markers.

### 6. Cross-agent deduplication isolation

Property mutation: made `_seen_requests` a single global set across all agents.

    command          pytest -q tests/test_usage.py::test_same_request_id_across_different_agents_is_not_suppressed
    exit status      1, read unpiped
    expected locus   ActivityTailer._seen_requests per-agent mapping in src/flock/watchdog/activity.py
    observed locus   tests/test_usage.py distinct agent count assertion
    signature        AssertionError: Expected 2 records (1 per agent), got 1
    evidence         /tmp/build82-control6.log sha256 90b1920dfde191af64beeb96a2839a12a157a9ff0d420bac63ceb2626a11f685

Restored behavior isolates request tracking per agent so shared or colliding request IDs across agents emit independently.

## Citation gate

    source sha       87ba652c3d8db2a53ab2a3fcbee59ff88ad73626
    command          python3 tools/check_citations.py
    exit status      0, read unpiped
    population       676 citations, 550 unique
    result           0 hard failures, 49 near misses
    evidence         /tmp/build82-citations.log sha256 4b707acd25093c547be65cec2ee04adb589c443411bbdcca5fa00d58f2f1f737
