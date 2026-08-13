# Build 51 — a kicked adapter should not block

> **Base on `main`.** Branch `<lane>/build-51-kicked-lpop`, push to origin.
> Owner: `bus` (`src/flock/bus/doors.py`).

## 1. One line

`receive()` at `doors.py:43` does a **blocking** pop:

```python
item = r.blpop(prefix(pod, tenant, agent, "ingress"), timeout=timeout)
```

⚠ **The router kicks the adapter because it has just forwarded an envelope.**
There is nothing to wait for. A kick that loses the race to a sibling — same
agent, two envelopes, two kicks — finds an empty queue and then sits blocked for
a full second doing nothing.

Measured, same run, on an otherwise idle container:

| | ms |
|---|---|
| `blpop` **with a message waiting** | **0.84** |
| `blpop` on an **empty** queue | **1,020** |
| whole kick, message waiting | 233 |
| whole kick, empty queue | 2,065 |

## 2. What to change

`LPOP` on the kicked path. If it finds nothing, return — another kick is already
coming, because kicks are per forwarded envelope.

⚠ **`timeout` does not disappear.** Anything that legitimately waits keeps
blocking; only the *kicked one-shot* stops. Read the call sites before deciding
which is which, and say in the report which ones you judged to be which.

⚠ **At-most-once is not affected.** `LPOP` removes the entry exactly as `BLPOP`
does. This changes waiting, not delivery.

## 3. Why it is worth a build on its own

It caps a one-second worst case on a path whose real work is 0.84 ms, and it is
the last cheap thing on the delivery path — everything else remaining is
structural (a long-lived adapter) or environmental (the 1.3–1.9 ms loopback
Redis round trip, still unexplained).

⚠ **Deliberately kept out of build 48** so that build's throughput number
measured one change and not two.

## 4. Done when

- the kicked path does not block; other waiters unchanged and named in the report
- a test proves an empty ingress returns promptly rather than after `timeout`
- `python3 -m pytest -q` green (345 on `main` at the time of writing)
- `container/accept.sh` green, and `fabric-bench` at `STATIONS=100 ROUNDS=20`
  delivering 2,000 of 2,000 with zero dead letters
- ⚠ **one h-flock tenant at a time on the lab.** Compare against the current
  `main` baseline of **6/s** — not the pre-build-48 2.64/s

## 5. Reporting

`jira done`, then message `architect` with the commit, the bench figure against
6/s, and which call sites you left blocking and why.
