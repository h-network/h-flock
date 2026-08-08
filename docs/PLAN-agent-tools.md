# Plan — the agent-facing tools

> Decided, not built. Replaces the single `send` command.

## 1. Why one general command was wrong

`send --kind StartAgent <agent> --payload '{"agent":"dave"}'` requires an agent
to know that kinds exist, what they are called, and what payload each takes.
That is the envelope model — ours, not theirs — and learning it means reading
docs or source.

**A focused command needs none of it.** `hire dave` requires knowing nothing
about a bus. Same principle as taking `REDIS_URL` out of the environment: remove
the reason to look, not the ability.

## 2. The set

| Command | Does | Envelope underneath |
|---|---|---|
| `sendMessage <agent> <text>` | a message to one agent | `Message` |
| `sendBroadcast <text>` | a message to every agent | `Message`, `recipient: all` |
| `peers` | who is in this office | roster read, no envelope |
| `hire <name> [options]` | enrol an agent: roster row, home, window, CLI | `StartAgent` |
| `letGo <name>` | remove one, reversing all of it | `StopAgent` |
| ~~`sendCommand`~~ | **parked** — text executed in a peer's window | `Command` |

⚠ **`sendBroadcast` takes no recipient**, which means the reserved name `all`
never appears in an agent's world at all. One more piece of the model that stops
needing explanation.

⚠ **It reaches agents only — never `api`, never `host`.** A broadcast is a
message to the room; the fixed agents are plumbing and are not in it.

Satisfied by the mechanism already chosen (`TODO.md`): the router fans out to
every roster member and the non-agent endpoints **discard**, rather than the
router learning to filter — which would mean reading roster values and breaking
invariant 8.

The visible cost: envelopes still *reach* `api` and `host` before being dropped,
so a broadcast in a three-agent tenant logs a fan-out of four with two discards.
Semantics right, traffic not zero. If that ever matters, the alternative is this
command expanding the list itself and sending N individual messages, so `all`
never goes on the bus — at the price of N sends and the peer list living in the
tool.

## 3. Two naming traps

⚠ **Do not call it `startAgent`.** The base image already ships `startAgent`,
which launches a CLI *in the current window*. Ours enrols a *new agent into the
tenant*. Same name, opposite meaning, both on `PATH` in the same shell.
`LLD-tmux-host` §5 already calls the concept *"hiring and letting go"*, which is
where `hire` / `letGo` come from.

⚠ **`sendMessage` is h-office's name, and h-office's is flag-based:**

```
sendMessage -o <office> -a <agent> -m "text"     h-office
sendMessage <agent> <text>                        proposed here
```

Taking the name with a different syntax is worse than a different name — someone
who knows one types it and gets an error. **Decide: match both, or neither.**

## 4. What happens to `send`

The focused commands call `flock.bus.send()` directly. There is **no generic
`send` on an agent's `PATH`** — leaving one there reintroduces exactly the
discovery path this removes.

`--kind` does not disappear; it stays as the library call underneath, reachable
by anything of ours that needs a kind no command covers yet.

## 5. `hire` carries the account

`hire` is where profiles land, since enrolling is when an account is chosen:

```
hire dave --cli claude --profile work
```

- `--cli` already exists as the `launch` key, written by `StartAgent` and read
  by `flock.tmuxhost`
- `--profile` is new and needs [`PLAN-profiles.md`](PLAN-profiles.md) first — a
  profile is an **account/email**, and a non-`default` one costs an interactive
  login before it can be used

So `hire` ships in two stages: without `--profile` now, with it once profiles
exist. **Do not invent a second mechanism for accounts inside `hire`.**

## 6. Discovery

`OFFICE_TOOLS=sendMessage,sendBroadcast,peers,hire,letGo` in the window
environment — static for the image's lifetime, so it cannot go stale the way
`AGENT_PEERS` did (see [`TODO.md`](TODO.md)).

Every one carries a real `--help`. ⚠ **Help must never require the
environment** — `send --help` currently fails without `AGENT_NAME`, which is the
first thing anyone types.
