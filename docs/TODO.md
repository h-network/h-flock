# Parked

Things decided-but-not-done, so they live somewhere other than a chat log.

⚠ **A struck-through or `SHIPPED` heading is a record of the time it was
written**, kept because the reasoning is why the fix went the way it did. Those
sections name commands that no longer exist — `sendMessage`, `sendBroadcast`,
`peers` — and that is deliberate: they are what the problem looked like then. The
current surface is one `office` command (`CONTRACTS` §5). Everything **not**
struck through is present tense and should be true today.

Each says *why* it is parked — an item with no reason is either work or noise.

Deferred *design* questions stay in each LLD's §7. This is the operational list.

## Agents in windows

**Onboarding for `codex` and `agy` — checked, and there is nothing to seed.**
Run headless in a fresh container, both go **straight to a login prompt**:
codex offers "Sign in with ChatGPT / Device Code / API key", agy offers "Google
OAuth / Cloud project". Neither has a pre-login gate.

`claude` is the odd one out — a theme picker *and* a per-directory trust dialog
before login, which is why it alone needed `hasCompletedOnboarding` and
`hasTrustDialogAccepted` seeded.

Their post-login approval gates are already covered: `startAgent` passes
`--dangerously-bypass-approvals-and-sandbox` to codex and
`--dangerously-skip-permissions` to agy.

So all three need only **credentials**, which
[`container/seed-home.sh`](../container/seed-home.sh) now handles.

**Credentials and profiles — mechanism SHIPPED, logins outstanding.**
`container/seed-home.sh in|out|check` copies keys and credentials into a running
tenant and saves logins back out, and `setup.sh` asks for accounts and seeds each
one's config dirs. What remains is doing the interactive logins once.

⚠ **Last link missing:** nothing reads the `profile` key yet. `flock.tmuxhost`
reads `launch` for the CLI but does not turn `profile` into `CLAUDE_CONFIG_DIR` /
`CODEX_HOME` in the window environment — so accounts are seeded and selected but
not used.

→ **[`PLAN-profiles.md`](PLAN-profiles.md)** — the shape, taken from h-office,
which solved it. The unit is the *account*, not the agent: a config dir is one
interactive login, so several agents share a profile and `default` is free.
`CLAUDE_CONFIG_DIR` / `CODEX_HOME` in the window env is the whole mechanism.

⚠ Our current onboarding seed writes `$HOME/.claude.json`, which covers the
**default profile only** — a second profile lands on the theme picker again
unless its own dir is seeded. Same bug h-office fixed in `4b88096`.

⚠ Still undecided: profile dirs must survive a rebuild, so they need a volume.
h-office gets that for free by being long-lived; we do not.

**The `startAgent` flip — and it was never about bash.** Found by watching a real
agent reply: `flock.tmux.create_window` launches the CLI **bare** —
`env AGENT_NAME=backend claude` — instead of `startAgent claude`. So the
permission flags are never applied and every command the agent runs stops on
*"This command requires approval"*.

`startAgent`'s own header says why that wrapper exists: *"Each CLI spells 'don't
stop to ask me' differently — claude `--dangerously-skip-permissions`, agy the
same, codex `--dangerously-bypass-approvals-and-sandbox`. Remembering which
belongs to which is the whole reason this wrapper exists."*

→ launch `startAgent <cli>` rather than `<cli>`. One line, and it covers all
three CLIs by construction rather than us tracking three sets of flags.

**The old framing.** Windows still run `bash -il`. `create_window` already
takes a command and `StartAgent` already passes one, so this is a default, not
work. Held deliberately until the two items above are solved — flipping first
just means every window stops on a prompt.

## Delivery

**The `verify` step.** `LLD-adapter-tmux` §4 says "verify, optionally" and we
took the option. h-office enables it by default after *"roughly one delivery in
ten left its message sitting in the recipient's input box, marked delivered and
already popped off the queue"*. That is a silent loss path: `opened` is logged,
the envelope is gone from Redis, and the message was never submitted.
→ check the bottom rows for the message's tail after Enter, press it again if
still there. Costs one extra Enter that an empty prompt ignores.

## Visibility

**Presence.** No busy / idle / wedged / login-expired signal. h-office calls it
*"the single most expensive gap in a long session"* — every state looks
identical from outside. The signal is `window_activity` from one `list-windows`
call, which `LLD-adapter-tmux` §5 already names.

