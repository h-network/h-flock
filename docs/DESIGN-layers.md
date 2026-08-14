# The layer split — switch, router, and the tables they read

⚠ **This is the design h-flock has been built toward since January**, written
down for the first time. Nothing here contradicts what exists; the switch is
built, the router is not, and the pieces that were missing turn out to be a
field and a policy layer rather than a redesign.

## 1. Two components, two jobs

| | **switch** — L2, one per tenant | **router** — L3, per pod and between pods |
|---|---|---|
| forwards by | destination name, inside one tenant | qualified address `pod:tenant:agent` |
| table | `name → attachment` | `pod:tenant` prefix → next hop |
| policy | port ACL on `source:destination` | **RT import/export** at the domain boundary |
| knows about | its own tenant, nothing else | other tenants, other pods, how to reach them |
| built? | **yes** — `flock/switch` since build 56 | **no** |

⚠ **The switch never holds a route.** That is what keeps it fast, keeps topology
knowledge from spreading, and stops one tenant holding credentials for another's
store — the objection that killed the alternative design in
`LLD-bus-and-switch` §7.

⚠ **§7's "registry of enrolled tenants" was the right idea in the wrong
component.** It belongs in the router's table.

## 2. The adapter IS the port, and the port is where filtering belongs

⚠ **The component now called `port` — `adapter` until build 56 — is a switchport.** It belongs to exactly one
participant, it has a type (`port_type`: `tmux` / `api` / `control`), it is where
the participant meets the fabric, and it is the closest thing to the source. Once
named that way, three things that were separately decided turn out to be the same
decision.

### 2.1 Why the filter is at the port and not in the switch

On real hardware you filter on the switchport, and it is free — TCAM, per-port
silicon, line rate. **There is no software equivalent.** So "filter at the
switchport" does *not* translate to "filter in the switch process". It
translates to **filter at the port** — and in this architecture the software
sitting on the port is the port itself. The switch process is the analogue of the
*fabric*, not of a port.

⚠ **CORRECTED 2026-08-14. This section previously argued that policy belongs at
the port *because the switch is serialized*. Measurement says otherwise, and the
correct answer is not a placement at all — it is TWO DIFFERENT CHECKS at two
layers.**

| | what it checks | data | measured |
|---|---|---|---|
| **switch** | ⚠ **an L2 port ACL was DESCRIBED here and is NOT BUILT and NOT DECIDED.** §2.5 says switch policy is *none*, and the code has only a roster membership check. **The two sections contradicted each other; this is the open question, not a decision** | — | 0.2 µs *if* ever built |
| **sending port** | RT export/import tags | freshness-sensitive, read per send | 28–46 µs, invisible against a ~233 ms send path |
| **router's port** | L3 policy between domains | the router is a **station with a port like any other** | its own port's problem |

### ⚠ Confirmed in-system, build 54

The standalone model was reproduced **more strongly** on the lab, 600 samples
per cell, cases interleaved in rotating order so Redis spikes cannot privilege
a placement — `container/scenarios/policy-system-bench.py`, `interleaved_us()`:

| | measured |
|---|---|
| policy decision **at the port** | **1,036–3,523 µs** (284–965 decisions/s) |
| the same check **from the switch's memory** | **1.9–5.0 µs** (198k–525k/s) |
| forward-only vs **forward + policy from memory** | **within noise at every roster size** — 434.29 vs 420.35 (10/5), 774.80 vs 724.82 (100/5), 1521.21 vs 1562.10 (1000/5) |
| port-side **parallelism** | 1 port 1,337/s → 16 ports **2,269/s**. Host contention saturates long before port count does |

⚠ **Both halves of the original argument are refuted.** Switch-side policy is
not merely affordable, it is **unmeasurable against forwarding alone**. And
port-side parallelism does not rescue the port's cost — 16× the ports buys 1.7×
the throughput.

⚠ **Interaction with build 58's liveness finding:** policy is evaluated
**synchronously before enqueue**, so a port killed in the kick/pop strand window
cannot leave an ambiguous held decision. A stranded frame is always one that was
already permitted. The strand window sits entirely *after* the policy decision.

⚠ **The switch can cache and a one-shot port cannot** — that asymmetry runs
*opposite* to the argument this section used to make. From Redis the same check
costs the switch 254% over forwarding-only; from memory it costs 10%. **The
earlier 69% figure came from a benchmark that made the switch read Redis, which
contradicts §3.1's own decision. I stacked it and reported it as evidence.**

