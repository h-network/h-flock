# Glossary — the words, and what they were coined for

⚠ **This document exists because the design was consistent and the vocabulary
was not written down.** h-flock has been built on one model since January 2026 —
a network: chassis, routing domains, stations, addresses, policy. The names carry
that intent. Until now the intent lived outside the repository, so three
independent readers reconstructed three plausible substitutes and none of them
matched.

Each entry says what a word means, **its networking origin**, **what it does not
mean**, and whether the thing it names is **built** or **intended**.

⚠ **Draft.** Entries marked ✱ are the operator's own definitions and are
authoritative. The rest are drafted from the code and the naming inventories
(`NAMING-bus.md`, `NAMING-api.md`, `NAMING-tmux.md`) and need his correction.

---

## The address model

### ✱ `pod`
**A machine running agentic work** — a server, a PC, a container. It is
physically somewhere: a datacentre, a room in a datacentre.

- **networking:** the chassis. The PE router the VRFs are configured on.
- **not:** a Kubernetes pod. Not a tenant. Not a logical grouping of agents.
- **state:** present in every Redis key (`pod:acme:…`) and in `prefix()`.
  ⚠ **Never yet used to distinguish anything**, because nothing routes between
  pods.

### `tenant`
**An isolated office on a pod.** Its own roster, boards, queues and windows. Two
tenants may both have an `architect` and never collide.

- **networking:** the **VRF** — an independent routing domain on shared
  infrastructure.
- **not:** a customer, a billing unit, or a security boundary between agents.
  ⚠ The container is the boundary (`HLD` §10); the tenant is the *routing*
  domain.
- **state:** built. One container is one tenant.

### ✱ `VAB`
**The `pod:tenant:agent` concept** — the identity of a participant expressed in
community notation.

- **networking:** BGP **communities**, and specifically the **route target**
  idea: a tag you match policy against rather than a path you walk.
- **not:** ⚠ **the roster value.** `tmux` / `api` / `control` has been carrying
  this name and is not this concept — it is an attachment type (below).
- **not:** "virtual agent base". That expansion appears in the first
  architecture commit and every document since; it was never the intended term
  and only makes sense for one of the three values it was applied to.
- **state:** ⚠ **the notation exists, the semantics do not.** Keys are
  community-shaped; nothing matches on them.

### `RD` — route distinguisher *(intended, unnamed in code)*
**What makes an address unique across domains**: `pod` + `tenant`.

- **networking:** the RD, which travels *with* a VPNv4 route so two VRFs can
  advertise the same prefix.
- **state:** ✅ **now on the wire.** Build 53 gave the frame an `l3` header
  carrying `pod:tenant:agent`, and the port resolves local-vs-remote before
  assembly. ⚠ Nothing yet *routes* on it — a non-local destination is refused at
  the sender, because the router does not exist.

### `RT` — route target / community *(intended, not built)*
**Membership and policy**: which participants and which domains may exchange
traffic, expressed as tags rather than as pairs.

- **networking:** the extended community controlling import and export. A route
  carries several; a VRF imports a set.
- **why it matters:** an ACL of `source → destination` pairs does not scale;
  tag matching does, and it gives group addressing for free. The gateway becomes
  import/export rather than a registry of remote tenants.
- **state:** **not built.** This is the piece the name `VAB` was coined for.

---

## Participants

### `participant`
**Anything that talks on the bus** — a terminal agent, an app client, the
lifecycle endpoint. Defined in `LLD-bus-and-switch` §1 and under-used since:
82 occurrences against 976 of `agent`.

- **not:** a synonym for `agent`. `api` and `control` participants have no
  window, which is the point.

### `agent`
**A participant that runs a CLI.** Scopes correctly to a future `oneoff` or
other attachment types.

### ✅ `port_type` — the roster value: `tmux` / `api` / `control`
**How a participant is attached, and therefore how delivery happens.** A window,
a mailbox, or an opener.

- **networking:** the port type — a property of the port, not of the frame.
- **decided:** `port_type`. The HLD's own switch table already calls it *"port
  config — a property of the port, not of the frame"*, so the docs were using
  the word informally before it was chosen.
- **was called:** `vab`, which belongs to the address model above.

### `roster`
**`name → attachment` for a tenant.** The MAC table: membership and port type,
nothing else.

---

## Moving an envelope

### ✅ `switch` — was `router`
The forwarding component moves envelopes between participants **inside one
tenant** by destination name. That is switching, and `HLD.md:17` already opened
with `| L2 switch | h-flock |`.

**Executed** on `rename/vocabulary`: `flock/router` → `flock/switch`, 104 code
and 423 prose replacements. ⚠ It reads **one** thing per envelope — destination
→ attachment. The port does the filtering (`DESIGN-layers` §2).

### `router` — the L3 component *(reserved, not built)*
**Reads what the switch will not**: applies RT policy, resolves qualified
addresses, re-addresses. Reached **by name, like any participant** — as hosts
reach a default gateway.

⚠ **The fork is resolved**: `LLD-bus-and-switch` §7 designed it as a branch
inside the forwarding path, §3.2 as a participant. Once the L2 component is a
*switch*, a routing branch inside it is a category error, so it is a separate
component reached by name.

