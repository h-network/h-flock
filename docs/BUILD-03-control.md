# Build 03 — commands and agent lifecycle

> The design is in the LLDs and `CONTRACTS.md`. This file is the delta and the
> lane split.
>
> **Base every lane on `main`.** Branch `<lane>/<what>`, push to origin. Done
> means pushed.

## ⚠ Before you touch tmux

**You are an agent living in a tmux window. Bare `tmux` reaches the server you
are running inside.** Before any `tmux` command, or running `flock.tmuxhost` /
`flock.adapter` outside a container:

```bash
export TMUX_TMPDIR=$(mktemp -d)
```

`flock.tmuxhost` reconciles in both directions — against the office's own server
it deletes every window not in the roster it was given, yours included. It has
destroyed this office once. See [`BUILD-01-skeleton.md`](BUILD-01-skeleton.md) §2.

## 1. What is new

Four kinds, two VABs, and an api that can carry any of them
(`CONTRACTS` §6, `LLD-api` §2–3):

| `kind` | VAB | Payload | Does |
|---|---|---|---|
| `Message` | `tmux` | `{"text": …}` | exists already |
| `Command` | `tmux` | `{"text": …}` | pastes bare — it executes |
| `StartAgent` | `control` | `{"agent": "dave", "cli": "claude"}` | enrol, window, CLI |
| `StopAgent` | `control` | `{"agent": "dave"}` | reverses all three |

`cli` defaults to `claude`.

## 2. Lanes

**`api`** — `POST /agents/{agent}/envelopes`

- body carries `kind` and `payload`; `{"text": …}` stays as sugar for `Message`
- **validate neither.** The api cannot know which kinds are openable — that is a
  fact about adapters, discovered at the far edge (`LLD-api` §3)
- `/messages` goes; nothing depends on it

**`tmux`** — `flock.tmux` shared library, and the `Command` opener

- extract `create_window`, `kill_window`, `list_windows` and the paste sequence
  out of `tmuxhost` and `openers` into `src/flock/tmux/`, and have both call it
- `Command` opener: same paste sequence as `Message`, **without** the
  `[message from …]` prefix — that prefix is the entire difference and the whole
  security boundary (`LLD-adapter-tmux` §3)

**`bus`** — the `control` VAB

- a new delivery routine for VAB `control`, dispatched like `tmux` is
- `StartAgent`: `HSET` roster → `SET` launch key → create the window via
  `flock.tmux`. **Roster first.**
- `StopAgent`: `HDEL` roster → `DEL` launch key → kill the window. Roster first
  here too — reversed, a crash makes the host recreate the window and the agent
  you killed comes back
- `host` becomes a roster row with VAB `control`, seeded by the container

**`architect`** — container, integration, `main`

- seed the `host` row, run it, report

## 3. Done when

```bash
POST /agents/bob/envelopes   {"kind":"Command","payload":{"text":"touch /tmp/it-ran"}}
POST /agents/host/envelopes  {"kind":"StartAgent","payload":{"agent":"dave"}}
POST /agents/host/envelopes  {"kind":"StopAgent","payload":{"agent":"dave"}}
```

- the `Command` file exists in bob's container
- `dave` appears in the roster **and** as a tmux window, and is immediately
  addressable — `send dave hi` lands
- `StopAgent` removes both, and `dave` does not come back on the next reconcile
- an unknown kind still dead-letters with a reason rather than erroring

## 4. Reporting

`jira done`, then message `architect` with **file paths**, the **contract** you
implemented or changed, and **status**. Verify it is pushed, not just committed.

⚠ Do not edit another lane's files. Build 01 and 02 both lost time to two lanes
writing the same module. If you need something in someone else's file, say so.