**Both are affordable in their own context and neither displaces the other.**
Port-side policy is justified by **feedback and freshness** — the error lands in
the sender's terminal instead of dead-lettering, and there is no cache to
invalidate — **not by cost.**

⚠ **`n²` is an argument about the DATA MODEL, not about placement.** Measured:
cost tracks tag-set size, not roster size — 30.6 / 28.3 / 29.5 µs at rosters of
10 / 100 / 1000. Tags beat pairs because of how they are stored, wherever the
check runs.

### 2.1a The router is a station, so it has a port

Nothing about the switch changes when the router arrives, and nothing special
is added anywhere: **the router is reached by name, and like every participant
it has a port.** L3 policy, qualified-address resolution and re-addressing all
happen *in the router's port*, which is the same machinery every other
participant already uses.

```
sending port  ── assembles, L2+L3 headers, RT check ──►  switch  ── L2 ACL + forward ──►  receiving port ── de-assembles, delivers by port_type
                                                            │
                                                            └─ destination is routerX ─►  router's PORT ── L3 policy, re-address ──► back onto the fabric
```

⚠ **Every hop is a port, and every port both assembles and de-assembles.** That
is the whole model: ports do the work, the switch moves frames.

### 2.2 The division

**Port, once per send — it builds and it filters:**

1. **build** — ⚠ **INTENDED, NOT BUILT.** `doors.send()` takes `source` from the
   **caller** and `require_allowed()` at `doors.py:34` evaluates policy against
   it; the switch only corrects `l2.source` at `switch/service.py:90`, **after** policy
   has run. Consistent with §2.3 (the port filters mistakes, not adversaries),
   but the port does **not** stamp identity. Making it structural is h-vab's
   bound-`Port` handle, recorded as *not taken* in `DECISION-h-vab`
2. is `destination` local? → address it directly
3. if not → is there a default route? → address the envelope to the **router**
4. do my export tags meet its import tags? → fail fast, real error **at the
   sender**

**Switch, once per envelope — one thing:**

1. destination → attachment, from the forwarding table (§3.1)

⚠ **The switch's read-set is exactly source, destination and its table.** That
is what the h-vab trial's switch did, and it is the same conclusion the FIB
decision reached from a different direction.

⚠ **A wrong "local" decision is safe:** the switch finds no destination and
dead-letters, which is what a switch does with unknown unicast.

### 2.3 ⚠ Placement, not enforceability

We inherit hardware ingress filtering's **placement** and none of its
**enforceability**. A real switch's ASIC enforces port security even though it
is configured per port; the host cannot bypass it. Here the port's filter runs
**in the participant's own process**, and `HLD` §10 is explicit — *"the container
is the boundary, and nothing inside it is"*, agents run with `sudo`. An agent can
skip `office send` and write Redis directly.

**So the port filters mistakes, not adversaries** — a wrong destination, a stale
name, a client left behind by a rename. That is most of what actually goes
wrong: build 49 shipped nine clients still sending `vab` and nothing caught it
until a participant silently mis-enrolled.

⚠ **An earlier version of this section said "the switch's check is the
enforcement; the adapter's is advisory". That was wrong in both halves.** The
port's filter is the real one, and the switch's ACL was never enforcement in a
security sense either — both live inside the boundary. Inside a tenant, both are
**hygiene**: defence in depth against bugs, arranged closest-to-source first,
exactly as you would order ACLs.

⚠ **The first filter in h-flock that is a genuine security control is RT
import/export at the router**, because it is the first one crossing a container
boundary, where the far side is a different trust domain. See §7.5.

### 2.4 Naming the port's two halves

⚠ **Do not name them `ingress` / `egress`.** Those words are already taken, and
they point the other way. `GLOSSARY` decided the *queues* are
participant-relative — `agent:<name>:egress` is what the participant sends — while
networking states a **port's** ingress from the *switch's* side. The same
component is then "the ingress filter" and `egress_adapter` at once.

**The port has a `send` half and a `deliver` half.** No direction word, no
viewpoint, and "the port's filter" is unambiguous because there is one filter and
it is on send.

| today | becomes |
|---|---|
| `port/send.py` — `office send` | the port's **send** half |
| `port/deliver.py` — kicked delivery | the port's **deliver** half |
| `agent:<name>:egress` / `:ingress` | **unchanged** — participant-relative |

### 2.5 The port assembles the frame, and filters BEFORE it assembles

