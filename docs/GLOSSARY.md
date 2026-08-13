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

### the roster value — `tmux` / `api` / `control` ⚠ *needs a name*
**How a participant is attached, and therefore how delivery happens.** A window,
a mailbox, or an opener.

- **networking:** the port type — a property of the port, not of the frame.
- **currently called:** `vab`, which belongs to the address model above.
- **candidates from the inventories:** `attachment_type` (bus), `port_type`
  (bus, api), `driver` (api). ⚠ **Decision outstanding.**

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

### `adapter` ⚠ *one word, two things*
- `adapter/cli.py` — the `office` command putting an envelope **on** the bus
- `adapter/runner.py` — taking one **off** it and delivering

Opposite sides of the switch, one name. **Decision outstanding.**

### `door`
**An HTTP surface the outside world reaches**: the api door (`:8080`) and the
session door (`:8081`).

### `producer` / `recipient` ⚠ *mixed pair*
The source and destination addresses of an envelope. producer↔consumer,
sender↔recipient, **source↔destination** — the model says the third.
352 occurrences, and they are wire fields, so changing them is an envelope v2.

---

## Elsewhere

### `endpoint` ⚠ *collides*
Currently **the model an agent talks to** — `agent:<name>:endpoint`,
`ENDPOINT_*`, vLLM or ollama. In the network model an endpoint is an addressable
termination, which is the opposite end of the meaning.

- **candidates:** `model_endpoint` (bus), `provider`, `uplink` (tmux).

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

| # | decision | cost |
|---|---|---|
| 1 | name for the roster value now called `vab` | wire + keys + docs |
| 2 | `router` → `switch`? | 38 code, 374 prose |
| 3 | `producer`/`recipient` → `source`/`destination`? | envelope v2 |
| 4 | `endpoint` → ? | keys + env |
| 5 | the two adapters — inbound and outbound names | internal only |
| 6 | the gateway fork: participant or router branch | design, not naming |
| 7 | put the RD in the envelope — qualified recipients? | envelope v2 |
