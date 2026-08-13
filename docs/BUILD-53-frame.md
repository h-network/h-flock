# Build 53 — the envelope becomes a frame

> **Base on `main`.** Branch `bus/build-53-frame`, push to origin.
> Owner: `bus`. ⚠ Touches `flock/adapter` (`tmux`'s) and the clients (`api`'s) —
> see §7. **This is a wire change.**
>
> ⚠ **Use `main`'s vocabulary** — `router`, `adapter`, `recipient`. The rename is
> parked on `rename/vocabulary` and the codemod will rewrite whatever you write.
> Do not half-adopt the new words.

## 1. What this is, and what it is not

The design is in [`DESIGN-layers`](DESIGN-layers.md) §2.5. The envelope stops
being flat and becomes a **frame with layered headers**:

```
L2   source, destination (local, bare)     ← the switch reads ONLY this
L3   pod:tenant:agent, qualified           ← rides along; the router reads it
L4   (reserved, not in this build)
payload
```

**In scope:** the frame layout, qualified addresses accepted, the adapter
resolving local-vs-remote, the switch reading L2 only.

⚠ **NOT in scope: routing.** There is no router. A destination whose
`pod:tenant` is not local **fails at the sender** with a real error. That is the
whole point — this build makes the address format real without building anything
that consumes it.

⚠ **NOT in scope: policy.** Tags and filtering are build 54.

## 2. The three changes

**1. The address rule accepts a qualified form.** Today `bus/keys.py`'s
`SEGMENT_REGEX = ^[a-z0-9][a-z0-9-]{0,62}$` rejects colons, so
`envelope.py:19`'s `_agent_name` refuses `acme:hq:alice` outright. Relax it in
**one place** — segments still cannot contain `:`, so splitting stays
unambiguous.

**2. The adapter resolves, once per send.**

| destination given | L3 header | L2 header | result |
|---|---|---|---|
| `alice` | `<my pod>:<my tenant>:alice` | `alice` | local, as today |
| `acme:hq:alice` where that is mine | `acme:hq:alice` | `alice` | local |
| `acme:sales:bob` | `acme:sales:bob` | — | ⚠ **error at the sender**: no route |

⚠ **A bare name stays legal and means local.** `office send -a bob` must not
require anyone to type a qualified address.

**3. The switch reads L2 and nothing else.** It forwards on the L2 destination
exactly as it forwards on `recipient` today. ⚠ **It must never parse the L3
header** — if it does, this build has failed regardless of what the tests say.

## 3. ⚠ Compatibility, and the trap from build 49

This changes the wire. `clients/telegram/bot.py` and `clients/web/server.py`
both construct envelopes, and build 49 shipped nine client files still sending a
renamed field because a server-side change did not reach them.

**Decide and state which:** a frame-shaped envelope that old clients can still
produce (flat form accepted and upgraded at the adapter), or a hard v2 with the
clients changed in this build. ⚠ **Say which you chose in the report.** Do not
leave it implicit and do not discover it in a client's tests.

## 4. The benchmark — `container/scenarios/frame-bench.sh`

⚠ **Do not expect end-to-end throughput to move.** The delivery path is ~233 ms
of which the switch is ~0.3%. A frame that costs 50 µs more to build will be
invisible at 6/s. **Measure the parts, and use end-to-end only as a regression
gate.**

**a. Frame overhead, per send, in-process**
- assemble a flat envelope (today) vs a layered frame — µs, median of ≥400
- **bytes on the wire**: `len(json)` for both, and Redis `used_memory` delta
  across 2,000 sends. Headers are not free and the number should be known.

**b. Switch decision, per envelope, in-process**
- today's `is_member` path vs the L2-only path, medians, at rosters of
  **10 / 100 / 1000**
- ⚠ interleave A/B per iteration and report **medians**, not means. Measured:
  this host's loopback Redis averages 1.7 ms with 26 ms spikes, and means are
  meaningless against that.

**c. Regression gate, end to end**
- `fabric-bench.sh` at `STATIONS=100 ROUNDS=20`: **2,000 of 2,000, zero dead
  letters**, throughput **≥ 6/s** (current `main` baseline)
- ⚠ **one h-flock tenant at a time on the lab**, output redirected to a
  lab-local file — an SSH detach has already cost us one accept run's evidence

**d. The thing most likely to be wrong**
- a qualified local address and a bare address must produce **byte-identical L2
  behaviour** and a complete five-record custody set
- a non-local address must fail **at the sender** and emit a record — a silent
  refusal is worse than a dead letter

## 5. Done when

⚠ **Every gate below must be shown able to FAIL** — see
[`BUILD-CONVENTION`](BUILD-CONVENTION.md) §1. For this build the cheapest proof
is: point the switch at the L3 header on purpose and show a test go red. A gate
that has never failed is not known to work.

- all of §2, with the switch demonstrably never reading L3
- `frame-bench.sh` exists and its output is in the report
- `python3 -m pytest -q` green (350 on `main` at the time of writing)
- `container/accept.sh` green
- §3's compatibility choice stated explicitly

## 6. What is deliberately deferred

The router, RT tags, filtering, L4, and any second pod. **If you find yourself
needing any of them to finish this build, stop and tell me** — it means the
layering is wrong, and that is a finding worth more than the build.

## 7. Ownership

`bus` owns it end to end, including the adapter send path and any client change,
because splitting a wire change across lanes leaves the tree inconsistent
between pushes. `tmux` and `api` have been told.