⚠ **The port encapsulates. Nothing is stripped on the way out.** An earlier draft
of this document had the port "stripping the qualification" before handing the
envelope to the switch — that was wrong, and it created a problem that does not
exist. The qualification never needs removing, because **the switch was never
reading that header.**

```
telegram / web / an agent
        │  payload
        ▼
      PORT ── policy lookup (export tags vs import tags) ── denied → error AT THE SENDER
        │
        ├─ assembles:
        │     L2   source, destination (local)        ← the switch reads ONLY this
        │     L3   pod:tenant:agent, qualified        ← the router reads this
        │     L4   (reserved, later)
        │     payload
        ▼
      SWITCH ── two headers and a table (§3.1). Nothing else, now or later.
```

**This is why the asymmetry is not "the port does more work".** It is that the
two components hold *different kinds* of check, sorted by where each can afford
to live:

| | port | switch |
|---|---|---|
| policy | **long** — tag sets, intersections, per-destination rules | none |
| read-set | whatever it needs | **fixed and tiny**: two headers |
| runs | per send, **parallel**, in the sender's process | per envelope, **shared and serialized** |

⚠ **The L3 header rides along untouched** through the switch and is read only by
something that operates at L3 — the router. That is what makes the router a pure
addition: nothing about the switch changes when it arrives, because the switch
never looked at that header.

**Filter before assembly.** Every input to the decision exists before a single
header does:

| filter input | source |
|---|---|
| source | the port's own identity — it **is** the port |
| destination | the caller's argument |
| my export tags, its import tags | policy tables |

Nothing in the frame is an input to the decision, so assembling first is pure
waste on the deny path — and the deny path is the one that should be cheap and
loud. It also gives a better error: *"you may not send to `acme:sales:bob`"* is a
statement about intent, where assembling first leaves you explaining why a frame
you already built is being discarded.

⚠ **A refusal must still emit a record** — source, destination, reason. That
needs no frame. Without it a denied send is invisible to the custody log, which
is the only observer this system has.

⚠ **The caveat, to know rather than design for:** filter-before-assembly holds
only while no policy depends on something the assembled frame alone knows. Today
none does — `kind` is supplied by the caller. If an L4 header ever carries a
value *derived* during assembly, that rule specifically would have to move after.

**Order: resolve → filter → assemble → hand to the switch.**

## 3. The VAB table

One table, two readers. It carries forwarding *and* membership, because with
communities the policy is computed rather than stored:

```
name        alice
attachment  tmux              ← how delivery happens (today's roster value)
export      [hq, reviewers]   ← RTs this participant advertises
import      [hq, ops]         ← RTs it accepts from
```

**May `alice` reach `bob`?** — does anything in `alice.export` appear in
`bob.import`. Two lookups and a set intersection.

⚠ **This retires the `source → destination` allow-list.** Pairs are *n²* and
have to be edited whenever anyone is hired; tags are one row per participant and
give group addressing for free.

✅ **Decided: tags live in a companion key, not the roster hash** — see §3.1,
which is the general form of the same rule.

**Open:** the default posture: no tags means allow-all (nothing breaks) or
deny-all (secure, breaks every tenant). A switchport defaults to permit; a
firewall defaults to deny. **This is a switchport.**

## 3.1 The forwarding table is DERIVED from the roster, never the roster

⚠ **The roster is the control plane.** It carries what a participant *is* —
attachment, `export[]`, `import[]`, provider, launch. The switch needs one
question answered — *where does this destination's ingress live* — and must
read a table that holds only that.

This is **RIB versus FIB**, and the sharpest form of it is the **MPLS label
FIB**: the lookup key is an opaque local index, not the destination address, so
a forwarding decision is one exact-match hit with no address structure to parse
and no attributes alongside it.

| | roster — RIB | forwarding table — FIB |
|---|---|---|
| holds | everything about a participant | precomputed key → ingress queue |
| read by | hire, presence, policy, console | the switch, per envelope |
| lives in | Redis | the switch's memory |
| changes on | enrol / retire | invalidate on the same events |

**Measured, and both are the same mistake in different places:**

- the trial fetches the whole roster per packet — `members()` is `HGETALL`
  against `main`'s single-field `HEXISTS`: **957 µs vs 498 µs at 100 stations,
  5,623 µs vs 1,646 µs at 1,000**
- even held in memory, its lookup rebuilds `{f"{domain}/{station}" …}` on every
  call, so the table is **O(N) where a FIB is O(1)** — 5 µs at 10 stations,
  293 µs at 1,000

