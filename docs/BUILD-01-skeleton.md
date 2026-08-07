# Build 01 — the skeleton

> The first build. A tenant that forwards envelopes end to end, with three mock
> agents. Read alongside [`CONTRACTS.md`](CONTRACTS.md) and your module's LLD.
>
> **Base every lane on `main`.** Branch `<lane>/<what>`, push to origin. Done
> means pushed.

## 1. What "working" means

One round trip, in a container, on the lab host:

```
  POST /agents/alice/messages
        │
        ▼  api egress ──► router ──► alice ingress ──► adapter ──► alice's window
                                                                        │
  GET /messages/{cid}  ◄── api ingress ◄── router ◄── alice egress ◄── send
```

Plus, from the same running tenant:

- `a → nobody` (a name not in the roster) is dead-lettered, not a crash
- broadcast reaches all three agents and stops at the tenant
- bringing the container up twice converges rather than duplicating

Everything on that path is in the five LLDs. Nothing in a §7 is in scope — do
not solve deferred problems.

## 2. The mock office

The agents are **three plain interactive shells** in tmux windows: `alice`,
`bob`, `carol`. No agent CLI, no credentials on the host.

This is legitimate rather than a shortcut — `LLD-tmux-host` §5 already says what
runs in a window is configuration, not that module's opinion. A shell is the
right mock because the reply path needs the window to *run* `send`, which only a
shell can do.

A delivered message pastes into a shell, which will try to execute it. Put a
stub on `PATH` named for the opener's first token so delivery lands as a
timestamped line in a file — an assertion a test can make, rather than a human
squinting at a pane. `tmux capture-pane` is a fine backstop and does not touch
`LLD-adapter-tmux` §7, which defers the *adapter* putting pane output on the
bus, not a harness reading one.

**Known not covered.** The §4 paste rules exist for TUIs; a shell exercises the
mechanics but not the behaviour they defend against. That is accepted — the
sequence is already proven in production use — and it is why delivery gating
stays deferred pending measurement against real CLIs.

⚠ Once it runs, `SADD` a fourth agent into the roster live. The polling
machinery in `LLD-bus-and-router` §3.2 is otherwise shipped unexercised, and
this is the one cheap test of it: a window should appear, a consumer should
start, the agent should become routable.

## 3. Lanes

| Lane | Owns | Reads |
|---|---|---|
| `bus` | `flock.bus` library, then `flock.router` | `LLD-bus-and-router` |
| `tmux` | `flock.tmuxhost`, then `flock.adapter` | `LLD-tmux-host`, `LLD-adapter-tmux` |
| `api` | `flock.api` | `LLD-api` |
| `architect` | `container/`, integration, `main` | `LLD-container` |

**The library surface is frozen in `CONTRACTS.md` §2**, so `tmux` and `api` code
against it from day one rather than waiting on `bus`. If it needs to change,
that is a message to `architect` before it is a commit.

Land the tmux **host** before the adapter — the adapter attaches to windows it
does not create, and a missing window is a dead-letter, not something to repair
(`LLD-tmux-host` §6).

## 4. The lab host

`ssh h-lab@172.16.0.14` — Docker 29.7.2, Compose v5.4.0, no sudo needed.

⚠ **An `h-cli` container runs there and is off limits.** Its blast radius is
everything named for compose project `h-cli-dev`: the container, network
`h-cli-dev_default`, volumes `h-cli-dev_*`, image `h-cli:latest`.

The realistic way to break it is not naming it — it is a blanket command. **Never
run `docker system prune`, `docker stop $(docker ps -q)`, or `docker compose
down` from a directory you did not create.** Namespace everything we build under
compose project `h-flock-<tenant>` so teardown is always scoped.

It publishes no host ports and the host listens only on SSH, so any port is free
for the api. Bind it to loopback anyway (`LLD-api` §6) and reach it over an SSH
forward.

## 5. Reporting

`jira done` then message `architect` with **file paths**, the **contract** you
implemented or changed, and **status**. Verify it is pushed, not just committed.
