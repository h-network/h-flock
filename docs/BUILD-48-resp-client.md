# Build 48 — take redis-py off the one-shot path

> **Base on `main`.** Branch `<lane>/build-48-resp`, push to origin.
> Owner: `bus`. ⚠ It touches three files `tmux` normally owns — see §6.

## 1. What this buys, measured

The startup tax is paid **twice per message**: once when an agent runs `office
send`, once when the router spawns `flock.adapter` to deliver it. Both are
one-shot processes whose real work is ~20 ms.

| | ms |
|---|---|
| `office --help` / `peers` / `status` | 466–697 |
| `flock.adapter`, message waiting — a real delivery | 657 |
| `blpop` **with a message waiting** — the actual work | **0.84** |
| spawn + connect + one command, redis-py | 566 |
| spawn + connect + one command, **hand-rolled RESP** | **87** |

`import redis` costs ~600 ms, of which **~290 ms is `asyncio`** — pulled in by
redis-py's `__init__` for an async client neither program touches. You cannot
take a lighter slice: `import redis.client` measured *worse* (883 ms) because
the package `__init__` runs first either way.

⚠ **This box is ~10× slower than a normal machine** (`import asyncio` at 290 ms).
Trust the ratios, not the absolutes, and re-measure before and after on the same
container in the same run.

## 2. Why this and not the alternatives

Compiled Python was measured and rejected: 576 of the 606 ms is *self* time —
executing ~100 module bodies, no single one above 32 ms. Nuitka and PyOxidizer
attack module finding and reading, which is the small part, and CPython's
runtime floor is 53 ms regardless. Go was considered and rejected: it wins
(13.6 ms) but costs a second toolchain, and the openers would have to move with
it. **Deleting the dependency beats optimising how it loads.**

## 3. What to build

`src/flock/bus/resp.py` — a minimal RESP2 client, no dependencies beyond
`socket`. The surface is exactly what the one-shot path calls, and no more:

```
rpush  lrange  get  xadd  hgetall  hget  hdel  blpop
lrem   lpop    llen hsetnx hkeys   hexists delete
```

Reply types needed: simple string, integer, bulk string (including nil `$-1`),
array (including nil), error. That is all of RESP2.

⚠ **`flock.bus` already duck-types the client** — it takes `r` as a parameter
and imports redis nowhere. That is why this is a small change: nothing in
`flock/bus/*.py` should need to know which client it got.

## 4. ⚠ The thing that will bite: return types

redis-py returns **bytes** unless `decode_responses=True`, and the callers
depend on which they get — `parse()` takes raw, `hgetall` keys are compared
against `str`. **Match the existing behaviour exactly, per call site.** A
client that returns `str` where the caller expects `bytes` will not fail
loudly; it will dead-letter envelopes, and the custody log will look like a
forwarding failure.

Read each call site and assert the type in a test. Do not infer it.

## 5. What must NOT change

- **The daemons keep redis-py**: `api/app.py`, `router/service.py`,
  `tmuxhost/host.py`, `watchdog/service.py`. They start once, so the import is
  free, and they want the library's reconnection and pooling. Only the
  **one-shot** programs switch.
- **No `BLPOP` → `LPOP` change in this build.** It is the right change and it is
  a separate one — bundling it would confound the before/after measurement.
- Envelope shape, key shapes, and the five custody records: byte-identical.

## 6. Files

| file | lines | change |
|---|---|---|
| `src/flock/bus/resp.py` | new | the client |
| `src/flock/adapter/runner.py` | 180 | construct the RESP client instead of `redis.Redis` |
| `src/flock/adapter/cli.py` | 74 | same |
| `src/flock/office/cli.py` | 639 | same |

⚠ **`bus` owns this build even though `tmux` owns two of those files** — the
change is one seam and splitting it across lanes would leave the tree
inconsistent between pushes. `tmux` has been told; coordinate before touching
`flock/adapter` for anything else this week.

## 7. Done when

- `office peers` and a real `flock.adapter` delivery both measure **under
  200 ms** on the same container, in the same run, before and after
- `python3 -m pytest -q` green (340 on `main` at the time of writing)
- `container/accept.sh` green — 25/25 plumbing, 19/19 sim-blocked
- `container/scenarios/fabric-bench.sh` at `STATIONS=100 ROUNDS=20`: **2,000 of
  2,000 delivered, zero dead letters**, and every custody record parsing
  strictly. ⚠ Compare throughput against the `main` baseline of **2.64/s**, one
  container at a time — no other h-flock tenant running.

## 8. Reporting

`jira done`, then message `architect` with the commit, the before/after
timings from one run, the bench result, and anything you had to special-case in
the protocol.
