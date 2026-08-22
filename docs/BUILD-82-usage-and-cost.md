# BUILD 82 — what a run costs

**Base: `main` after build 80 lands.** Branch `api/usage-and-cost`.

⚠ **BLOCKED until build 80 is merged.** Usage records are a new writer, and
shipping them before `writer` exists reproduces exactly the problem 80 fixes:
a record nobody can attribute. Do not start early.

## 1. Why this is not a port

h-office solved this in `services/router/usage.py` (367 lines): scan every CLI
config dir, glob the session files, map a session to an agent by its `cwd`,
dedupe by request id, sum four token buckets, price them.

⚠ **h-flock does not need most of that, because `ActivityTailer` already does
it.** `watchdog/activity.py:107-116` already reads:

```
~/.claude<suffix>/projects/-workdir-<agent>/*.jsonl
~/.codex<suffix>/**/rollout-*.jsonl
```

…with the agent already resolved, the multi-account profile suffix already
handled, byte offsets already tracked in `_state`, and codex's shared-rollout
ownership already decided by `_codex_session_belongs_to`.

⚠ **And `_claude_events` / `_codex_events` parse the very record that carries the
token counts, then discard everything except `kind` and `tool`.** The data is
already streaming past us and being thrown away. **Extract it there.** Do not
add a second scanner over the same files — two readers of one file with separate
offsets is a drift bug waiting to happen.

## 2. What to build

### 2.1 Emit a usage record

Where the tailer already parses a record, also read the usage block and emit:

```
{"module":"watchdog","event":"usage","writer":"usage","agent":"bus","cli":"claude",
 "model":"claude-opus-4-8","input":812,"cache_read":40311,"cache_write":1902,
 "output":1204,"ts":"…"}
```

- claude: per-message `message.usage`
- codex: the `token_count` event
- ⚠ **dedupe by request id.** h-office does this because the same request can
  appear more than once in a session file; without it every number is inflated.
- **Four buckets, always present, zero when absent.** `cache_read` and
  `cache_write` are not optional extras — on a long agent turn they dominate,
  and a total that omits them is wrong by an order of magnitude, not a rounding.

### 2.2 Pricing

Port `config/pricing.json` from h-office as `container/config/pricing.json` —
it is data and it is good. Keep its rules exactly:

- USD per **1,000,000** tokens
- **longest-prefix** model match (`claude-opus-4` matches `claude-opus-4-8`)
- ⚠ **a model with no matching key is $0 AND FLAGGED.** Silent zero is how a
  local run and an unpriced cloud model become indistinguishable. The flag is
  the point — say `unpriced` in the output, do not just total to zero.

### 2.3 A way to read it

`office usage [--agent X] [--since ISO] [--json]`, summing the emitted records:

```
agent    cli     model                  input   cache_r  cache_w   output      USD
bus      claude  claude-opus-4-8        12.4k    1.20M     48.1k    31.2k    4.83
tmux     codex   gpt-5-codex             8.1k     412k         -    12.0k    0.71
architect claude nemotron-lightning      2.1M        -         -   180.4k  unpriced
                                                                          ------
                                                                            5.54
```

## 3. ⚠ The correlation half — this is the part the operator actually asked for

*"we will need it later to benchmark communications too."*

A total per day is nearly useless for that. **What is wanted is cost attributable
to a conversation**, which means a `stream_id` on the spend.

⚠ **The join already exists and you should reuse it, not invent one.**
`DeliveryVerifier.poll` (`watchdog/verification.py:100-102`) already compares a
delivery marker's timestamp against that agent's activity timestamps. A usage
record carries a timestamp from the same stream. So:

> the first usage record for agent A after the marker for `stream_id` S,
> and before the next marker for A, is S's turn.

Emit `stream_id` and `correlation_id` on the usage record when that join
succeeds, and **omit them when it does not** — a wrong attribution is worse than
none, and `correlation_id` then gives cost per *thread* for free.

⚠ **This is heuristic and must say so in the code.** An agent that receives two
messages during one turn produces one usage record; the second gets no
attribution. That is correct behaviour, not a bug to paper over.

## 4. Out of scope

- budgets, limits, alerts or anything that *blocks* on cost
- a dashboard
- rate-limit or quota tracking
- changing `ActivityTailer`'s existing `kind` values or offsets

## 5. Verification

1. a claude fixture with known usage → exact four buckets, exact USD at a known rate
2. the **same request twice** in one file → counted once (the dedupe control)
3. a model absent from `pricing.json` → `unpriced`, not `0.00`
4. cache buckets present → included; a control that drops them must change the
   total, proving they are not decorative
5. marker then usage → `stream_id` attached; usage with **no** preceding marker →
   **no** `stream_id`, and a control proving it is omitted rather than guessed

⚠ **`architect` runs the live arm** on h-oracle against `vllm-nemotron` — an
unpriced local model, which is the case most likely to be silently wrong.

## 6. Done means

Pushed, `pytest -q` green, `check_citations.py` exit 0 read **unpiped**, and
`docs/BUILD-82-results.md` with a filled `TEST-SIGNOFF` block.

⚠ **`VERIFIED BY` is not you.**