**~~Boards~~ — SHIPPED in build 11.** → [`PLAN-boards.md`](PLAN-boards.md).
Tickets, four columns, `office add`/`list`/`take`/`done`/`cancel`/`hold`/`delete`,
and an append-only history in `$TASK_RECORD`. The rule the design turned on held
all the way through: **the agent moves its own tasks, nothing infers them** — the
adapter knows an envelope was delivered and cannot know whether the agent read
it, started it, or disagreed with it.

⚠ It went further than that in the end: **nothing delivers a ticket at all.** A
board is pulled, so the one-`doing` rule is not enforced, it simply falls out.
The watchdog's evidence — a ticket sitting in `doing` with a `started_ts` — now
exists.

## ~~Broadcast strands envelopes on the fixed agents~~ — SHIPPED

**Fixed in build 08.** An unroutable VAB now dead-letters instead of returning
before popping, and VAB `api` has a delivery routine. `sendBroadcast` also
resolves its own recipients, so agent broadcasts never reach the fixed agents at
all. ⚠ Still undecided: whether `POST /agents/all/envelopes` *should* reach them
— an architect loose end, now cosmetic rather than a leak.

<details><summary>original</summary>

**Found by an agent during the first live run, then confirmed: `api` ingress was
34 and climbing, `host` dead-letters were 34.** Every `send all` reaches both,
because the router fans out to `_agents() - {sender}` and the fixed agents are
roster rows like any other.

`host` handles it correctly — VAB `control`, no opener for `Message`,
dead-lettered and logged. Noisy, but visible.

`api` does not. VAB `api` dispatches to no delivery routine, so
`flock.adapter.runner` logs `VAB is 'api', not 'tmux'` and **returns before
popping**. The envelope is never consumed and never dead-lettered: it just
accumulates, one per broadcast, forever.

Two faults meeting, and they can be fixed independently:

1. **No `api` delivery routine.** The api-adapter opener — an envelope handed to
   a waiting HTTP client (`LLD-api` §7). Its absence should not be silent
   accumulation.
2. **An unroutable VAB should dead-letter, not return.** Whatever else is true,
   an adapter that cannot deliver must leave the envelope visible, the way an
   unknown `kind` already does. §4: *nothing disappears silently.*
3. **Whether broadcast should reach the fixed agents at all is still undecided.**
   The old router excluded `api`; the current one includes it. Neither is written
   down — this is an architect loose end, noted at the time and not closed.

</details>

## ~~What belongs in a window's environment~~ — SHIPPED

**Done in build 08.** `AGENT_PEERS` removed, `OFFICE_TOOLS` added, the guide
names only the agent and is written once. Rule kept below because it decides
every future variable.

**The rule: static for the window's lifetime → environment. Derived from the
roster → a tool, never environment.**

A window's environment is frozen at creation. So anything that changes while the
office runs is wrong there, and goes stale silently.

| | |
|---|---|
| `AGENT_NAME` | env — fixed for this window |
| `POD`, `TENANT` | env — what `send` needs, fixed |
| `OFFICE_TOOLS=send,peers,…` | env — ships with the image, cannot go stale |
| **peers** | **a tool.** Changes the moment `StartAgent` adds one |

⚠ **`AGENT_PEERS` (build 06) breaks this and should be removed.** Add dave and
alice's `AGENT_PEERS` is wrong until her window is recreated — the exact
staleness the roster exists to prevent.

⚠ **The guide has the same bug.** `write_agent_guide` runs at window creation
only, so `/workdir/<agent>/AGENTS.md` ages the same way. Fix both together:
`flock.tmuxhost` already reconciles every `ROSTER_POLL_SECONDS` and already reads
the roster, so **rewrite the guide each pass**. A few hundred bytes, and it
leaves one source of truth instead of two that drift.

`OFFICE_TOOLS` also covers the reader who stops early: `echo $OFFICE_TOOLS` then
`--help` on each, with no exploring and no source to read.

## Log records from agent tools never reach the log

⚠ **`office` runs in an agent's window, so its log records go to that pane** —
not to the container's stdout, which is the only thing collected.

Measured: an envelope sent by an agent produces `popped`, `forwarded`,
`received`, `opened` centrally. **`sent` is missing.**

