# Build 88 — cost is either right, or it says it isn't

**Lane: `api`. Base: `main` at `d313fbc`.** Branch from main, push to origin.

**Sprint 3 of [`SPRINTS.md`](SPRINTS.md).** Files: `src/flock/watchdog/activity.py`
and whatever renders `office usage`.

⚠ **A fixture captured from a live codex agent is already in the tree** —
`tests/fixtures/codex-session-captured.jsonl`, eight records trimmed from a real
rollout. **Use it. Do not write a synthetic one.** The defect this build fixes
shipped precisely because a test constructed a shape codex has never written, and
the extractor and the fixture agreed with each other while both disagreed with
reality.

## 1. codex reports `model: unknown`, so every codex row prices as `unpriced`

`src/flock/watchdog/activity.py:154` falls through to `"unknown"`. ⚠ **The model
is not in the usage record.** It is in a `turn_context` record, `payload.model`,
emitted once per turn — `gpt-5.6-sol` in the fixture.

**Take the last `turn_context` at or before the usage record's ordinal**, so a
model change mid-session is followed rather than averaged over. `session_meta`
also carries a model at `payload.base_instructions.provenance.model`, and it is
the *provenance of the instructions* — usable as a fallback, wrong as the primary.

⚠ **Honesty limit of the fixture, stated so you do not over-claim:** all three
`turn_context` records in it carry the same model, because that session never
changed model. It proves you read the right field. It does **not** prove you
follow a change. Say so in your sign-off rather than implying coverage you do not
have.

## 2. ⚠ `last_token_usage`, never `total_token_usage`

`total` is cumulative across the session; `last` is that turn. In the fixture:

| ordinal | `last.input_tokens` | `total.input_tokens` |
|---|---|---|
| 17 | 14,132 | 14,132 |
| 414 | 111,751 | **3,332,258** |

**They are identical in the first record.** A one-record test cannot tell them
apart, which is exactly how summing `total` produced a figure an order of
magnitude over the truth. **Assert on a record where they differ.**

## 3. agy is not measurable, and the output must say so

⚠ **Established by reading agy's own state, not assumed.** agy stores SQLite plus
protobuf under `~/.gemini/antigravity-cli/`, not JSONL — so `ActivityTailer`
was never going to find it. The model *is* recoverable (`gemini-3.7-flash`, one
row per generation). **Token counts are not present anywhere**: every `token` and
`usage` string across all four blob columns is conversation content — an
`nvidia-smi` table, a tool summary, prose.

**So do not write an agy adapter.** There is nothing to adapt. `office usage` and
`office status` must **name agy agents as not measurable** rather than showing
them as zero, absent, or `unknown` — three things that currently read the same as
"ran and cost nothing".

⚠ **This is the whole point of the build.** A cost table that silently omits the
most talkative agent invites a comparison it cannot support.

## 4. Surface codex rate limits

Every `token_count` record carries `rate_limits` — `used_percent`,
`resets_at`, `plan_type` (`prolite` in the fixture). We surface none of it, and
it is the limit an operator actually hits. Smallest useful version is fine.

## 5. Decide the attribution question, or close it

`src/flock/port/openers.py:69` bounds delivery markers at 500, and a trimmed
marker yields a usage record with no `stream_id`. ⚠ **Read the comment above that
line before proposing anything** — a counter that fired on every uncorrelated
record was built and deleted in review, because 9 of 27 uncorrelated in a live
run were the *normal* case, and a signal dominated by the normal case is the
`delivery_unverified` defect again.

**A reasoned "close this, the loss is bounded and silence is correct" is an
acceptable outcome.** State which you chose and why.

## Done means

Pushed to origin. Tests green, and every new test names the captured file it
reads. `TEST-SIGNOFF` filled in, ⚠ **`VERIFIED BY` is not you.**
