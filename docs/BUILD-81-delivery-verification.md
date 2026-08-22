# BUILD 81 — a delivery check that is right more often than it is wrong

**Base: `main` at `6543c45`.** Branch `tmux/delivery-verification`.

⚠ **Do not start from `watchdog/service.py`.** Build 80 is in flight on `bus` and
touches `_alert`/`_error` in that file. This build owns
`src/flock/watchdog/verification.py` and its tests. If you need a change in
`service.py`, say so and it will be sequenced.

## 1. The measurement that opened this

| run | unverified | reality |
|---|---|---|
| 4 agents, 3 h, local model | **1,180 of 1,285** | every one received and acted on |
| build 74, Nemotron | **4 of 13** | four healthy agents that had not typed yet |

⚠ **A check that is wrong 92% of the time is worse than no check** — it trains
everyone to ignore it, and it is currently ignored.

## 2. Root cause, read from the code

`verification.py:40` — `verify_after_seconds: float = 10.0`.

`verification.py:100-102` — `_input_times()` collects **only** activity entries
where `kind == "input"`, then `verified = any(input_time > marker_time)`.

Two independent defects:

**(a) Ten seconds is not a turn.** A local model takes minutes. The pasted input
is not recorded by the CLI until the agent's *current* turn ends, so a busy agent
is judged before it could possibly have answered.

**(b) Only `input` counts as being alive.** An agent mid-turn emits `output` and
`tool` events continuously. `ActivityTailer` already collects them. The verifier
throws away the strongest evidence of liveness it has.

## 3. What to build

### 3.1 Widen the evidence

Any activity entry — `input`, `output`, or `tool` — timestamped after the marker
counts as the agent being alive and progressing.

⚠ **State the trade honestly in the code comment.** This admits a false
*positive*: an agent still finishing a *previous* turn emits `output` and will
read as verified without having seen the paste. **That is the better error.** The
check exists to find a wedged process or a login prompt, and neither produces any
activity of any kind. Trading a rare false positive for a 30-92% false negative
rate is the whole point of this build.

### 3.2 Make the window real, and configurable

`verify_after_seconds` default **120**, from `VERIFY_AFTER_SECONDS`. Ten seconds
was never measured against a turn; 120 is a starting estimate that §5 must
either confirm or replace with a measured number.

### 3.3 Fix the read, which is O(entire stream)

`_input_times` does `xrange(min="-", max="+")` — the **whole** activity stream,
per agent, per poll. Over a three-hour run that is re-read every cycle. Read from
the marker forward (`min=<marker-derived id>`) or bound it; the answer only ever
depends on entries *after* the marker.

## 4. Do not change

- **the record name** `delivery_unverified`, or `delivery_unjudged`
- **the no-retry rule.** `verification.py:121` says it exactly right: it cannot
  distinguish loss from a landed paste, so it must never retry. At-most-once is
  absolute and a duplicate is a defect, not a nuisance.
- the `blocked` key's shape — the console and the api door both read it

## 5. Verification — this one needs a live run, and you do not have Docker

Build the change plus unit tests with synthetic activity streams covering:

1. marker, then only `output` inside the window → **verified** (the fix)
2. marker, then nothing at all, past the window → **unverified** (still fires)
3. marker, then activity *before* the marker only → **unverified** (ordering)
4. no activity history at all → **unjudged**, unchanged
5. ⚠ a control that mutates the widened evidence back to `input`-only and shows
   case 1 flipping to unverified — **failing inside `_input_times`, not in the
   caller**

Then hand it back. **`architect` runs the live arm** on h-oracle against
`vllm-nemotron` — four agents, real traffic — and reports the before/after rate.
A unit test cannot establish the false-negative rate; only the run can.

⚠ **Report the measured rate even if it is bad.** If 120 s is still wrong, the
number is the finding and the default changes. Do not tune it to look good.

## 6. Done means

Pushed to `origin`, `python3 -m pytest -q` green, `python3 tools/check_citations.py`
exit 0 read **unpiped**, and `docs/BUILD-81-results.md` with a `TEST-SIGNOFF`
block for the unit arm — verdict **SMOKE** is correct there, because the claim
that matters is a rate and only the live run establishes it.

⚠ **`VERIFIED BY` is not you.** Every sign-off in this repository says
`author? YES`; ask `api` to read it.
