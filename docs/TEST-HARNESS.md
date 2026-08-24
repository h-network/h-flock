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

## 1 — packet switching · conservation only · **BUILT, ON A BRANCH, NOT MERGED, NOT WIRED**

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

**Spec:** `BUILD-114`. Built by `bus`, on a branch.

### ⚠⚠ Its first run found something, which is the argument for the whole register

**Steady 20/20 clean. Burst 100 destinations × 2: 195 of 200 through every stage,
five lost.** All five carry **only a `sent` record**.

**What the five eliminate, each established from code rather than argued:**

| | |
|---|---|
| `doors.py:80-88` | `rpush` runs **first** and the `except` **raises** — so `sent` is **proof the envelope reached the egress list** |
| no `expire`/`setex` in `src`, no `--maxmemory` | keys never vanish on their own |
| `switch/service.py:113` | the **only** consumer of egress in the tree; `api/app.py:597` merely reads `llen` |
| `resp.py` `makefile("rb")` | buffered — no framing bug at 100 keys, no `settimeout`, no reconnect |
| `service.py:185-190`, `:124-128`, `:147-154` | **every in-tree loss path emits a record** — `forward_unknown`, `dead_lettered` |

⚠ **The five match no failure path in the code.** They were on the list, the only
in-tree consumer never recorded them, and every way the tree can lose an envelope
leaves a trace. **So something outside `src/` removed them.**

⚠ **Five hypotheses have died here** — tail truncation (timing), static watch list
(`service.py:104-114` rebuilds the roster per step), socket framing, key TTL and
eviction, and a **second switch instance** (the burst log has exactly one
`started reason=switch pid=51`, no restarts, and the tenant was freshly
generated). **The cause is open.**

## ⚠⚠ And the finding that outranks it: THE EVIDENCE WAS TORN DOWN

The diagnosis stopped because **the artifacts needed to finish it no longer
exist** — only the custody snapshots and ledgers survived project teardown, so
absence from an alternate log **cannot be proven either way**.

⚠ **This is the second time.** `BUILD-105`'s agy capture took six named paths and
never opened `brain/`, and an invented fixture shape hid a total data loss.
**Twice is a rule, not an incident:**

> ⚠⚠ **A harness must capture enough to DIAGNOSE, not merely enough to JUDGE —
> and it must capture it BEFORE teardown.** A run that goes red and destroys its
> own evidence has cost more than it returned.

**So the next move on this RED is reproduction with full retention, not more
archaeology.** The recipe is known (100 × 2 burst), the control is known (20 × 2
clean), and the drain guard now separates *did not drain* from *lost*.

⚠ **`bus` added a drain guard (`ecd62d3`): poll to zero, print
`PACKET_QUEUE_DEPTH`, return `rc100` rather than judge.** That is the right shape
— **a gate that reports a false loss is exactly as bad as one that misses a real
one**, and `rc100` keeps *ran-but-incomplete* distinct from *failed*.

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

## 3 — does the LOGGING tell the truth · **PARTLY EXISTS, ALL OF IT UNWIRED**

**Question:** are the records complete, well-formed, and do they mean what the
contract says?

**What exists**, none of it invoked by anything:

| script | what it answers |
|---|---|
| `analyse-run.py` | *"is every step logged"* — stage coverage, not averages |
| `analyse-verification.py` | how often `delivery_unverified` cried wolf |
| `analyse-v4-aof.py` | exact v4 frame bytes at egress vs ingress, from the AOF |

⚠⚠ **Run against build 113's custody log — four PROVEN losses — the verification
analyser reports `delivery_unverified 0`, `0.0% of opened`, and prints "no
verification flags — nothing to judge".**

⚠ **It is not broken. It measures the wrong direction.** It computes flags raised
as a share of deliveries, which answers *"how often did the alarm cry wolf"* — the
92% false-positive problem build 81 fixed. **It has no concept of a false
negative, because it can only see flags that WERE raised.** A tool that measures
how often an alarm went off cannot measure how often it should have.

⚠⚠ **So the blind spot is invisible to the tool built to audit it**, and that is
the same shape as everything else this week, one level further out.

**What closing it requires: GROUND TRUTH.** A false-negative rate is
*should-have-flagged* minus *did-flag*, and nothing today knows the first term.

⚠ **Script 2's ack supplies it.** A receiver that testifies for itself is a
record of what actually arrived, which is precisely what `analyse-verification`
needs to compute the direction it currently cannot. **So script 3 depends on
script 2 — build order is 1, 2, 3**, and that dependency is a finding rather
than a preference.

⚠ `analyse-v4-aof.py` also overlaps script 2 from below — byte-exact frame
comparison at the wire, where the ack proves receipt at the application. **Two
independent answers to "did the payload survive", at different layers.**

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
