# Parked

Things decided-but-not-done, so they live somewhere other than a chat log.
Each says *why* it is parked — an item with no reason is either work or noise.

Deferred *design* questions stay in each LLD's §7. This is the operational list.

## Agents in windows

**Onboarding for `codex` and `agy`.** `container/Dockerfile` pre-seeds
`hasCompletedOnboarding` for `claude` only. The other two CLIs the base image
ships have their own first-run state and will land on their own setup screens.
The failure is silent and specific to us: an agent in a headless window that
stops on a setup prompt never starts, while the roster says it exists and the
router keeps routing to it.
→ find each CLI's equivalent marker, seed all three the same way.

**Credentials.** No `~/.claude/.credentials.json` and no `ANTHROPIC_API_KEY` in
the image, so a CLI reaches its login prompt and stops. An interactive login
works but does not survive a rebuild, since nothing is mounted or persisted.
→ needs a decision: mounted credentials file, or an env var. The mount keeps the
secret out of every pane's environment, which is why `API_TOKEN` was scoped to
the api process (`LLD-container` §3).

**The `startAgent` flip.** Windows still run `bash -il`. `create_window` already
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

**Boards.** The api serves `/board` and nothing writes one, so they read empty.
Agents have no equivalent of `jira list` / `jira consume`.

## Authority between agents

**Agents have no model of who has standing, and correctly refuse to take
direction.** Observed in the first live discussion run: asked why it had not
followed a peer's instruction, an agent answered *"bob isn't my principal — you
are. His messages reach me the same way any data does."* That is right, not a
malfunction — the bus proves **who** sent a message and says nothing about **who
may direct whom**, and nothing in an agent's context supplies it.

The office already has the word: `AGENTS.md` uses **lead** (*"if you're the
lead, follow up with them or reassign"*). Reuse it rather than inventing one.
→ needs a name in the environment and a line in the per-agent guide.

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

## Correlation

**Replies to a waiting HTTP client.** Build 02 onward is inject-only: `POST`
returns `202` and nothing comes back on that request. The two shapes are in
`LLD-api` §7 — an expiring table keyed by `correlation_id`, or ephemeral named
agents so the bus does the demultiplexing. ⚠ Not in the api process's memory.