⚠ **The payoff today is not speed.** At ~390 ms of serialized work per envelope
(`subprocess.Popen` per delivery, `switch/service.py`), a 1 ms lookup is
0.3% either way. The reason to separate the tables is that **the hot path must
not carry policy** — the moment `import`/`export` land in the roster row, a
switch that reads the roster is reading policy per frame, which is the design
error the split exists to prevent.

## 4. RD, and why qualified addressing is a prerequisite

| BGP/MPLS | h-flock | state |
|---|---|---|
| **RD** — makes an address unique across domains | `pod:tenant` | **in the keys, absent from the envelope** |
| **VRF** — the routing domain | `tenant`, and the container | built |
| **RT** — import/export community | membership tags | not built |

`"recipient": "alice"` is a bare name. **You cannot reach `alice` on another pod
without saying which `alice`**, so qualified addressing is not a nice-to-have —
it is the precondition for the router existing at all. `LLD-bus-and-switch` §7
already lists it as undesigned.

## 5. How the router's table gets filled

- **Static, first:** configure a peer and list what it serves. Enough to build.
- **Advertised, later:** routers exchange reachability — pod A's router tells
  pod B which VABs it serves and with which RTs attached; B's import policy
  decides what it accepts.

⚠ That is BGP's shape, and it matters for a reason beyond elegance: **no central
registry**, so no single point of failure and no component that must know the
whole network.

## 6. What this settles

- **the §7 fork** — a branch in the forwarding path versus a participant. Once
  the L2 component is a *switch*, a routing branch inside it is a category
  error. The router is a separate component, reached by name.
- **ACL scaling** — tags, not pairs.
- **where the registry lives** — the router, not the switch.
- **why `VAB` felt wrong** — it names the address concept, and had been attached
  to the roster's value, which is an attachment type.

## 7. What is still open

1. ✅ **decided** — roster value is `port_type`
2. ✅ **decided** — `endpoint` → `provider`
3. ✅ **decided** — `egress_adapter`/`ingress_adapter`, **participant-relative**
4. ✅ **decided** — tags in a companion key; the switch reads a derived FIB, not
   the roster (§3.1)
5. ✅ **decided — the default posture is SPLIT, because the question was wrong**

   Asking "allow-all or deny-all" as one global choice assumed one kind of
   filter. There are two, and they sit on opposite sides of the only boundary
   that actually holds (§2.3):

   | where | what it is | default |
   |---|---|---|
   | within a tenant | switchport, **hygiene** | **permit** — no tags means reachable |
   | at the router, between tenants or pods | firewall, **real trust boundary** | **deny** — no import tag means unreachable |

   ⚠ Same mechanism, opposite defaults, and the reason is not taste: it is
   whether the filter spans a boundary that can be enforced. Inside the
   container nothing can be, so a deny-default there buys nothing and breaks
   every tenant.
6. ⚠ **open, and the one that gates everything** — envelope v2:
   `source`/`destination`, **the qualified address form, and the L2/L3 split**
   (§2.5). The envelope stops being flat and becomes a frame with headers.
   ⚠ The switch reads **L2 only**, so it does not change now and does not change
   when the router arrives.

⚠ **1–3 were listed open here after being decided, exactly as `GLOSSARY`'s table
was.** Renames 1–3 are executed and parked on `rename/vocabulary`.

✅ **6 was the gate and it is MET.** Build 53 landed the frame — qualified
addressing accepted, the port resolving, the switch reading L2 only. The rename
unparks in build 56.

✅ **The switch is functionally done.** Measured across the frame change: the
forwarding decision is 795.85 µs → 791.47 µs at roster 100, unchanged, because
it reads L2 and is invariant to headers it does not touch. L4 will cost it
nothing either.

⚠ **It is *approximately* header-independent, not truly so.**
`parse_for_switch` decodes the whole JSON — L3 and payload included — to read
L2. A real switch reads fixed-offset bytes and never touches the payload. At
+77 bytes that is invisible against a 1.7 ms Redis round trip, which is why the
number did not move. **If frames grow substantially the switch starts paying for
headers it does not read**, and the fix is framing that exposes L2 without
parsing the rest. That, not throughput, is what would falsify "the switch is
done".