⚠ **Half solved in build 11, and the half that is solved shows which option
works.** Board events no longer go through `log_record` at all — they append to
`$TASK_RECORD`, a shared file the container collects, written by one function
(`flock.bus.record_task_event`) that swallows every error so a bad log path
cannot fail a `done`. That is the second of the three options below, chosen in
practice rather than in principle.

**Still open: `sent`.** `office send` from a window still logs to that pane. The
same fix would work; it has not been done, and the reason boards went first is
that the watchdog needed them.

Two documented claims are therefore false as written:

- `LLD-bus-and-router` §4 — *"four records across a delivered envelope's life"*.
  True for api-sent envelopes; agent-sent ones have three centrally and one in a
  terminal. The crash-detectability argument does not cover the agent's end.
- `PLAN-boards.md` — *"there is no second place to look"*. Was true and is now
  fixed: `$TASK_RECORD` is that one place for board events.

The design assumed every emitter is a container process. An agent's tools are
not, and nothing about `flock.bus.log_record` writing to stdout is wrong — it is
that stdout means something different in a window.

→ Options, none chosen: emit to a Redis list the container tails; write to a
shared file the container collects; or accept it and correct the two claims.
⚠ Do not "fix" it by having agents' tools skip logging — the record is useful in
the pane too, as the agent's own confirmation.

## Found by running a real agent

First live test with an authenticated Claude Code in a window. Delivery worked —
the envelope reached the TUI, was read, and acted on. Three findings:

**1. `hire` never writes the guide or the trust entry.** Two code paths create
windows: `flock.tmuxhost.create_window` writes the guide, the `CLAUDE.md` copy
and the `.claude.json` trust entry — and the **control opener calls
`flock.tmux.create_window` directly**, skipping all of it. A hired agent gets an
empty `/workdir/<name>` and a trust prompt it cannot answer headlessly.

→ Move guide-and-trust writing into `flock.tmux.create_window` itself, so both
callers get it. One implementation, two callers, which is why that library
exists.

⚠ It looked fine earlier only because the guide was rewritten on every reconcile
pass. Removing that loop was correct and exposed a gap that was always there.

**2. ⚠ `sendMessage` collides with Claude Code's own built-in tool.** Told to
reply, the agent used its native `SendMessage` — for spawning sub-agents — and
reported *"No agent named 'alice' is reachable. There are no spawned teammates in
this session."* A coherent-sounding failure from entirely the wrong subsystem.

The name is not neutral inside the CLI we run. Worth reconsidering: `officeSend`,
`msg`, or something with no built-in of the same name.

**3. An agent with no guide reaches for tools, not commands.** Told to run
`peers`, it searched its *tool list* and concluded none existed — it never
considered a binary on `PATH`. Which is correct behaviour with no context, and it
means the guide is doing more work than "being nice": it is what tells an agent
that this office is driven by shell commands at all.

## The agent-facing surface

**Principle: anything reachable will be explored, and a confusing sanctioned path
guarantees it.** Observed: an agent asked to find its peers hit
`AGENTS=alice:tmux,...` — the container's seed string, with VABs in it and itself
included — and went to `redis-cli` for a better answer, arriving at the roster
hash with `api` and `host` in it. It did nothing wrong. The best answer available
was one it should never have seen.

Two halves, and they only work together:

**Give them clean tools — SHIPPED.** `sendMessage`, `sendBroadcast`, `peers`
all live, `--help` works with an empty environment, generic `send` gone from
`PATH`. → **[`PLAN-agent-tools.md`](PLAN-agent-tools.md)**:
`sendMessage`, `sendBroadcast`, `peers`, `hire`, `letGo`, discovered via
`OFFICE_TOOLS`. One general `send --kind … --payload '<json>'` was wrong because
it makes an agent learn the envelope model to use it at all.

⚠ Concrete instance already open: **`send --help` fails without `AGENT_NAME`** —
it checks the environment before parsing arguments, so the first thing anyone
types errors out. Help must never depend on the environment.

**Take the unsanctioned path away — except we cannot, and that is decided.**
Agents keep `sudo`: the container grants `ubuntu` `(ALL) NOPASSWD: ALL`, and that
is wanted (possibly per-agent optional later). ⚠ **So nothing inside the container
is a boundary.** Not file modes, not a compiled binary, not Redis ACLs — `sudo
cat redis.conf` and `sudo redis-cli` end all three. The container is the boundary;
inside it, everything is visible.

