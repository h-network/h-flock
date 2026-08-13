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
| built? | **yes** — it is `flock/router` today, misnamed | **no** |

⚠ **The switch never holds a route.** That is what keeps it fast, keeps topology
knowledge from spreading, and stops one tenant holding credentials for another's
store — the objection that killed the alternative design in
`LLD-bus-and-router` §7.

⚠ **§7's "registry of enrolled tenants" was the right idea in the wrong
component.** It belongs in the router's table.

## 2. The adapter IS the port, and the port is where filtering belongs

⚠ **The component we call `adapter` is a switchport.** It belongs to exactly one
participant, it has a type (`port_type`: `tmux` / `api` / `control`), it is where
the participant meets the fabric, and it is the closest thing to the source. Once
named that way, three things that were separately decided turn out to be the same
decision.

### 2.1 Why the filter is at the port and not in the switch

On real hardware you filter on the switchport, and it is free — TCAM, per-port
silicon, line rate. **There is no software equivalent.** So "filter at the
switchport" does *not* translate to "filter in the switch process". It
translates to **filter at the port** — and in this architecture the software
sitting on the port is the adapter. The switch process is the analogue of the
*fabric*, not of a port.

⚠ **The argument is scaling, not current load.** Measured: the forwarding
decision is ~500 µs at 100 stations against a ~160 ms per-delivery path — about
**0.3%**. The switch is not busy today, and any claim that it is can be
disproved in ten minutes. The real point is that **the switch is the one
component whose cost cannot be parallelised**, while ports are per-send and
concurrent. A `source:destination` pair ACL is *n²* and RT tag intersection is
per-envelope set work; both compound in exactly the wrong place.

### 2.2 The division

**Port, once per send — it builds and it filters:**

1. **build** — stamp `source` from the port itself, not from a caller argument
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
| `adapter/cli.py` — `office send` | the port's **send** half |
| `adapter/runner.py` — kicked delivery | the port's **deliver** half |
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
(`subprocess.Popen` per delivery, `router/service.py:31`), a 1 ms lookup is
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
it is the precondition for the router existing at all. `LLD-bus-and-router` §7
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
was.** Renames 1–3 are executed and parked on `rename/vocabulary`; only 5 and 6
are live questions. **6 is the gate**: `rename/vocabulary` is parked until "the
new frame works", and the frame's first requirement is qualified addressing —
which changes the same envelope fields the rename does.