⚠ **A consequence discovered by build 53 and resolved by build 63:** the frame
is a **hard v2** — flat v1 is rejected. That was initially free because Redis ran
without persistence. Build 63 resolved the coupling by separating **durable
application state** (boards, streams) from **ephemeral transport state** (queues).
Redis runs with AOF persistence enabled (`appendonly yes`, `appendfsync everysec`),
and `container/entrypoint.sh` runs `purge_transport` at boot before any consumer
starts. Transport queues (`ingress`, `egress`, `dead`) and delivery locks
(`delivering`) are purged, while task boards and streams survive intact. This
preserves the hard-v2 wire property without requiring dual-read windows across
restarts.

---

## 8. ⚠⚠ BLOCKED — DO NOT BUILD. Three independent reviews found this design does not compose

> ⚠ **`api`, `bus` and `tmux` reviewed this section separately and converged.**
> The recovery design below **cannot be built as written**. Three structural
> problems, each of which invalidates part of it:
>
> **1. The stale `delivering` tag defeats re-kick.** `run_port` loops on `HSETNX`
> until success and only clears in `finally`, which `SIGKILL` skips. So a holder
> killed after acquisition wedges that agent **permanently**, and re-kicking it
> creates *more processes that wait forever* without restoring liveness.
> `tmux`: *"Re-kick alone can turn one stranded frame into an unbounded set of
> waiting port processes."* **Ownership must be solved first** — a lease with
> expiry, or explicit stale-owner reconciliation.
>
> **2. `Ping`'s "the record is the reply" is false.** ⚠ Custody records go to
> **PID 1 stdout**, and the watchdog reads neither `docker logs` nor any durable
> ledger. **There is no path by which the watchdog observes the reply.** A probe
> needs correlated, readable state — which is `bus`'s "durable custody ledger"
> finding arriving from a second direction.
>
> **3. Depth cannot distinguish slow from dead.** All three said this
> independently.
>
> ⚠ **PARTLY RESOLVED by build 67, and the example was wrong.** `api` argued a
> healthy agent running a long tmux command holds a climbing queue. **It does
> not.** `paste_text` (`tmux/ops.py:371`) pastes and sends Enter immediately with
> no readiness check, and `message_opener` has none either — **delivery is
> fire-and-forget into the pane.** A busy agent's queue drains at the normal
> rate; the agent's own slowness never reaches the queue.
>
> **So the discriminator is PROGRESS, not depth**, which is `tmux`'s build-67
> observation A:
>
> | | depth | pops/opens |
> |---|---|---|
> | healthy under burst | climbing | **occurring** |
> | dead or wedged | climbing | **zero** |
>
> ⚠ **What remains genuinely unresolved** is how long an absence of progress must
> last before it means dead, and that is a threshold question rather than a
> signal question. Build 67 measured the fault shapes; it did not pick the
> number.
>
> ### ⚠ Demonstrated on ourselves, 2026-08-14 — and it defeats the obvious fix
>
> The **office's own watchdog** flagged a lane as *"likely stuck rather than
> slow"* after 5 minutes of silence. Its presence state independently read
> **`wedged`**. I treated those as two signals agreeing and concluded the lane
> was stuck.
>
> **It was not.** The lane was *deliberately waiting for the lab*, because I had
> told it to wait. It was following instructions and was flagged for it.
>
> ⚠ **Correlating those two signals proved nothing, because they are not
> independent.** "No progress seen" and "presence says wedged" are both functions
> of *nothing happened*. **I mistook a second reading of the same observation for
> a second source.**
>
> ⚠ **The only thing that resolved it was the participant SAYING so.** Not depth,
> not progress, not presence, not elapsed time.
>
> **So for a general destination the discriminator cannot be inferred from
> outside.** It needs either a declaration the participant makes, or an active
> probe it must answer. Stacking more passive signals does not help — they are
> one observation wearing different hats.
>
> ⚠ That is the argument **for** something Ping-shaped, and `tmux` already
> established why the current design fails: **nothing reads the reply.** Both
> halves are now known, which is more than we had this morning.
>
> ⚠ **It fired a SECOND time on the same correct behaviour**, seven minutes
> later. The lane was still waiting, still correctly. **That is the cost of a
> watchdog that cannot tell waiting from stuck: not a wrong answer once, but the
> same wrong answer forever**, until a reader stops believing it.
>
> ✅ **And the second firing gives a third discriminator, cheaper than the other
> two: KNOWN BLOCKING.** The lane was waiting on a resource held by another
> lane — a fact the *system already had*. It did not need to infer liveness or
> ask anyone.
>
> **The h-flock analogue is exact:** a port waiting on `delivering` is blocked on
> a lock whose **holder is recorded in that very hash**. A watchdog that reads it
> knows the difference between *waiting for a known holder* and *nothing is
> happening*, with no probe and no declaration.
>
> | discriminator | cost | covers |
> |---|---|---|
> | **known blocking** — is it waiting on something we recorded? | free, already stored | the wedged-tag case |
> | declaration | needs a protocol | intentional idleness |
> | active probe | needs a reader for the reply | genuine liveness |
>
> ⚠ **Score after one afternoon: three alerts, two different lanes, ZERO true
> positives.** Both were blocked on the **lab**, held by the other, in a sequence
> *I* set. Presence read `wedged` for both.
>
> **A monitor with a 100% false-positive rate is worse than no monitor**, because
> it trains its reader to disbelieve it — and the fourth alert is the one that
> matters.
>
> ⚠ **All three would have been silent under `known blocking` alone.** The system
> held the answer every time: which lane had the lab. It never needed to infer
> liveness, ask anything, or wait out a threshold.
>
> **In h-flock that fact is the `delivering` hash**, which records the holder. A
> watchdog reading it before alerting separates *waiting for a known holder* from
> *nothing is happening* — for free, and it would eliminate this entire class of
> alert.
>
> ⚠ **§8.1–8.4 below are retained as the record of the reasoning, not as a
> buildable design.** The parts that ARE settled: the fix belongs in the port and
> the watchdog rather than the switch; ingress must be bounded at forward time
> (§8.3); a kicked port losing `HSETNX` should exit rather than spin.