⚠ **It is the first place a filter is a real security control**, because it is
the first one crossing a container boundary — `DESIGN-layers` §2.3 and §7.5.

### `kind`
**What the payload is.** The ethertype: the switch ignores it, an opener at the
far edge reads it.

### `opener`
**The thing that knows how to deliver one `kind`** at the far edge.

### ✅ `port` — was `adapter`
**The switchport a participant is attached to.** It belongs to exactly one
participant, it has a `port_type`, and it is where that participant meets the
fabric. It **builds** (stamping `source` from the port, not from an argument)
and it **filters** — it is the closest component to the source, which is where
filtering belongs.

- **networking:** the access port. `port_type` is literally its type, which is
  why that name fitted before anything was called a port.
- **not:** a TCP port, and not a security boundary — see `DESIGN-layers` §2.3.
  The port filters **mistakes, not adversaries**; `HLD` §10 makes the container
  the boundary and an agent with `sudo` can bypass any of this.
- **halves:** the port **sends** (`port/send.py`) and **delivers**
  (`port/deliver.py`).

### ⚠ `ingress` / `egress` — the QUEUES only, never the port's halves
`agent:<name>:egress` is what the participant sends; `agent:<name>:ingress` is
what it receives. **Relative to the PARTICIPANT**, as a host's rx and tx. The
switch has no queues of its own: it reads a participant's egress and writes a
participant's ingress.

⚠ **This is why the port's halves are `send` and `deliver` and not
`ingress`/`egress`.** Networking states a *port's* ingress from the **switch's**
side — traffic entering the fabric — while these queues are named from the
participant's. The same component would be "the ingress filter" and
`egress_adapter` simultaneously. Naming the halves by what they do removes the
viewpoint question instead of answering it twice.

⚠ **The queues keep the participant's viewpoint.** Flipping them would invert
`agent:<name>:egress` without breaking anything mechanically, so every existing
log line and document would quietly read backwards — and it is a Redis key
change on top.

### `door`
**An HTTP surface the outside world reaches**: the api door (`:8080`) and the
session door (`:8081`).

### `producer` / `recipient` ⚠ *mixed pair*
The source and destination addresses of an envelope. producer↔consumer,
sender↔recipient, **source↔destination** — the model says the third.
352 occurrences, and they are wire fields, so changing them is an envelope v2.

---

## Elsewhere

### ✅ `provider` — was `endpoint`
Currently **the model an agent talks to** — `agent:<name>:endpoint`,
`ENDPOINT_*`, vLLM or ollama. In the network model an endpoint is an addressable
termination, which is the opposite end of the meaning.

- **decided:** `provider`. It names which inference service an agent's CLI
  talks to, with its credentials and model ids — `agent:<name>:provider` holds
  the *name*, `PROVIDER_<NAME>_URL` holds the address, deliberately split so an
  agent cannot read or change the URL. Producing `ANTHROPIC_BASE_URL`,
  `ANTHROPIC_AUTH_TOKEN` and the three tier model variables in the window.
- **frees `endpoint`** for its networking meaning, which is why it collided.

### `launch`
The Redis key holding **which CLI a participant runs**. `cli` or `runtime` says
it; 60 occurrences, contained.

### `board`
An agent's task list — `todo → doing → hold → done`. Pull-based.

### `host` ⚠ *conflated three ways*
The fixed lifecycle participant (`vab: control`), the tmux window reconciler
(`flock/tmuxhost`), and the machine. Searching finds all three.

---

## Open decisions

| # | decision | status |
|---|---|---|
| 2 | `router` → `switch` | ✅ **decided** — it switches within a tenant |
| 3 | `producer`/`recipient` → `source`/`destination` | ✅ **decided** — envelope v2 |
| 6 | the gateway fork | ✅ **resolved by 2** — a routing branch inside a *switch* is a category error, so the router is a separate component reached by name |
| 7 | RD in the envelope | ✅ **required, not optional** — inter-pod addressing is impossible with a bare name (`DESIGN-layers` §4) |
| 1 | roster value (`tmux`/`api`/`control`) → `port_type` | ✅ **decided** — the HLD's switch table already called it a port property |
| 4 | `endpoint` → `provider` | ✅ **decided** — frees `endpoint` for its networking meaning |
| 5 | adapter names — and from whose viewpoint | ✅ **revised** — the component is a `port`; its halves are **send** and **deliver**, so the viewpoint question does not arise. `ingress`/`egress` stay participant-relative and name **queues only** |

⚠ **This table said "open" for 1, 4 and 5 while the entries above said decided.**
A document contradicting itself is the exact defect build 44 was written to
catch, and it sat here for a week in the one document whose job is to settle
what words mean.

**All five are now decided, and none are executed** — see
[`BUILD-49-vocabulary.md`](BUILD-49-vocabulary.md), which is parked on
`rename/vocabulary` until the new frame works.

**The layer design these serve is in [`DESIGN-layers.md`](DESIGN-layers.md)** —
switch and router, the three-and-two lookup split, RT as a set intersection, and
why qualified addressing is a precondition rather than a feature.
