# The test harness — a register

⚠ **A programme, not a sprint.** The operator names which part to build; this
file records what exists, what is planned, and what each script is *for*, so a
later reader can tell the difference between a script that was never written and
one that was written and never wired in.

⚠⚠ **The failure this register exists to prevent, stated once:** on 2026-08-24 we
found that `container/scenarios/` held **32 scripts, six of them reconcilers**,
and `container/accept.sh` invoked **none of them**. Sender, receiver and
reconciler all existed, all worked, and had never been run together. **A script
that is not wired to a gate is a script that does not run.**

**So every entry below carries a WIRED column, and it is the column that matters.**

---

## The rule for every script here

⚠ **It must be able to go RED.** A harness that records and does not judge is
what we already had. Each script states what makes it fail, and a build that adds
one demonstrates the failure per `BUILD-CONVENTION` §1.

⚠ **It must say what it does NOT cover.** Every script here isolates a layer; the
value is in the boundary, and a reader who mistakes the boundary draws a false
conclusion. Build 111 measured a switch and was read as measuring delivery.

---

## 1 — packet switching · conservation only · **BUILT, NOT WIRED**

**Question:** does the fabric lose, duplicate, strand or reorder an envelope,
and how fast does it move them — with **no content inspection at all**?

**Parts, all of which already exist:**

| | |
|---|---|
| sender | `container/scenarios/bench-send.py` — real `flock.bus.doors.send`, real `sent` records |
| receiver | `container/scenarios/bench-port.py` — synthetic port; pops, emits real `received` and `opened`, **discards the payload** |
| judge | `container/scenarios/reconcile-unicast.py` — the reconciler from builds 92 and 96 |

⚠ **This is the CONTROL the whole week has lacked.** No tmux, no CLI, no
`ENTER_DELAY`, no Ink — ground truth at both ends because both ends are ours. **If
this path is clean and the tmux path loses four in twenty, the loss is provably
in the port and terminal, not the fabric.** Build 113 could not make that
attribution.

**Covers:** envelope conservation and forwarding throughput.
⚠ **Does NOT cover:** content integrity, the port, the terminal, or the
application. **Coalescing and truncation are invisible to it** — it counts
envelopes, not bytes.

**Spec:** `BUILD-114`.

**Runnable:** `container/scenarios/packet-switching.sh` runs `steady` (receiver
already running) or `burst` (sender queues before the receiver starts).  A
`--reconcile-only DIR` run judges a retained custody fixture without Docker.
The measured boundary is **popped → forwarded**; the run covers no port,
terminal, or application and never inspects payload bytes.

**Outcomes:** `0` is clean; `1` is unexplained loss, `2` is a duplicate, `3`
is a stray opened envelope, `5` is `forward_unknown`/indeterminate, and `100`
is incomplete setup or evidence.  The script prints the boundary, stage counts,
and throughput before composing the reconciler result.  It is **not wired to
`accept.sh`**; that is deliberately a later build.

**Failure evidence:** a nonzero live result captures the full container log,
container/process snapshots, tenant keyspace contents, per-queue LLENs, and
SHA256s before teardown. A clean result skips this diagnostic set.

---

## Candidates — from findings, NOT scheduled

⚠ **Listed so they are not re-derived. The operator picks; none of these is
committed.**

| candidate | the finding that produced it |
|---|---|
| content integrity | `bench-port` discards payloads, so coalescing and truncation are invisible |
| burst / queue-drain | build 113 bursted **tmux**; the fabric itself has never been bursted |
| delivery verification | `verification.py` is an aliveness check and missed **four real losses** in a burst |
| terminal layer | six stages end at the port's handoff; nothing records below it |
| control plane | `_incomplete`, `_failed` and `_partially_failed` have **never** run outside a unit test |
| usage accounting | codex `rate_limits` unproven live; agy not collected |
| test doubles | fixed for `resp.Redis`; **unchecked for every other double** |