> ⚠ **STATUS — read this before implementing anything below.** `api`'s design
> review found that this section, §8.1, §8.2 and §3.1 **state intent in the
> present tense**, which reads as description of built behaviour. It is not.
> That is the exact defect `GLOSSARY` exists to prevent — *built* versus
> *intended* — committed in the document that defines the discipline.
>
> | claim | actually |
> |---|---|
> | the port drains until empty | ⚠ **NOT on `main`** — build 66, in flight. `deliver.py` calls `receive(blocking=False)` once and exits |
> | the watchdog watches and clears the queue | ⚠ **NOT BUILT.** `watchdog/service.py`'s own docstring says *"without repairing either"*; it never inspects ingress, re-kicks, or dead-letters |
> | the switch reads an in-memory FIB (§3.1) | ⚠ **NOT BUILT.** `switch/service.py:28,67,115` call `members()` and `is_member()` against Redis every time |
> | strand exists and is measured | ✅ **built and measured** — build 58, 2 of 5 port kills |
> | ingress is unbounded | ✅ **verified** — retention trims only `dead` and `tasks.done` |

Build 58 proved a frame can strand: the switch forwards, kicks a port, and that
port dies before it pops. **The obvious fix — a sweeper that scans ingress — is
the wrong one**, because it puts periodic work in the one component whose cost
cannot be parallelised. *We do not slow down the switch.*

**The receiving port owns this**, and it already has everything it needs:

- `receive()` handles **exactly one** envelope per invocation and returns
- so a kick that dies strands whatever was waiting, until the *next* kick — which
  drains one, leaving the newest stranded instead. That is the permanent
  off-by-one build 58 measured

⚠ **BUILT, MEASURED, AND REJECTED — build 66.** Draining works and is not worth
it.

| | |
|---|---|
| strands | **2 → 0**. The off-by-one is real and draining clears it |
| delivery | 9997 → 9998 |
| duplicates | 0, unchanged |
| **throughput** | **6.45 → 5.54/s, −14.1%** |

⚠ **The cost is structural, not tunable.** The `delivering` tag serialises
delivery **per agent**. Before, 32 kicks meant 32 ports each handling one frame
with their startup costs **overlapping in parallel**. Draining makes one port do
32 frames **sequentially** while the rest exit. Startup dominates the path —
~230 ms against ~20 ms of real work — so **overlapping 32 startups beats
amortising one**. No cap value fixes that; it is the shape of the change.

⚠ **And the trade is wrong on its merits.** The cost is **unconditional**: 14%
on every delivery, forever. The benefit is **conditional on ports dying**, which
only happened because we killed them. In a healthy system a strand is a lag of
one frame that the next kick clears; it becomes a real loss only at end of
traffic — and **that terminal case is the watchdog's, and draining does not solve
it either**.

⚠ **`exit-not-spin` is coupled to this and also does not ship.** Without
draining, a kicked port that exits on losing the tag leaves its frame for the
next kick — which *is* the strand mechanism. The two are one change, and neither
lands.

