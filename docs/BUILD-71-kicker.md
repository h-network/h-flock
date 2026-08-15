# Build 71 — the switch forwards and moves on; a kicker spawns

> ⚠⚠ **CANCELLED. DO NOT BUILD. The cost it exists to remove is ZERO on real
> hardware.** Measured on `h-oracle` (32-core Ryzen 9950X3D) against the lab
> (4-vCPU QEMU VM), same workload, same scripts:
>
> | stage | lab, 4 vCPU | h-oracle, 32 core |
> |---|---|---|
> | `popped → forwarded` — the switch | 7–9 ms | **0 ms** |
> | `forwarded → kick_started` — **the kick this build removes** | 11 ms | **0 ms** |
> | `kick_started → received` — spawn | 622–677 ms | **23 ms** |
> | throughput | 6.5/s | **832/s** |
>
> ⚠ **The 11 ms kick was CPU contention on four vCPUs, not a syscall cost.** So
> was the 659 ms spawn, and so was every "unexplained ~500 ms" I attached to
> three separate code paths today. This build would have moved 0 ms into a new
> long-lived component.
>
> ⚠ **And it would not have helped on the slow host either** — which is the
> argument that actually settles it, because it does not depend on which machine
> you run. On the lab the switch's serialized cost (~20 ms) implies a ~50/s
> ceiling while end-to-end runs at **6.5/s: eight times below it**. The switch is
> not the constraint on *either* host; spawn is, at 60× the kick. This build
> raises a ceiling we never reach, and adds a fifth long-lived component to
> supervise to do it.
>
> **What would revive it on latency:** end-to-end throughput approaching the
> switch's serialized ceiling. That needs spawn to get much cheaper — i.e.
> long-lived ports. ⚠ **But long-lived ports remove the kick outright** (the
> switch only kicks when no port is running), which is a better fix than moving
> it. On latency this build is dominated in both directions.
>
> ## ⚠ A different argument for a kicker, which this build did NOT make
>
> **Backpressure, not latency.** Nothing bounds how many ports exist at once —
> `INGRESS_MAX` bounds queue *depth*, not process *count*. At 100s of agents a
> burst is an unbounded fan-out of interpreters.
>
> ⚠ **The switch cannot fix this itself, and the reason is structural:** to bound
> concurrency you need somewhere that may *block*, and the switch may not — it is
> single-threaded and blocking it stops forwarding for the whole tenant. Refusing
> a kick instead of blocking strands the envelope (build 66 measured what
> stranding costs). A serialized spawner can simply wait.
>
> **This is not resilience.** The switch already survives a failed or hung spawn:
> `_kick` catches `OSError` and logs `kick_failed` (`switch/service.py:91`), and
> `SIGCHLD = SIG_IGN` (`:232`) keeps the process table from filling. Those close
> the failure path. What is open is the *resource* path.
>
> ⚠ **UNMEASURED — do not act on this yet.** `conservation.sh:633` already
> samples `concurrent_ports`, and **no build doc has ever quoted the peak**. Get
> that number at 100 agents on h-oracle before building anything: if the peak is
> comfortable this stays theoretical, and if it climbs, it justifies a kicker on
> grounds this build never claimed.
>
> **What survives:** `bus`'s finding that a pipelined ingress+kick rollback races
> an active consumer and needs one atomic Lua operation. That is correct
> independent of whether this is ever built.

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
