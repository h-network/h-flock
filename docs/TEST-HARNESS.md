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

## 1 — packet switching · conservation only · **SPEC'D, NOT BUILT**

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

---

## 2 — bi-directional · payload verified and ACKED · **DEFINED, NOT SPEC'D**

**Question:** does a payload survive intact, and can the receiver *say so* —
in both directions?

**Shape:** origin sends a payload with a unique marker; the destination
**verifies the content it received and acks back over the bus**; the origin
verifies the ack. **One adapter, two roles, a round trip.**

⚠⚠ **Why the ACK is the point, and not a convenience.** Six custody stages end at
the port's handoff. Nothing below it is recorded, and **that is deliberate** — a
switch that forwards by name and never reads content cannot know whether the
destination consumed anything. Build 113 measured the consequence: four messages
`opened` and never received.

**A test adapter can close that gap without violating the design, because the
adapter is an APPLICATION.** The fabric still never inspects content; **the
receiver testifies for itself.** ⚠ **That is the only honest way to get
end-to-end receipt in this architecture**, and it is why this script is worth
more than script 1 plus a payload check.

**What it catches that script 1 cannot:** coalescing · truncation · reordering ·
corruption · **and receipt itself**, rather than handoff.

**Also yields:** round-trip latency, and both directions under load at once —
which is what a real conversation between agents actually looks like.

⚠ **Does NOT cover the tmux port or a CLI.** The receiver is `bench-port`-shaped,
so there is no terminal and no input box. **Script 2 isolates fabric + port +
application.** The terminal remains uncovered by anything — see the candidates.

⚠ **Build order matters**: script 1 first, because a bi-directional content
failure is ambiguous until envelope conservation is independently proven. **If
script 1 is clean and script 2 is not, the defect is in content handling. Without
script 1, it could be either.**

---

## Candidates — from findings, NOT scheduled

⚠ **Listed so they are not re-derived. The operator picks; none of these is
committed.**

| candidate | the finding that produced it |
|---|---|
| burst / queue-drain | build 113 bursted **tmux**; the fabric itself has never been bursted |
| delivery verification | `verification.py` is an aliveness check and missed **four real losses** in a burst |
| terminal layer | six stages end at the port's handoff; nothing records below it |
| control plane | `_incomplete`, `_failed` and `_partially_failed` have **never** run outside a unit test |
| usage accounting | codex `rate_limits` unproven live; agy not collected |
| test doubles | fixed for `resp.Redis`; **unchecked for every other double** |