**So the port keeps taking one envelope per kick.** The off-by-one stays, and it
is the watchdog's problem — which is blocked, honestly, rather than papered over
with a 14% tax.

⚠ **This does not need an observer, a sweeper, or any switch change.** The cost
is borne per delivery, in a process that is already running, and it is parallel.

⚠ **One residual case survives:** if the port handling the **final** envelope
dies and no further kick ever arrives, that frame strands permanently. Draining
shrinks the window from *every killed port* to *only a killed port with no
successor* — exactly the condition build 58 hit, because its producer had
stopped.

✅ **The residual belongs to the WATCHDOG. No new observer.** `flock/watchdog`
is already the periodic observer: it polls agents, reads presence and activity,
judges blocked and absent, and raises alerts. **Ingress non-empty with no
progress is the same shape of question it already answers** — and it lives
outside the switch, so noticing costs the forwarding path nothing.

⚠ **Three components, three jobs, and none of them the switch:**

| | job | cost borne |
|---|---|---|
| **port** | drain until empty | per delivery, parallel, already running |
| **watchdog** | notice a queue that stopped moving | periodic, outside the hot path |
| **switch** | ⚠ **nothing. It forwards.** | unchanged |

### ✅ The watchdog WATCHES the queue and CLEARS it — that is the name

⚠ **An earlier version of this section said the watchdog must only alert, on the
grounds that re-kicking is a retry. That was wrong.** A stranded frame is sitting
in ingress **never popped and never delivered**. Kicking a port to pop it is a
**resumption, not a retry** — at-most-once promises not to deliver twice, and
nothing has been delivered once.

⚠ **Watch the QUEUE, not the envelope.** Tracking individual frames runs into the
finding from build 65 — exact post-pop loss attribution may need a durable
custody ledger. Asking *"is this queue non-empty and not decreasing?"* needs no
ledger, and it catches both failures at once:

| | what it looks like | what the watchdog does |
|---|---|---|
| **A — strand** | depth stuck, not decreasing | **re-kick**; a port drains it. Recovery |
| **B — destination cannot consume** | depth **climbing**; re-kicks change nothing | **dead-letter**; the queue is bounded and `dead_lettered` is the record |

**The distinguisher is whether depth decreases after a kick.** For A it does; for
B it does not, and further kicks only spawn doomed processes.

⚠ **Case B is unbounded today and untested.** `retention` trims `dead` and
`tasks.done` and **never touches ingress**; every `maxlen` in the tree is on a
stream, never on the ingress list. So a destination that is enrolled, permitted,
and permanently unable to consume grows its queue until the container runs out
of memory, with **no cap, no dead-letter, and no alert**. Build 58 injected port
*kills*, which is case A. **Nobody has ever run case B.**

⚠ **Dead-lettering is what bounds it**, and it needs no new machinery: `dead` is
already trimmed by retention and already has a record type.

### 8.1 ⚠ h-flock needs an ICMP capability. Where each part lives depends on WHO KNOWS

⚠ **An earlier version of this section claimed "the watchdog IS h-flock's ICMP".
That was my overstatement, not the operator's point.** He said the ICMP
*feature* is needed somewhere and guessed the watchdog. Consolidating all of it
into one component is wrong, and the reason is instructive.

**Split by who has the information at the moment of failure:**

| failure | who knows, and when | who should say so |
|---|---|---|
| destination not in roster | **the switch, immediately** | the switch — it is already dead-lettering |
| policy denied | **the sending port, before assembly** | the port — already does, `send_refused` |
| unknown `kind`, opener raised | **the receiving port, immediately** | that port — already dead-letters |
| **strand** — kicked port died before popping | ⚠ **nobody, ever** | **the watchdog. Only it looks later** |
| **destination cannot consume** | ⚠ **nobody at the time; visible only as depth over time** | **the watchdog** |

⚠ **The first three need no watchdog at all.** The detector already knows and is
already emitting a record — it simply does not tell the **source**. Turning that
into a notification is a frame addressed back to the origin, travelling the
normal path. `BUILD-57`'s content applies there, at the point of detection.

⚠ **Only the last two are the watchdog's**, and precisely because *nothing else
can see them*. That is the real dividing line, not "ICMP-ness".

**A liveness probe, if we want one**, needs no new mechanism: openers are
per-kind, so a **`Ping` kind with a no-op opener** traverses the whole real path
— forward, kick, spawn, pop, open — and emits ordinary custody records while the
agent sees nothing. **The record is the reply**, and it exercises the real path
rather than a proxy for it. Whether the watchdog is the right prober is a
separate question from whether the probe is the right mechanism.

