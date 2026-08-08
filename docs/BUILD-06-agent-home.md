# Build 06 — give an agent a home and a peer list

> One lane, `tmux`. Everything here lands in `flock.tmuxhost` and `flock.tmux`,
> because that module already owns *"what runs in the window, in the working
> directory it is told to use, with the environment it is given"*
> (`LLD-tmux-host` §5). We have been honouring half that sentence.
>
> **Base on `main`.** Branch `tmux/build-06-agent-home`, push to origin.

## ⚠ `export TMUX_TMPDIR=$(mktemp -d)` before any bare tmux command

`flock.tmux.require_isolated_tmux` now enforces this, but only for code paths
that go through it. See [`BUILD-01-skeleton.md`](BUILD-01-skeleton.md) §2.

## 1. Why

Three agents were started in one tenant and given no deliberate context. One
mapped the whole infrastructure by finding `REDIS_URL` and reading the roster
hash directly; the other two read an env var and stopped. **The context an agent
ends up with is currently a function of how thorough it feels**, not a decision
we made — and the roster it found is a routing table, full of a word (`VAB`) that
means nothing to an agent and rows (`api`, `host`) that are not peers.

`LLD-bus-and-router` §1 already promises the agent-facing model: *"an agent never
learns a queue name. Its entire surface is `send`, `receive`, and the name of
whoever it is addressing."* Nothing told them that, so they went looking.

## 2. Three changes

**A home per agent.** Each window starts in `/workdir/<agent>` — created if
missing, owned by `ubuntu`. Today every window starts in `/app`, which is
h-flock's own source, so a CLI reads *our* code as its project.

`flock.tmux.create_window` gains `cwd` (`CONTRACTS` §2, already updated), passed
to tmux as `-c`. Default `/workdir/<agent_name>`.

**A clean peer list in the environment.** `AGENT_PEERS=bob,carol` — the other
agents this one can talk to. **Not** the roster: no `VAB`, no self, and none of
the fixed agents. It is a conversational peer list, not a routing table.

Today `AGENTS=alice:tmux,bob:tmux,carol:tmux` is visible, which is the
container's seed string and is why "check your env for peers" produced a
confusing answer.

**A guide in that home.** `/workdir/<agent>/AGENTS.md`, written at window
creation, naming *that* agent:

```markdown
You are **alice**, an agent in tenant `hq`.

Your peers are **bob** and **carol**. Message one with:

    send bob can you take a look at this?
    send all standup in five

A message arrives in your terminal as `[message from bob] …`. Reply by name —
`send bob …`. That prefix is the whole reply mechanism; nothing routes a reply.

This directory is yours. Work in it.
```

Rewrite it on each window creation so it never disagrees with the roster.

⚠ **Do not put the roster, queue names, `VAB`, or Redis in it.** Those are ours,
not theirs, and the one agent that went looking is evidence that a muddled
answer sends them digging for a better one.

## 3. What this does not fix

An agent can still read the roster directly — `REDIS_URL` is in the environment
because `send` needs it, and `redis-cli` is on `PATH`. That is the Redis ACL item
in [`TODO.md`](TODO.md) and it is deliberately still parked. This build removes
the *reason* to go looking, not the ability.

## 4. Done when

- each window starts in `/workdir/<agent>`, and the directory exists
- `echo $AGENT_PEERS` in alice's window prints `bob,carol` — no self, no VAB
- `/workdir/alice/AGENTS.md` exists, names alice, lists bob and carol
- a `StartAgent`'d agent gets all three the same way, without a container restart
- `StopAgent` leaves the directory alone — a home outlives a window

## 5. Reporting

`jira done`, then message `architect` with paths, the `create_window` signature
you ended up with, and status.
