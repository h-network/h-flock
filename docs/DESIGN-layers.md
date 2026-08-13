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

## 2. The host decides local-or-gateway; the switch only forwards

This is how hosts and switches actually divide the work. A host consults its own
table, finds the destination is not on-link, and addresses the frame to the
**gateway's** address. The switch never knows a routing decision happened.

**Adapter (the host), once per send — three checks:**

1. is `destination` in the local VAB table? → address it directly
2. if not → is there a default route? → **address the envelope to the router**
3. do my export tags meet its import tags? → fail fast, with a real error at the
   sender

**Switch, once per envelope — two:**

1. destination → attachment (the forwarding table it already reads)
2. `source:destination` port ACL

⚠ **The switch's check is the enforcement; the adapter's is advisory.** The
adapter version exists for fast feedback and to avoid consuming the bus. A host
that lies or skips its checks still meets the port ACL. Remove the switch-side
check and this becomes good manners rather than a control.

⚠ **A wrong "local" decision is safe:** the switch finds no destination and
dead-letters, which is what a switch does with unknown unicast.

⚠ **The saving is real** even at equal lookup counts — the switch is shared, the
adapters are per-send and parallel. Resolution belongs off the hot path.

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
5. ⚠ **open** — default posture: allow-all or deny-all
6. ⚠ **open, and the one that gates everything** — envelope v2:
   `source`/`destination` **and the qualified address form**

⚠ **1–3 were listed open here after being decided, exactly as `GLOSSARY`'s table
was.** Renames 1–3 are executed and parked on `rename/vocabulary`; only 5 and 6
are live questions. **6 is the gate**: `rename/vocabulary` is parked until "the
new frame works", and the frame's first requirement is qualified addressing —
which changes the same envelope fields the rename does.
