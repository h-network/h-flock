# Build 74 — the v4 switch against real tmux agents on a real model

> **Base on `main`.** Branch `tmux/build-74-nemotron`, push to origin.
> Owner: `tmux` (`container/scenarios/`, no product code expected).

## 1. What has never been tested

Every benchmark we have — `switch-bench`, `base-run`, `conservation`,
`frame-cost-sweep` — uses **synthetic ports or api clients**. Deliberately: no
CLI, no tokens, steady payloads. `base-run-tmux.sh` uses real tmux windows but
puts a **plain shell** in them.

⚠ **So the v4 wire has never met a real agent.** Not a real CLI, not a real
paste-plus-Enter with `PASTE_ENTER_DELAY`, and — the part that matters most —
**not a real payload**.

⚠ **An LLM is the natural fuzzer for the frame body.** Every synthetic run sent
`{"text":"r0"}`. A model emits newlines, quotes, backslashes, unicode, code
fences and JSON-inside-JSON. **v4 claims the body is opaque bytes the switch
never decodes; this is the first thing that will actually test that claim.**

## 2. ⚠ Host: h-oracle, and this is an EXCEPTION to the split

The GPU is on h-oracle, so this runs there. `BUILD-CONVENTION` §3.0 reserves
h-oracle for performance — this is a deliberate exception because the model
cannot run anywhere else.

⚠⚠ **THIS IS AN INTEGRATION TEST, NOT A PERFORMANCE TEST. Do not report a
throughput figure from it.** Delivery here is gated by model inference, which is
seconds. Any `/s` number describes Nemotron, not the fabric.

⚠ **Do not touch `h-flock-office`** — the office runs in that container. Fresh
tenant, your own compose project, `down -v` at the end.

**Model:** `nemotron-lightning` at `http://127.0.0.1:8000/v1` on h-oracle
(NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4). Confirmed up.

## 3. Shape

- **3–4 agents**, `port_type: tmux`, real windows, real CLI, backed by the model
  above. You own how a window gets its env — pick the mechanism.
- **~30 rounds** of messages between them.
- ⚠ **Let them answer in their own words.** Do not constrain output to short
  clean strings; the messy output *is* the test. If anything, ask for something
  that produces a code fence and a quote.

## 4. What to check

**Custody, joined on `(stream_id, recipient)`** with `analyse-run.py`:

| | expect |
|---|---|
| all six stages | `sent, popped, forwarded, kick_started, received, opened` — **coverage, not averages** |
| **duplicates** | ⚠ **ZERO. This is the absolute defect.** |
| losses | permitted **only if attributable** — at-most-once, zero retries |
| `ttl` / `hops` | ttl decremented, hops incremented, on every forward |

**Frame integrity — the point of the build:**

- ⚠ **The body must arrive byte-identical.** Compare what was sent against what
  the port parsed, per envelope, **including across a source stamp**.
- ⚠ **Report any payload that broke anything**, with the bytes. A frame the model
  produced that we mishandle is the most valuable output this build can have.

**The tmux path specifically:**

- `received -> opened` — this is where `PASTE_ENTER_DELAY` lives; expect ~500 ms
  and say so
- `delivery_unverified` / `delivery_unjudged` rate — ⚠ **this is the only
  scenario where `watchdog/verification.py` applies at all**, since it watches pane
  input. First real reading we will have of it.

## 5. Done when

- the run completes and `analyse-run.py` **refuses nothing** — a refused stage is
  a finding, report it rather than re-running until it passes
- zero duplicates, every loss attributed
- body byte-identity confirmed, or the counter-example reported
- ⚠ **fresh tenant, `down -v`, `h-flock-office` untouched** — state this
- capture-then-analyse per `BUILD-CONVENTION`: ⚠ **nothing reads the log while
  the run is in flight**

## 6. Reporting

`jira done`, then message `architect` with: the six-stage coverage table, the
duplicate count, `ttl`/`hops` behaviour, `received -> opened` p50, the
`delivery_unverified` rate, and **any payload that broke anything**.

⚠ **No throughput figure.** If one appears in the report I will ask you to remove
it, because someone will quote it later.