### 8.2 ⚠ Age on FAILURE, not on silence

MAC aging drops an entry after N seconds without traffic, and that is safe on
Ethernet **only because unknown unicast is flooded** — the frame still arrives,
the reply re-learns the entry, nobody notices.

**We cannot flood. We dead-letter.** So aging on silence would break a
legitimately quiet participant: an agent receiving nothing for an hour ages out,
and the next message to it dead-letters though it was perfectly healthy.

**So the closer model is NUD** — `REACHABLE → STALE → PROBE → FAILED` — driven by
whether traffic gets through, not by elapsed quiet. A successful delivery
refreshes; the watchdog probes when in doubt; only repeated failure ages an entry
out.

⚠ **None of this is needed yet.** The switch holds **no** in-memory table today —
`_agents()` and `is_member()` read Redis per use — so a watchdog write is visible
to the switch on the very next envelope, with no reload, no invalidation and no
message between them. **This section is the answer to the invalidation question
that arrives with the FIB (§3.1), recorded now because it is much harder to
reconstruct mid-build.**

### 8.3 ⚠ Two objections from `api`'s review that change the design

**1. Bound ingress at FORWARD time, not by culling later.** `api` proposed an
`INGRESS_MAX` enforced in the switch: if the destination's queue is full,
dead-letter immediately. That gives **synchronous attribution** — a record, at
the moment, naming the destination — instead of silent background eviction by a
watchdog racing a live port.

⚠ **And it costs nothing.** `RPUSH` **returns the new list length**. The switch
already calls it, so the bound is a comparison on a value it is handed for free
— no extra Redis round trip, no `LLEN`, no new read. This is strictly better
than what §8.2 proposed and it is `api`'s, not mine.

**2. ⚠ A busy agent is indistinguishable from a dead one by depth alone.** This
may kill the depth-based watchdog design as written. An agent running a long
command in tmux holds a climbing queue for **minutes** and is perfectly healthy.
A watchdog that dead-letters on climbing depth would destroy legitimate work.

⚠ **Depth alone is not a liveness signal.** Whatever the watchdog does must
distinguish *slow* from *dead*, and §8.2 does not. That is unsolved, and
`presence` and `activity` — which the watchdog already reads — are the obvious
place to look, since they are how the system already tells busy from absent.

⚠ **Both of these were asserted in §8.2 without evidence and neither has been
tested.** Recorded as objections, not as decisions.

### 8.4 ⚠ The `delivering` tag: a THIRD watchdog job, and a worse failure than the strand

Measured by `bus` during build 66's conservation run — **a real herd, not a
theoretical one**: 8–17 concurrent `flock.port` processes, Redis at 136–308
ops/s, container CPU **774%–1285%** (7.7–12.8 cores). ⚠ Throughput **held** at
~8.7/s against a 6.45/s baseline, so this is load without loss. No pre-66
process-count baseline exists, so no honest before/after can be given.

**Two changes follow.**

**1. A kicked port that loses `HSETNX` should EXIT, not spin.** Today it loops on
`hsetnx` with `sleep(0.05)` forever. The holder is already draining, and any
later write arrives with its own kick, so a waiter contributes nothing but 20 Hz
of Redis load and a process. ⚠ **Draining made this worse** — the holder now
holds for up to 32 frames instead of one, so waiters wait far longer.

**2. ⚠ A holder killed after `HSETNX` wedges that destination permanently.**
`finally: hdel` does not run on `SIGKILL`, and audit row 16 recorded non-expiry
and non-takeover as **deliberate** — the tag prevents two ports delivering the
same agent, which protects at-most-once. So the trade is deliberate: **safety
over liveness**, consistent with everything else here.

But the consequence was never stated: **every subsequent kick for that agent
spawns a port that spins forever.** That is worse than a strand — a strand loses
one frame, a stuck tag wedges the destination *and* accumulates processes.

⚠ **So the watchdog has three jobs, not two**: stuck queues, climbing queues,
and **stale `delivering` tags**. And the third is a precondition for the others —
**re-kick cannot resume a wedged agent while the tag is held.**

⚠ **Clearing a stale tag is the one watchdog action that can break at-most-once**
if it is wrong: clear it while the holder is alive and two ports deliver the same
agent. Liveness of the holder must be established before the tag is cleared, and
that is exactly the *slow versus dead* problem §8.3 records as unsolved.