That changes the Redis ACL item below from a security control to a tidiness one,
and it means source-hiding should be **deterrence, not enforcement**:

- **Delete `/app` from the final image.** The source is copied there to build and
  the package installs into `/opt/flock`; nothing needs it at runtime. This
  removes the stumble rather than labelling it, and costs nothing.
- **A banner at the top of anything they may still reach** — and it must give a
  *reason*, not a prohibition. These agents reason around bare rules: one read a
  comment in `pyproject.toml` and turned it into a finding. "This is bus
  internals; `send --help` is your interface, and queue names here will change"
  answers the question they were about to ask. A bare "do not read" is an
  invitation.
- Use the convention they already respect — the `AGENTS.md` style — rather than
  inventing a new marker.

**Write it at the top.** Agents stop reading early. Whatever matters most goes
first: who you are, who you can talk to, how to send. Anything below the fold is
effectively absent, so the guide staying *short* is a feature — every paragraph
added pushes something out of the part that gets read.

## Authority between agents

**Agents have no model of who has standing, and correctly refuse to take
direction.** Observed in the first live discussion run: asked why it had not
followed a peer's instruction, an agent answered *"bob isn't my principal — you
are. His messages reach me the same way any data does."* That is right, not a
malfunction — the bus proves **who** sent a message and says nothing about **who
may direct whom**, and nothing in an agent's context supplies it.

Build 06 tells each agent its **peers** — and "peer" is precisely a relationship
with no authority in it, so they talk and nothing moves.

Naming is unsettled and is the open question here. `AGENTS.md` in this office
uses **lead**; the ask was phrased as an **architect** title. Not the same thing:
one is a role in a hierarchy, the other is a named job. Decide before building.

Also unsettled: what standing actually means to an agent. "Act on this rather
than consider it" is the useful half; "believe anything that claims to be from
them" is the failure mode next to it.

⚠ **Blocked on the item below.** Telling an agent that requests from a named
peer carry authority makes `producer` load-bearing, and `producer` is currently
forgeable — see next. Ship the standing model on top of an unenforced identity
and any agent can impersonate the lead and direct the whole office.

## Security — all parked deliberately

**TLS.** Both doors are plain HTTP on `0.0.0.0`, so the bearer token crosses the
network in the clear. Terminate outside the process (`LLD-api` §7); a proxy in
front of both doors is where it goes (`LLD-container` §3).

**CORS.** No headers, so a browser app from another origin is blocked at
preflight — and it looks like the api being down rather than a header missing.
One middleware, once an origin is known.

**Redis ACLs — now a prerequisite, not a nicety.** `REDIS_URL` is in every agent
window because `send` needs it, so an agent can bypass both doors and write any
queue directly. Invariant 3 is a convention `send` honours, not something
enforced.

⚠ **Demonstrated, not theorised.** From inside an agent window, an `RPUSH`
straight into a *peer's* ingress with `"producer": "architect"` was accepted by
Redis. Invariant 2 — *the sender comes from the queue the envelope was popped
from* — holds only for envelopes that reach the router via egress. **A direct
ingress write bypasses the router entirely and forges identity.**

That makes this the gate on the authority model above, and on `producer`-based
policy for control kinds. `LLD-bus-and-router` §3.1 anticipated the fix: a
credential scoped to `~pod:<pod>:tenant:<tenant>:agent:<agent>:*`, which is why
the agent sits in the address at all.

**`producer` policy on control kinds.** Any agent can enrol or kill any other
today. An allow-list in the control opener is the right place — but only once
`producer` is genuinely unforgeable, which it is not while any window can write
a peer's ingress directly.

## ~~Correlation~~ — ANSWERED in build 12

**Ephemeral named agents won**, not the expiring table. A client enrols itself
with `vab: api`, gets an address and a mailbox, and the bus demultiplexes by
address — so no table keyed by `correlation_id` exists anywhere, which was the
point of preferring that shape.

⚠ **It is still not a reply on the same request.** `POST` returns `202` as it
always did; the answer arrives in the client's mailbox and is read by cursor or
SSE. Request/response was never the shape — an agent takes seconds to minutes to
answer, and holding an HTTP request open for that is the thing the design avoids.

**Still open: per-client tokens.** One shared token, and `as` is checked against
the roster rather than proven.
