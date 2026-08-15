# Build 71 — the switch forwards and moves on; a kicker spawns

> **Base on `main`.** Branch `bus/build-71-kicker`, push to origin.
> Owner: `bus` (`flock/switch`, `flock/bus`, `container/entrypoint.sh`).

## 1. What this is fixing, measured

Per-envelope, from build 70's captured logs, joined on `stream_id`:

| the switch's own serialized work | |
|---|---|
| `popped → forwarded` — the forwarding | 9 ms |
| `forwarded → kick_started` — **the spawn syscall** | **11 ms** |
| **total** | **~20 ms → a ~50/s ceiling** |

**The kick is 55% of the switch's cost**, and the switch is the one component
whose cost cannot be parallelised. Remove it and the ceiling roughly doubles.

⚠ **The kick is already fire-and-forget** — `Popen` does not wait. The 11 ms is
the syscall itself. There is no waiting to delete, only work to move.

## 2. The shape

**Switch:** stop calling `Popen`. Push the destination onto a kick queue **in the
same pipeline as the ingress write it already makes** — ingress first, then the
kick, because Redis executes a pipeline in order and a kick that arrives before
its envelope spawns a port that finds nothing.

⚠ **Marginal cost should be ~0**: same round trip, one extra command.

**Kicker:** a small long-lived process. `BLPOP` the kick queue, `Popen` the port,
loop. Nothing else. Started by `entrypoint.sh` alongside the other daemons.

**Ports: UNCHANGED.** Still one-shot, still exit after one envelope. ⚠ **That is
the point of this design** — it removes the switch's syscall without making
delivery depend on a single long-lived consumer.

## 3. ⚠ Constraints, each learned the hard way

- ⚠ **DO NOT DEDUPLICATE KICKS.** Collapsing two kicks for one agent looks like
  an obvious win and would **strand an envelope**: a port pops exactly one, so N
  envelopes need N kicks. Build 66 measured what stranding costs. If you ever
  want dedup, it requires draining, which was measured and rejected
  (`DESIGN-layers` §8).
- ⚠ **Bound the kick queue at write time**, exactly as build 68 bounds ingress:
  `RPUSH` returns the new length, so it is free. An unbounded queue was case B,
  and it cost 1084% CPU.
- ⚠ **The kicker is a new single point of failure.** So are the switch,
  `tmuxhost`, the watchdog and the api door — this is a fifth of a kind we
  already run, not a new class. Say how it is supervised and what happens when
  it dies.
- ⚠ **The kicker will have its own ceiling.** If it spawns serially at ~11 ms it
  tops out near 90/s. Better than 50/s, still finite. **Say what its ceiling is
  rather than leaving it to be discovered.**

## 4. ⚠ This will NOT make anything faster today, and the gate says so

Delivery costs **669 ms** in spawn. The switch is **~1%** of the path. Raising a
ceiling we sit 8× below changes no end-to-end number.

| | expect |
|---|---|
| switch per-envelope (`popped → forwarded` + `forwarded → kick_started`) | **~20 ms → ~9–11 ms** |
| end-to-end steady-state throughput | ⚠ **UNCHANGED, 6.08–6.90/s** |
| `kick_started → received` | unchanged, ~669 ms |

⚠ **If end-to-end throughput moves, something unexpected happened — report it,
do not celebrate it.** A faster number here would mean the switch was a
constraint we had not measured, which contradicts build 70.

## 5. Done when

- switch makes no `Popen`; kicker exists and is supervised
- ⚠ **negative controls** per [`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1: kill
  the kicker and show delivery stops **and that the kick queue grows rather than
  losing envelopes**; restart it and show the backlog drains. Then drive the
  queue over its bound and show the dead-letter
- `switch-bench.sh` and `base-run.sh` before and after, **paired, same session**
  (`BUILD-CONVENTION` §3 — this host varies 35% unpaired)
- `python3 -m pytest -q` green (383 at the time of writing)
- `container/accept.sh` green; conservation unchanged: **zero duplicates**
- one tenant at a time, lab-local output, ⚠ **fresh tenant per run** — a reused
  one produced 2100% coverage and nearly passed as clean

## 6. Reporting

`jira done`, then message `architect` with the paired before/after switch cost,
the kicker's own ceiling, what happens when it dies, and confirmation that
end-to-end throughput did **not** move.
