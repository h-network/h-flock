# Build 47 — the custody log can lose records to itself

> **Base on `main`.** Branch `<lane>/build-47-torn-records`, push to origin.
> Owner: `bus` (`src/flock/bus/logging.py`).

## 1. What was measured

A 30-round Nemotron relay between two agents, 49 delivered envelopes. The
custody audit reported **48 of 49 with the full five-record set**. The missing
envelope was not missing anything: all five records existed, and two of them
shared a line.

```
{"ts":"…04:47:12.477Z","module":"api","event":"sent",…}{"ts":"…04:47:12.484Z","module":"router","event":"forwarded",…}
```

Across the whole run: **2 torn lines in 290 (0.7%)**, involving four different
modules — `tmuxhost`+`container` in one, `api`+`router` in the other. It is not
one bad pair of writers; it is any two.

## 2. Why

`container/Dockerfile:96` sets `PYTHONUNBUFFERED=1`, which makes stdout
write-through. `logging.py`'s `print(line, flush=True)` then issues **two**
write syscalls — the record, then the newline. Every module writes to the same
container stdout, so a second process's write can land between them.

Each write is under `PIPE_BUF` and therefore atomic on its own. **The record is
not torn; the newline is separated from it.**

## 3. Why it matters more than 0.7% suggests

⚠ **The log is the only observer.** `CONTRACTS` §3's five records are how anyone
answers "where did this stop", and the audit tooling parses one JSON object per
line. A torn line silently removes **two** records from the reconstruction — and
it removes them from the *middle* of the chain, which is exactly the shape a
real loss has. A reader cannot distinguish this from a genuine forwarding
failure without going back to the raw bytes, which is what happened here.

⚠ **It gets worse with traffic, not better.** Two writers raced at 49 envelopes
over three minutes.

## 4. The fix

One write per record, newline included — `sys.stdout.write(line + "\n")` rather
than `print(line, flush=True)`. Under `PIPE_BUF` that is atomic against other
writers, which is the property being relied on and never stated.

⚠ **State it in the code.** The reason this is one call rather than two is not
visible from reading it, and the next person tidying this file will reach for
`print`.

## 5. Also worth a line while you are here

`popped` was logged **before** the producer's own `sent` for the same envelope
(`04:47:12.470` vs `.477`) — the append happens before the emit, so a fast
router beats the sender's log write. That is correct behaviour and a trap for
anything reconstructing order from timestamps. Say so in `CONTRACTS` §3:
**the five records are a set, not a sequence.**

## 6. Done when

- no torn lines in a run of the same shape — re-run
  `container/scenarios/fabric-bench.sh` at `STATIONS=100 ROUNDS=20` and parse
  every line strictly; a parse failure is a test failure
- `CONTRACTS` §3 says the records are unordered
- `python3 -m pytest -q` green (339 on `main` at the time of writing)
