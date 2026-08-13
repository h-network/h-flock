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
- **state:** ⚠ **in the keys, absent from the envelope.** `"recipient": "alice"`
  is a bare name — the distinguisher never reaches the packet, which is why
  qualified recipient names are listed as undesigned in
  `LLD-bus-and-router` §7 and why an unresolvable name dead-letters.

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
lifecycle endpoint. Defined in `LLD-bus-and-router` §1 and under-used since:
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

### `switch` versus `router` ⚠ *decision outstanding*
The forwarding component moves envelopes between participants **inside one
tenant** by destination name. That is switching. It is currently the module
`flock/router`, while `HLD.md:17` opens with `| L2 switch | h-flock |`.

⚠ **If the gateway is built, `router` will be the wrong name twice** — the L2
component called router, and the L3 component called gateway. `bus` proposed
`tenant switch`. 38 code occurrences, 374 in prose.

### `gateway` *(reserved, not built)*
**The L3 router**: reads what the switch will not, applies policy, resolves
qualified names, re-addresses. Reached **by name, like any participant** — as
hosts reach a default gateway.

⚠ Designed twice in the same document: `LLD-bus-and-router` §7 as a branch in
the router, §3.2 as a participant with its own attachment type. **Only one can
be built.**

### `kind`
**What the payload is.** The ethertype: the switch ignores it, an opener at the
far edge reads it.

### `opener`
**The thing that knows how to deliver one `kind`** at the far edge.

### ✅ `egress_adapter` / `ingress_adapter` — was `adapter` for both
- **`egress_adapter`** — `adapter/cli.py`, the `office` command putting an
  envelope **on** the bus, writing the participant's egress
- **`ingress_adapter`** — `adapter/runner.py`, taking one **off** and delivering

⚠ **`ingress` and `egress` are relative to the PARTICIPANT**, as a host's rx and
tx — not to the switch. The switch has no queues of its own: it reads a
participant's egress and writes a participant's ingress.

⚠ **This choice was deliberate and the alternative was rejected.** Naming them
from the switch's side is what networking does for *device ports* — but these
queues hang off participants, and hosts name their own queues. Flipping the
viewpoint would invert the meaning of `agent:<name>:egress` without breaking
anything mechanically, so every existing log line and document would quietly
read backwards.

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
| 5 | adapter names — and from whose viewpoint | ✅ **decided** — `egress_adapter`/`ingress_adapter`, **participant-relative**; the switch-relative alternative was considered and rejected |

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
