# Build 62 — nine gates that pass on a fast day

> **Base on `main`.** Branch `tmux/build-62-sleep-gates`, push to origin.
> Owner: `tmux` (`container/`).

## 1. What was found

`bus` audited `container/` during build 59 and counted **nine** remaining gates
that `sleep` a fixed interval and then assert: **8 in `plumbing-check` steps
2–8 and 11**, and **1 console gate in `accept.sh`**.

The tenth was the lifecycle gate, and it is why this build exists. Measured
during build 59: the check sampled **260 ms before** `window_created`, against a
**4.5 s median** operation behind a fixed 5 s sleep. It had ~500 ms of margin and
any jitter tipped it. It produced a **red run on a correct branch**, and the
first hypothesis was that build 54 had slowed something down — it had not,
`+1.35%`.

⚠ **A fixed sleep followed by an assertion is a gate that passes on a fast day.**
It fails randomly under load, which is exactly when someone is looking, and each
false red costs an investigation.

## 2. What to do

Convert each to a **poll with a deadline**, matching the shape build 59 gave the
lifecycle gate: poll the condition, succeed as soon as it holds, fail at the
deadline with what was expected and what was seen.

⚠ **Use a wall-clock deadline, not an iteration count.** Build 58 had a limit
named for seconds that counted loop iterations, where each iteration cost
multiple seconds under load — a 40-minute boundary silently became hours. Same
mistake, different file.

⚠ **Keep the deadline generous and the poll tight.** A poll every 100 ms with a
15 s deadline is not slower than `sleep 5` in the common case — it is *faster*,
because it returns as soon as the condition holds.

## 3. ⚠ The negative control is the whole build

**A poll that always succeeds is indistinguishable from an assertion that never
runs.** For **each** converted gate, make its condition genuinely fail — the
window absent, the file unwritten, the client unenrolled — and show it go red at
the deadline with a useful message.

⚠ **Nine conversions and nine proofs.** If that is tedious, that is the cost of
the guarantee; four false-green defects in two days is the alternative. Report
the count of gates converted and the count proven to fail — **if those two
numbers differ, say so.**

## 4. Also report, do not fix

While you are in there, note any gate whose **condition is untestable** — one
where you cannot make it fail without breaking something unrelated. That is a
finding about the check's design and I want to hear it rather than have it
quietly polled.

## 5. Done when

- nine gates converted; **nine proven able to fail**
- no fixed `sleep` remains as a gate in `container/` — ⚠ `sleep` used for
  *pacing* is fine and is not a gate; say how you told them apart
- `container/accept.sh` green on `main`, exit 0
- `python3 -m pytest -q` green (367 at the time of writing)
- ⚠ one h-flock tenant at a time, output to a lab-local file

## 6. Reporting

`jira done`, then message `architect` with: gates converted, gates proven to
fail, any untestable conditions found, and how you distinguished a pacing sleep
from a gate.
