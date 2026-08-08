# Build 02 — kicked adapters

> Rework, not new ground. The design is in the LLDs; this file is only the delta
> from what is currently on `main` and who owns which part.
>
> **Base every lane on `main`.** Branch `<lane>/<what>`, push to origin. Done
> means pushed.

## ⚠ Read this before you touch tmux or the adapter

**You are an agent living in a tmux window. Bare `tmux` reaches the server you
are running inside.** Before any `tmux` command, before `python -m
flock.adapter`, before `python -m flock.tmuxhost`, outside a container:

```bash
export TMUX_TMPDIR=$(mktemp -d)     # a scratch server, not the office's
```

This is not advice. `flock.tmuxhost` reconciles windows in both directions, so
against the office's own server it deletes every window whose name is not in the
roster it was given — `architect`, `bus`, `tmux`, `api` included. It has already
destroyed this office once. Full reasoning in
[`BUILD-01-skeleton.md`](BUILD-01-skeleton.md) §2.

## 1. What changed in the design

Adapters were daemons. They are not any more. `LLD-adapter-tmux` §2 and
`LLD-bus-and-router` §3.2–3.3 are the authority; the short version:

- The router, having written an ingress queue, **kicks** `flock.adapter <agent>`
  — one fixed command, fire and forget. No type, no list, no return code.
- An adapter is **invoked, delivers one envelope, exits.** Nothing is held open
  between deliveries. No supervisor, no per-agent thread, no roster polling at
  the edge.
- The roster becomes a **`HASH` of agent → VAB** — the MAC table. **The router
  reads its fields, an adapter reads its values.** The router must never call
  `vab()`; that is what keeps invariant 8 structural.
- A **busy tag** serialises delivery per agent. A kick that finds it set waits
  for it to clear, then delivers its own envelope. A crash leaves it set, on
  purpose — see `LLD-bus-and-router` §3.3.

## 2. Lanes

**`bus`** — `flock.bus.roster`, `flock.router`

- `members` → `HKEYS`, `is_member` → `HEXISTS`, new `vab()` → `HGET`
  (`CONTRACTS` §2)
- router: after the `RPUSH`, spawn the kick and do not wait on it
- router: delete the hardcoded `{"api"}` — `api` is a roster row now
- router: it may call `members`/`is_member` and **never** `vab`

**`tmux`** — `flock.adapter`

- delete `supervisor.py` and `consumer.py` entirely
- `openers.py` is correct and stays as it is
- new `python -m flock.adapter <agent>`: take the busy tag, `HGET` the VAB,
  dispatch, deliver the one envelope it was kicked for, clear the tag, exit
  (`CONTRACTS` §4)

**`api`** — `flock.api`

- delete the `_receiver` thread, `ReplyStore`, and `GET /messages/{cid}`
- the api holds no loop; it is an agent with VAB `api` and gets kicked like any
  other (`LLD-api` §4)
- build 02 is inject-only: `POST` returns `202` and nothing comes back on that
  request

**`architect`** — container, integration, `main`

- entrypoint seeds the roster with `HSET`, `AGENTS` becomes `name:vab` pairs
- runs it on the lab host and reports

## 3. Done when

The same round trip as build 01 — `POST` → alice's pane → `send` back → the api
receives it — with:

```
  ps         no adapter process at rest, none per agent
  redis      exactly one blocked client: the router
  logs       four records per envelope, joinable on stream_id
```

and two envelopes fired at one agent back to back arrive as two separate,
correctly ordered pastes, not fused into one input.

## 4. Reporting

`jira done`, then message `architect` with **file paths**, the **contract** you
implemented or changed, and **status**. Verify it is pushed, not just committed.
